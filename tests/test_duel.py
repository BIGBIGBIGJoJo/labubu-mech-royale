"""Policy transitions, real weapon readiness, and integration safety guards."""
import copy
import math
import time
import unittest
from unittest.mock import patch

import test_strategy as strategy_fixture
from duel import DuelController


class DuelTests(unittest.TestCase):
    setUpClass = classmethod(strategy_fixture.StrategyTests.setUpClass.__func__)
    setUp = strategy_fixture.StrategyTests.setUp
    weapon = strategy_fixture.StrategyTests.weapon
    enemy = strategy_fixture.StrategyTests.enemy

    def step(self, t=None, target=None, *, los=True, events=(), urgent=False):
        if t is not None:
            self.obs.update(t=t, tick=round(t*20))
        self.obs['events'] = list(events)
        if target is None:
            target = self.enemy()
        actors = self.obs['mechs'] or [target]
        threats = [{'actor': a, 'd': math.dist(a['pos'][:2], self.obs['self']['pos'][:2]),
                    'los': los, 'risk': 1.} for a in actors]
        return self.bot.duel.decide(self.obs, threats, target, self.bot.stats(self.obs['self']), urgent=urgent)

    def test_healthy_full_hp_mirror_starts_without_prior_hit(self):
        report = self.step()
        self.assertEqual(report['phase'], 'probe')
        self.assertFalse(report['retreat'])
        self.obs['mechs'] = [self.enemy()]
        self.assertTrue(self.bot.act(self.obs)['fire'][0])

    def test_full_hp_two_opponents_preempts_loot_and_held_goal(self):
        self.obs['mechs'] = [self.enemy(80), self.enemy(90, 20, id=6)]
        self.obs['cubes'] = [{'id': 99, 'pos': [5, 0, 0], 'n': 3}]
        self.bot.goal, self.bot.goal_kind, self.bot.goal_until = [5, 0, 0], 'loot', 100
        with patch.object(self.bot, 'resource_goal', side_effect=AssertionError('loot preempted')):
            action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, 'recover')
        self.assertEqual(self.bot.telemetry['duel']['reason'], 'multiple_opponents')
        self.assertIsNone(self.bot.resource_key)
        self.assertNotEqual(self.bot.goal, [5, 0, 0])
        self.assertGreater(math.hypot(*action['move']), .5)
        self.assertLess(action['move'][0], 0)

    def test_hidden_recent_attacker_deduplicates_and_expires(self):
        event = {'type': 'damaged', 'by': 6, 'weapon': 'gun', 'amount': 20}
        self.assertEqual(self.step(events=[event])['reason'], 'multiple_opponents')
        self.assertEqual(self.step(23.1)['phase'], 'probe')
        self.assertEqual(self.step(23.2, events=[{**event, 'by': 5}])['opponents'], [5])

    def test_npc_zone_and_null_do_not_fabricate_second_mech(self):
        for by, weapon in ((109, 'npc'), (None, 'zone'), (None, 'gun')):
            with self.subTest(by=by, weapon=weapon):
                self.bot.duel = DuelController(self.hello['config'])
                self.assertFalse(self.step(events=[{'type': 'damaged', 'by': by,
                    'weapon': weapon, 'amount': 5}])['retreat'])

    def test_long_range_own_weapon_does_not_extend_bystander_reach(self):
        self.obs['self']['weapons'][1] = self.weapon('laser')
        self.obs['mechs'] = [self.enemy(80), self.enemy(250, id=6)]
        report = self.step(target=self.obs['mechs'][0])
        self.assertEqual(report['opponents'], [5])
        self.assertFalse(report['retreat'])

    def test_occluded_bystander_and_visible_dead_actor_do_not_count(self):
        target = self.enemy(80)
        self.obs['mechs'] = [target, self.enemy(90, id=6, hp=0)]
        self.assertEqual(self.step(target=target)['opponents'], [5])
        self.obs['mechs'][1]['hp'] = 1400
        q = [{'actor': target, 'd': 80, 'los': True, 'risk': 1},
             {'actor': self.obs['mechs'][1], 'd': 90, 'los': False, 'risk': .18}]
        report = self.bot.duel.decide(self.obs, q, target, self.bot.stats(self.obs['self']))
        self.assertEqual(report['opponents'], [5])

    def test_low_hp_hysteresis_is_independent_of_opponent_count(self):
        self.obs['self']['hp'] = 700
        self.assertTrue(self.step()['retreat'])
        self.obs['self']['hp'] = 1200
        self.assertTrue(self.step(21)['retreat'])
        self.obs['self']['hp'] = 1320
        self.assertFalse(self.step(22)['retreat'])

    def test_ledger_survives_los_flicker_and_cannot_renew_finish(self):
        self.step()
        fight = self.bot.duel.encounter
        fight.update(spent=100, finish_used=True)
        self.step(20.1, los=False)
        self.assertIs(self.bot.duel.encounter, fight)
        report = self.step(20.2)
        self.assertAlmostEqual(report['elapsed'], .2)
        self.assertEqual(report['spent'], 100)
        self.assertTrue(fight['finish_used'])
        self.assertEqual(fight['grace'], 22.)

    def test_ledger_expires_only_after_bounded_contact_absence(self):
        self.step()
        self.step(20.1, los=False)
        self.step(26.1, los=False)
        self.assertIsNone(self.bot.duel.encounter)
        self.assertEqual(self.step(26.2)['phase'], 'probe')

    def test_damage_memory_does_not_refresh_actual_contact_timestamp(self):
        self.step()
        self.step(20.1, los=False, events=[{'type': 'damaged', 'weapon': 'gun', 'by': 5, 'amount': 20}])
        self.step(22., los=False)
        self.assertEqual(self.bot.duel.encounter['last_contact'], 20.1)
        self.step(26.11, los=False)
        self.assertIsNone(self.bot.duel.encounter)

    def test_cost_uses_incoming_events_and_entry_max_hp(self):
        self.step(events=[{'type': 'damaged', 'weapon': 'gun', 'by': 5, 'amount': 50}])
        self.assertEqual(self.bot.duel.encounter['spent'], 0)
        self.obs['self'].update(hp=1600, max_hp=1600, cubes=3)
        report = self.step(20.1, events=[{'type': 'damaged', 'weapon': 'gun', 'by': 5, 'amount': 350}])
        self.assertEqual(report['reason'], 'health_cost')
        self.assertEqual(report['spent'], 350)
        self.assertEqual(self.bot.duel.encounter['entry_max_hp'], 1400)

    def test_other_target_npc_crate_hits_and_hp_fall_are_not_progress(self):
        self.step()
        report = self.step(22.1, target=self.enemy(hp=1000), events=[
            {'type': 'hit', 'target': ident, 'amount': 300} for ident in (6, 109, 1001)])
        self.assertFalse(report['retreat'])
        report = self.step(report['pending_hit_until']+.1, target=self.enemy(hp=900))
        self.assertEqual(report['reason'], 'no_effective_progress')

    def test_slow_remaining_estimate_is_diagnostic_only(self):
        self.step()
        report = self.step(22, events=[{'type': 'hit', 'target': 5, 'amount': 45}])
        self.assertGreater(report['observed_remaining_s'], 8)
        self.assertFalse(report['retreat'])

    def test_reload_flight_grace_is_fixed_and_not_renewed_each_tick(self):
        self.step()
        self.obs['self']['weapons'][0].update(ammo=0, reload=2.2)
        self.step(21)
        until = self.bot.duel.encounter['reload_until']
        self.obs['self']['weapons'][0]['reload'] = 1.2
        self.assertFalse(self.step(22)['retreat'])
        self.assertEqual(self.bot.duel.encounter['reload_until'], until)
        self.obs['self']['weapons'][0].update(ammo=20, reload=0)
        pending = self.step(until+.1)['pending_hit_until']
        self.assertEqual(self.step(pending+.1)['reason'], 'no_effective_progress')

    def test_health_cost_allows_once_only_ready_near_finish(self):
        self.step()
        self.obs['self']['hp'] = 1050
        events = [{'type': 'damaged', 'by': 5, 'weapon': 'gun', 'amount': 350},
                  {'type': 'hit', 'target': 5, 'amount': 45}]
        report = self.step(20.1, target=self.enemy(hp=180), events=events)
        self.assertEqual(report['phase'], 'finish')
        self.assertGreater(report['ideal_finish_s'], .75)
        self.assertLess(report['ideal_finish_s'], 1.5)
        deadline = report['finish_until']
        report = self.step(20.2, target=self.enemy(hp=135), events=[events[1]])
        self.assertEqual(report['finish_until'], deadline)
        self.assertEqual(self.step(deadline+.01, target=self.enemy(hp=1))['reason'], 'finish_extension_expired')
        self.assertTrue(self.bot.duel.health_recover)
        self.assertTrue(self.step(deadline+.1, target=self.enemy(hp=1))['retreat'])

    def test_finisher_never_overrides_no_progress_low_hp_multiple_or_zone(self):
        for case in ('no_hit', 'low_hp', 'multiple', 'zone'):
            with self.subTest(case=case):
                self.setUp()
                self.step()
                self.obs['self']['hp'] = 700 if case == 'low_hp' else 1050
                target = self.enemy(hp=45)
                if case == 'multiple':
                    self.obs['mechs'] = [target, self.enemy(80, id=6)]
                events = [{'type': 'damaged', 'weapon': 'gun', 'by': 5, 'amount': 350}]
                if case != 'no_hit':
                    events.append({'type': 'hit', 'target': 5, 'amount': 45})
                self.assertTrue(self.step(20.1, target, events=events, urgent=case=='zone')['retreat'])

    def test_hard_time_limit_even_with_continued_damage(self):
        self.step()
        self.assertEqual(self.step(40, events=[{'type': 'hit', 'target': 5, 'amount': 45}])['reason'], 'duel_time_limit')

    def test_rearm_requires_fixed_retreat_time_healed_and_single_contact(self):
        self.step()
        pending = self.step(22.1)['pending_hit_until']
        self.assertTrue(self.step(pending+.1)['retreat'])
        deadline = self.bot.duel.encounter['retreat_until']
        self.assertTrue(self.step(deadline-.1)['retreat'])
        self.obs['self']['hp'] = 1250
        self.assertTrue(self.step(deadline)['retreat'])
        self.obs['self']['hp'] = 1400
        self.obs['mechs'] = [self.enemy(), self.enemy(80, id=6)]
        self.assertEqual(self.step(deadline+.1)['reason'], 'multiple_opponents')
        self.obs['mechs'] = [self.enemy()]
        # The missing second exposed actor remains active for one second.
        self.assertTrue(self.step(deadline+.2)['retreat'])
        self.assertEqual(self.step(deadline+1.2)['phase'], 'probe')

    def test_pending_hit_deadline_never_renews_without_actual_target_damage(self):
        self.step()
        report = self.step(22.)
        deadline = report['pending_hit_until']
        self.assertLessEqual(deadline-22., 1.)
        for t in (22.1, 22.2, 22.3):
            report = self.step(t, events=[{'type': 'hit', 'target': 5, 'amount': 0}])
            self.assertEqual(self.bot.duel.encounter['pending_hit_until'], deadline)
        self.assertEqual(self.step(deadline+.01)['reason'], 'no_effective_progress')

    def test_actual_target_hit_rearms_pending_allowance_and_limits_preempt(self):
        self.step()
        self.step(22.)
        self.step(22.1, events=[{'type': 'hit', 'target': 5, 'amount': 45}])
        self.assertIsNone(self.bot.duel.encounter['pending_hit_until'])
        report = self.step(24.2)
        self.assertGreater(report['pending_hit_until'], 24.2)
        self.obs['self']['hp'] = 1050
        self.assertEqual(self.step(24.3, events=[{'type': 'damaged', 'weapon': 'gun', 'by': 5, 'amount': 350}])['reason'], 'health_cost')

    def test_probe_preempts_resource_targeting(self):
        self.obs['mechs'] = [self.enemy(100)]
        self.obs['crates'] = [{'id': 1001, 'hp': 300, 'pos': [40, 0, 0]}]
        with patch.object(self.bot, 'resource_goal', side_effect=AssertionError('probe preempts loot')):
            action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, 'engage')
        self.assertEqual(self.bot.telemetry['target'], 5)
        self.assertTrue(action['fire'][0])

    def test_upper_body_and_lightning_ignore_invalid_center_pitch(self):
        self.obs['self'].update(cubes=10, aim=[0, -.7])
        self.obs['self']['stats']['muzzle_height'] = 10.5
        target = self.enemy(6.5)
        schedule = self.bot.duel.ideal_schedule(self.obs, target, self.bot.stats(self.obs['self']))
        self.assertIsNotNone(schedule['first_hit_s'])
        self.obs['self']['weapons'] = [self.weapon('lightning'), None]
        self.assertIsNotNone(self.bot.duel.ideal_schedule(self.obs, target, self.bot.stats(self.obs['self']))['first_hit_s'])

    def test_released_laser_keeps_observed_movement_slowdown(self):
        for charge in (.05, .1, .4):
            with self.subTest(charge=charge):
                self.setUp()
                self.obs['self']['hp'] = 500
                self.obs['self']['weapons'][1] = self.weapon('laser', charge=charge)
                self.obs['mechs'] = [self.enemy(80)]
                with patch.object(self.bot, 'movement', return_value=((1, 0), False)) as movement:
                    action = self.bot.act(self.obs)
                self.assertFalse(action['fire'][1])
                motion = movement.call_args.args[0]
                self.assertEqual(motion['self']['weapons'][1]['charge'], charge)
                self.assertEqual(self.obs['self']['weapons'][1]['charge'], charge)

    def test_quiet_cover_is_unknown_if_budget_or_incoming_samples_fail(self):
        self.obs['self']['hp'] = 700
        stats = self.bot.stats(self.obs['self'])
        q = [{'actor': self.enemy(), 'd': 100, 'los': False, 'risk': .18}]
        quiet = self.bot.duel.quiet_healing
        self.assertFalse(quiet(self.obs, q, stats, lambda a,b: False, time.perf_counter()-1))
        self.assertFalse(quiet(self.obs, q, stats, lambda a,b: b[2] > stats['height']*.8, time.perf_counter()+1))
        self.assertTrue(quiet(self.obs, q, stats, lambda a,b: False, time.perf_counter()+1))
        self.bot.duel.attackers[6] = self.obs['t']
        self.assertFalse(quiet(self.obs, q, stats, lambda a,b: False, time.perf_counter()+1))

    def test_fresh_hidden_bearing_survives_reload_but_zone_does_not_refresh(self):
        self.obs['self']['hp'] = 500
        self.obs['self']['weapons'][0].update(ammo=0, reload=1.2)
        self.obs['events'] = [{'type': 'damaged', 'weapon': 'gun', 'by': 6, 'amount': 45, 'bearing': 1.2}]
        self.assertAlmostEqual(self.bot.act(self.obs)['aim'][0], 1.2)
        self.obs.update(t=24, tick=480, events=[{'type': 'damaged', 'weapon': 'zone', 'by': None, 'amount': 1, 'bearing': None}])
        self.assertEqual(self.bot.act(self.obs)['aim'][0], self.obs['self']['aim'][0])


if __name__ == '__main__':
    unittest.main()
