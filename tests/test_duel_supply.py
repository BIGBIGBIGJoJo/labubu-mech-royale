"""Keep usable defense while withdrawing without overriding health recovery."""
import copy
import json
import math
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import test_strategy as fixture


class DefensiveWithdrawalTests(unittest.TestCase):
    setUpClass = classmethod(fixture.StrategyTests.setUpClass.__func__)
    setUp = fixture.StrategyTests.setUp
    weapon = fixture.StrategyTests.weapon
    enemy = fixture.StrategyTests.enemy

    def retreat(self, fraction):
        self.obs['self']['hp'] = fraction * self.obs['self']['max_hp']
        self.obs['mechs'] = [self.enemy(80)]
        report = {'retreat': True, 'phase': 'retreat', 'reason': 'retreat_commitment',
                  'opponents': [5], 'health_recover': fraction < .93}
        with patch.object(self.bot.duel, 'decide', return_value=report):
            return self.bot.act(self.obs)

    def test_healthy_retreat_fires_available_gun_without_stopping(self):
        for fraction in (1., .93):
            with self.subTest(fraction=fraction):
                self.setUp()
                action = self.retreat(fraction)
                self.assertTrue(action['fire'][0])
                self.assertFalse(action['reload'])
                self.assertTrue(self.bot.recover)
                self.assertEqual(self.bot.mode, 'recover')
                self.assertGreater(math.hypot(*action['move']), .5)

    def test_healing_withdrawal_keeps_existing_quiet_fire_gate(self):
        action = self.retreat(.92)
        self.assertFalse(any(action['fire']))
        self.assertTrue(self.bot.recover)

    def test_healthy_withdrawal_does_not_start_slow_laser_charge(self):
        self.obs['self']['weapons'][1] = self.weapon('laser')
        action = self.retreat(1.)
        self.assertTrue(action['fire'][0])
        self.assertFalse(action['fire'][1])


class WeaponAcquisitionTests(unittest.TestCase):
    setUpClass = classmethod(fixture.StrategyTests.setUpClass.__func__)
    setUp = fixture.StrategyTests.setUp
    weapon = fixture.StrategyTests.weapon
    enemy = fixture.StrategyTests.enemy

    def offer_weapon(self):
        self.obs['mechs'] = [self.enemy(100)]
        self.obs['pickups'] = [{'id': 77, 'kind': 'laser', 'pos': [-10, 0, 0]}]

    def test_healthy_acquisition_reuses_one_vetted_winner(self):
        self.offer_weapon()
        original = self.bot.resource_goal
        observed = []

        def resource(*args, **kwargs):
            observed.append((self.bot.recover, kwargs['deadline']-time.perf_counter()))
            return original(*args, **kwargs)

        self.bot.recover = True  # Previous frame's state cannot bias admission.
        with patch.object(self.bot, 'resource_goal', side_effect=resource) as scan:
            action = self.bot.act(self.obs)
        self.assertEqual(scan.call_count, 1)
        self.assertFalse(observed[0][0])
        self.assertLessEqual(observed[0][1], .004)
        self.assertFalse(self.bot.recover)
        self.assertEqual(self.bot.mode, 'loot')
        self.assertEqual(self.bot.telemetry['duel']['phase'], 'acquire')
        self.assertEqual(self.bot.resource_key, ('pickups', 77))
        self.assertIsNone(self.bot.duel.encounter)
        self.assertLess(action['move'][0], -.5)

    def test_acquisition_does_not_change_immediate_take(self):
        self.offer_weapon()
        self.obs['pickups'][0]['pos'] = [1, 0, 0]
        action = self.bot.act(self.obs)
        self.assertEqual(action['take'], 77)

    def test_selected_target_hit_starts_ledger_and_next_damage_accrues(self):
        self.offer_weapon()
        self.obs['events'] = [{'type': 'hit', 'target': 5, 'weapon': 'gun', 'amount': 45}]
        with patch.object(self.bot, 'resource_goal', side_effect=AssertionError('hit starts encounter')):
            self.bot.act(self.obs)
        fight = self.bot.duel.encounter
        self.assertEqual(list(fight['hits']), [(20., 45)])
        self.obs.update(t=20.1, tick=402)
        self.obs['events'] = [{'type': 'damaged', 'by': 5, 'weapon': 'gun', 'amount': 45}]
        self.obs['self']['hp'] -= 45
        with patch.object(self.bot, 'resource_goal', side_effect=AssertionError('ledger retained')):
            self.bot.act(self.obs)
        self.assertIs(self.bot.duel.encounter, fight)
        self.assertEqual(fight['spent'], 45)

    def test_other_target_hit_does_not_fabricate_selected_encounter(self):
        self.offer_weapon()
        self.obs['events'] = [{'type': 'hit', 'target': 1009, 'weapon': 'gun', 'amount': 45}]
        self.bot.act(self.obs)
        self.assertIsNone(self.bot.duel.encounter)
        self.assertEqual(self.bot.mode, 'loot')

    def test_existing_encounter_cannot_be_replaced_for_loot(self):
        self.obs['mechs'] = [self.enemy(100)]
        self.bot.act(self.obs)
        fight = self.bot.duel.encounter
        fight.update(spent=100., finish_used=True)
        self.offer_weapon()
        self.obs.update(t=20.1, tick=402)
        with patch.object(self.bot, 'resource_goal', side_effect=AssertionError('existing fight')):
            self.bot.act(self.obs)
        self.assertIs(self.bot.duel.encounter, fight)
        self.assertEqual(fight['spent'], 100.)
        self.assertTrue(fight['finish_used'])
        self.assertAlmostEqual(self.bot.telemetry['duel']['elapsed'], .1)

    def test_retry_reset_cannot_admit_loot_in_same_decision(self):
        self.obs['mechs'] = [self.enemy(100)]
        self.bot.act(self.obs)
        self.bot.duel.encounter.update(retreat_until=20.1, stop_reason='no_effective_progress')
        self.offer_weapon()
        self.obs.update(t=20.2, tick=404)
        with patch.object(self.bot, 'resource_goal', side_effect=AssertionError('retry remains combat')):
            self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry['duel']['phase'], 'probe')
        self.assertIsNotNone(self.bot.duel.encounter)

    def test_health_multiple_and_urgent_gates_preempt_scan(self):
        for case in ('low_hp', 'below_healed', 'multi', 'hidden_attacker', 'urgent'):
            with self.subTest(case=case):
                self.setUp()
                self.offer_weapon()
                if case == 'low_hp': self.obs['self']['hp'] = 700
                if case == 'below_healed': self.obs['self']['hp'] = .92*1400
                if case == 'multi': self.obs['mechs'].append(self.enemy(100, 20, id=6))
                if case == 'hidden_attacker':
                    self.obs['events'] = [{'type': 'damaged', 'by': 6, 'weapon': 'gun', 'amount': 1}]
                if case == 'urgent': self.obs['self']['in_zone'] = False
                with patch.object(self.bot, 'resource_goal', side_effect=AssertionError(case)):
                    self.bot.act(self.obs)
                self.assertNotEqual(self.bot.telemetry['duel']['phase'], 'acquire')

    def test_nonweapon_winner_is_not_replaced_by_lower_ranked_pickup(self):
        for kind in ('cubes', 'crates'):
            with self.subTest(kind=kind):
                self.setUp()
                self.offer_weapon()
                candidate = (100., [10, 0, 0], kind, (kind, 88), {'id': 88, 'pos': [10, 0, 0]})
                with patch.object(self.bot, 'resource_goal', return_value=candidate) as scan:
                    self.bot.act(self.obs)
                self.assertEqual(scan.call_count, 1)
                self.assertEqual(self.bot.telemetry['duel']['phase'], 'probe')
                self.assertIsNone(self.bot.resource_key)

    def test_missing_blacklisted_and_ineligible_replacement_do_not_defer(self):
        for case in ('missing', 'blacklisted', 'held'):
            with self.subTest(case=case):
                self.setUp()
                self.offer_weapon()
                if case == 'missing': self.obs['pickups'] = []
                if case == 'blacklisted': self.bot.blacklist[('pickups', 77)] = 30.
                if case == 'held': self.obs['self']['weapons'][1] = self.weapon('laser')
                self.bot.act(self.obs)
                self.assertEqual(self.bot.telemetry['duel']['phase'], 'probe')

    def test_failed_scan_restores_previous_recovery_context(self):
        self.offer_weapon()
        self.bot.recover = True
        with patch.object(self.bot, 'resource_goal', side_effect=RuntimeError('fixture error')):
            with self.assertRaises(RuntimeError):
                self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)

    def test_captured_laser_approach_with_real_geometry(self):
        data = json.loads((Path(__file__).parent/'data/duel-weapon-approach.json').read_text())
        hello, obs = copy.deepcopy(data['hello']), copy.deepcopy(data['obs'])
        hello['map']['dir'] = str(fixture.ROOT/'arena')
        bot = fixture.policy.Bot(hello)
        self.assertTrue(bot.map.available)
        self.assertEqual(len(bot.map.prisms), 259)
        # This single-state regression isolates policy/geometry. The final
        # chronological Linux replay measures the actual scheduling budget.
        with patch('time.perf_counter', return_value=100.):
            action = bot.act(obs)
        pickup = next(p for p in obs['pickups'] if p['id'] == 8053)
        stats = bot.stats(obs['self'])
        self.assertTrue(bot.map.move_clear(obs['self']['pos'], pickup['pos'], stats['radius'], stats['height']))
        self.assertEqual(bot.telemetry['duel']['phase'], 'acquire')
        self.assertEqual(bot.resource_key, ('pickups', 8053))
        self.assertEqual(bot.goal, pickup['pos'])
        toward = [pickup['pos'][i]-obs['self']['pos'][i] for i in range(2)]
        self.assertGreater(sum(action['move'][i]*toward[i] for i in range(2)), 0)


if __name__ == '__main__':
    unittest.main()
