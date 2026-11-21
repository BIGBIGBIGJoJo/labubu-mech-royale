"""Movement budget regressions; estimates are not a combat simulator."""
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spacing import LightningApproach
import bot as policy
from test_strategy import FlatArena, official_fixture

with gzip.open(ROOT / 'check/stream.jsonl.gz', 'rt') as stream:
    CONFIG = json.loads(next(stream))['config']
CASES = json.loads((ROOT / 'tests/fixtures/lightning_approach_baseline.json').read_text(encoding='utf-8'))


def recorded_case(index=0):
    case = copy.deepcopy(CASES[index])
    target = case.pop('target')
    last_laser = case.pop('last_laser')
    case['beams'] = ([] if last_laser is None else
                     [{'by': target['id'], 'kind': 'laser', 'age': case['t'] - last_laser}])
    return case, target


def close_case(hp=1568, target_hp=1624, distance=35, energy=100):
    obs, target = recorded_case()
    obs['self'].update(hp=hp, energy=energy, pos=[0, 0, 0], aim=[0, 0])
    obs['beams'] = []
    target.update(pos=[distance, 0, 0], vel=[0, 0, 0], hp=target_hp, charging=False)
    return obs, target


class ApproachModelTests(unittest.TestCase):
    def test_missing_and_invalid_enemy_hp_declines_without_estimating(self):
        for value in (None, 0, -1, float('nan'), float('inf'), -float('inf'), '600', True):
            obs, target = close_case(target_hp=600)
            if value is None:
                del target['hp']
            else:
                target['hp'] = value
            with self.subTest(hp=value):
                model = LightningApproach(CONFIG)
                model.committed = target['id']
                result = model.assess(obs, target)
                self.assertFalse(result['allowed'])
                self.assertEqual(result['reason'], 'unknown_hp')
                self.assertIsNone(model.committed)
                json.dumps(result, allow_nan=False)

    def test_recorded_expensive_charge_declined_at_four_checkpoints(self):
        model = LightningApproach(CONFIG)
        for index in range(4):
            obs, target = recorded_case(index)
            with self.subTest(t=obs['t']):
                model.observe(obs)
                result = model.assess(obs, target)
                self.assertFalse(result['allowed'])
                self.assertEqual(result['reason'], 'survival_margin')
                self.assertGreater(result['contact_s'], result['relative_contact_s'])
                self.assertLess(result['margin'], 0)
                self.assertTrue(result['phase_known'])

    def test_close_healthy_and_low_hp_prey_are_not_blanket_denied(self):
        for hp, prey in [(1568, 1624), (1000, 600)]:
            with self.subTest(hp=hp, prey=prey):
                obs, target = close_case(hp, prey)
                result = LightningApproach(CONFIG).assess(obs, target)
                self.assertTrue(result['allowed'])
                self.assertGreater(result['lightning_shots'], 0)
                self.assertGreater(result['margin'], 0)

    def test_already_committed_keeps_favorable_fight_below_seventy_percent(self):
        obs, target = close_case(target_hp=1321)
        model = LightningApproach(CONFIG)
        self.assertTrue(model.assess(obs, target)['allowed'])
        obs['self']['hp'] = 940  # Above baseline recovery, below its old 70% cliff.
        fresh = LightningApproach(CONFIG).assess(obs, target)
        continuing = model.assess(obs, target)
        self.assertFalse(fresh['allowed'], 'An entry needs one extra enemy burst in reserve')
        self.assertTrue(continuing['allowed'])
        self.assertEqual(continuing['reason'], 'continue')
        self.assertGreater(continuing['margin'], 0)

    def test_commitment_is_for_same_target_only(self):
        obs, target = close_case(target_hp=1321)
        model = LightningApproach(CONFIG)
        model.assess(obs, target)
        obs['self']['hp'] = 940
        target['id'] += 1
        self.assertFalse(model.assess(obs, target)['allowed'])

    def test_distant_wounded_target_can_be_finished_by_gun(self):
        obs, target = close_case(target_hp=250, distance=95)
        result = LightningApproach(CONFIG).assess(obs, target)
        self.assertTrue(result['allowed'])
        self.assertLess(result['finish_s'], result['contact_s'])
        self.assertEqual(result['lightning_shots'], 0)

    def test_energy_reserve_is_not_spent_twice_on_lightning(self):
        obs, target = close_case(target_hp=600, energy=10)
        result = LightningApproach(CONFIG).assess(obs, target)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['reason'], 'energy_reserve')
        self.assertEqual(result['lightning_shots'], 0)

    def test_reload_delays_ideal_finish(self):
        obs, target = close_case(target_hp=600)
        ready = LightningApproach(CONFIG).assess(obs, target)
        obs['self']['weapons'][0].update(ammo=0, reload=2.05)
        reloading = LightningApproach(CONFIG).assess(obs, target)
        self.assertGreater(reloading['finish_s'], ready['finish_s'])

    def test_charging_enemy_can_release_before_simultaneous_lightning(self):
        obs, target = close_case(target_hp=600)
        target['charging'] = True
        result = LightningApproach(CONFIG).assess(obs, target)
        self.assertGreaterEqual(result['laser_releases'], 1)

    def test_continuous_ideal_hits_suppress_laser_but_missing_hits_does_not(self):
        obs, target = close_case()
        result = LightningApproach(CONFIG).assess(obs, target)
        self.assertEqual(result['laser_releases'], 0)
        self.assertGreater(result['laser_releases_without_future_short'], 0)
        self.assertGreater(result['margin'], 0)
        self.assertLess(result['margin_without_future_short'], 0)

    def test_energy_exhaustion_ends_conditional_short(self):
        obs, target = close_case(target_hp=1000, energy=43.8)
        result = LightningApproach(CONFIG).assess(obs, target)
        self.assertEqual(result['lightning_shots'], 1)
        self.assertGreater(result['laser_releases'], 0)
        self.assertGreater(result['finish_s'], CONFIG['weapons']['lightning']['short_s'])

    def test_confirmed_short_survives_own_lightning_cooldown(self):
        obs, target = close_case(target_hp=600)
        obs['self']['weapons'][1]['cooldown'] = .2
        unknown = LightningApproach(CONFIG).assess(obs, target)
        obs['events'] = [{'type': 'hit', 'weapon': 'lightning', 'target': target['id'], 'effect': 'short'}]
        model = LightningApproach(CONFIG)
        model.observe(obs)
        known = model.assess(obs, target)
        self.assertGreater(unknown['laser_releases'], known['laser_releases'])
        self.assertEqual(known['laser_releases'], 0)
        self.assertAlmostEqual(known['known_short_remaining_s'], 1.9)
        obs['t'] += 2.1
        obs['events'] = []
        model.observe(obs)
        self.assertEqual(model.assess(obs, target)['known_short_remaining_s'], 0)

    def test_observed_release_phase_avoids_inventing_ready_laser(self):
        obs, target = close_case(target_hp=600)
        obs['self']['weapons'][1]['cooldown'] = .8
        unknown = LightningApproach(CONFIG).assess(obs, target)
        model = LightningApproach(CONFIG)
        obs['beams'] = [{'by': target['id'], 'kind': 'laser', 'age': .1}]
        model.observe(obs)
        known = model.assess(obs, target)
        self.assertGreater(unknown['laser_releases'], known['laser_releases'])
        self.assertTrue(known['phase_known'])

    def test_multiple_threats_and_blocked_los_do_not_commit(self):
        obs, target = close_case(target_hp=600)
        for options in [dict(visible_count=2), dict(los=False)]:
            with self.subTest(options=options):
                self.assertFalse(LightningApproach(CONFIG).assess(obs, target, **options)['allowed'])

    def test_unreachable_speed_and_height_have_json_safe_diagnostics(self):
        for mode in ('speed', 'height'):
            obs, target = close_case(distance=100)
            if mode == 'speed':
                target['vel'] = [CONFIG['mech']['walk_speed'] + 1, 0, 0]
            else:
                target['pos'][2] = 70
            result = LightningApproach(CONFIG).assess(obs, target)
            self.assertFalse(result['allowed'])
            self.assertEqual(result['reason'], 'unreachable')
            self.assertIsNone(result['contact_s'])
            json.dumps(result, allow_nan=False)

    def test_back_facing_includes_turn_delay_and_rear_damage(self):
        obs, target = close_case(target_hp=600)
        front = LightningApproach(CONFIG).assess(obs, target)
        obs['self']['aim'][0] = math.pi
        back = LightningApproach(CONFIG).assess(obs, target)
        self.assertGreater(back['contact_s'], front['contact_s'])
        self.assertGreater(back['incoming'], front['incoming'])


class ApproachIntegrationTests(unittest.TestCase):
    def setup_bot(self, *, hp=1568, enemy_hp=1624, distance=95):
        hello, obs = official_fixture()
        recorded, target = close_case(hp, enemy_hp, distance)
        obs.update(recorded, alive=16, offer=None)
        for key in ('projectiles', 'crates', 'cubes', 'pickups', 'sounds', 'beams', 'events', 'drops'):
            obs[key] = []
        obs['self']['weapons'][0].update(cooldown=0, ammo=12, reload=0)
        obs['mechs'] = [target]
        obs['zone'] = dict(center=[0, 0], radius=560, next_center=[0, 0], next_radius=380,
                           shrink_start=60, shrink_end=110, dps=20)
        with patch.object(policy, 'ArenaMap', FlatArena):
            bot = policy.Bot(hello)
        return bot, obs, target

    def test_denied_charge_preserves_gun_fire_and_fallback_spacing(self):
        bot, obs, _ = self.setup_bot()
        action = bot.act(obs)
        self.assertFalse(bot.telemetry['lightning_approach']['allowed'])
        self.assertLess(bot.telemetry['goal'][0], 0)
        self.assertTrue(action['fire'][0])
        self.assertFalse(bot.recover)

    def test_hidden_enemy_hp_retains_ranged_movement_and_gun_fire(self):
        bot, obs, target = self.setup_bot()
        del target['hp']
        action = bot.act(obs)
        self.assertEqual(bot.telemetry['lightning_approach']['reason'], 'unknown_hp')
        self.assertLess(bot.telemetry['goal'][0], 0)
        self.assertTrue(action['fire'][0])

    def test_favorable_committed_target_does_not_trigger_old_hp_cliff(self):
        bot, obs, target = self.setup_bot(enemy_hp=1321, distance=40)
        bot.act(obs)
        self.assertTrue(bot.telemetry['lightning_approach']['allowed'])
        obs['self']['hp'] = 940
        obs.update(t=obs['t'] + .1, tick=obs['tick'] + 2)
        bot.act(obs)
        self.assertFalse(bot.recover)
        self.assertTrue(bot.telemetry['lightning_approach']['allowed'])
        self.assertGreater(bot.telemetry['goal'][0], 0)

    def test_recovery_resets_approach_without_changing_recovery(self):
        bot, obs, _ = self.setup_bot(hp=600)
        bot.lightning_approach.committed = obs['mechs'][0]['id']
        action = bot.act(obs)
        self.assertTrue(bot.recover)
        self.assertIsNone(bot.lightning_approach.committed)
        self.assertNotIn('lightning_approach', bot.telemetry)
        self.assertEqual(action['fire'], [False, False])

    def test_other_lightning_matchups_retain_baseline_close_spacing(self):
        bot, obs, target = self.setup_bot(distance=95)
        target['weapons'] = ['gun']
        bot.act(obs)
        self.assertGreater(bot.telemetry['goal'][0], 0)
        self.assertNotIn('lightning_approach', bot.telemetry)

    def test_without_lightning_retains_baseline_range_and_fire(self):
        bot, obs, _ = self.setup_bot(distance=95)
        obs['self']['weapons'][1] = None
        action = bot.act(obs)
        self.assertLess(bot.telemetry['goal'][0], 0)
        self.assertTrue(action['fire'][0])
        self.assertNotIn('lightning_approach', bot.telemetry)


if __name__ == '__main__':
    unittest.main()
