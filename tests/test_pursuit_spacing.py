"""Scoped gun separation and unchanged nearest-target/fire permissions."""
import copy
import math
import unittest
from unittest.mock import patch

import test_strategy as bot_fixtures
import test_tactical as move_fixtures
from tactical import pursuit_distance


class GunSpacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        move_fixtures.TacticalTests.setUpClass()
        cls.config = move_fixtures.TacticalTests.config

    setUp = move_fixtures.TacticalTests.setUp

    def target(self, distance=41, kind='mech', **kw):
        return {'id': 10, 'kind': kind, 'pos': [distance, 0, 0],
                'cubes': 1, 'weapons': ['gun', 'laser'], **kw}

    def preferred(self, target=None, **kw):
        return pursuit_distance(self.config, self.me, target or self.target(), self.stats, **kw)

    def weapon(self, kind):
        return {'kind': kind, 'stats': dict(self.config['weapons'][kind])}

    def test_clear_gun_duel_restores_anchor_after_closer_acquisition(self):
        for gap in (36.83, 41, 47.01, 70, 120):
            with self.subTest(gap=gap):
                self.assertEqual(self.preferred(self.target(gap)), 70)

    def test_short_live_range_still_caps_restored_anchor(self):
        self.me['weapons'][0]['stats']['range'] = 50
        self.assertEqual(self.preferred(self.target(30)), 44)

    def test_large_body_floor_can_exceed_anchor(self):
        self.stats['radius'] = 80
        self.assertAlmostEqual(self.preferred(), 80 + 2.5 * 1.05 + 2)

    def test_elevation_pitch_floor_can_exceed_anchor(self):
        self.stats['muzzle_height'] = 80
        expected = (80 - 9 * 1.05 * .9) / math.tan(-self.stats['min_pitch']) + 2
        self.assertGreater(expected, 70)
        self.assertAlmostEqual(self.preferred(), expected)

    def test_occluded_close_mech_still_approaches_physical_floor(self):
        self.assertAlmostEqual(self.preferred(line_clear=False), 2.5 + 2.5 * 1.05 + 2)

    def test_close_npc_and_multiweapon_loadouts_keep_existing_preferences(self):
        self.assertEqual(self.preferred(self.target(20, kind='npc')), 20)
        for second in ('gun', 'laser', 'mortar', 'lightning'):
            with self.subTest(second=second):
                self.me['weapons'][1] = self.weapon(second)
                self.assertEqual(self.preferred(self.target(30)), 30)

    def test_slot_order_and_low_energy_do_not_disable_gun_separation(self):
        self.me['weapons'] = [None, self.me['weapons'][0]]
        self.me['energy'] = 3
        self.assertEqual(self.preferred(), 70)


class GunSpacingBotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = bot_fixtures.official_fixture()

    setUp = bot_fixtures.StrategyTests.setUp
    enemy = bot_fixtures.StrategyTests.enemy
    weapon = bot_fixtures.StrategyTests.weapon

    def test_close_nearest_mech_is_fired_on_while_separating_at_low_hp(self):
        self.obs['self']['hp'] = 200
        self.obs['mechs'] = [self.enemy(41, weapons=['gun', 'laser']),
                             self.enemy(80, id=6, hp=1)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry['pursuit_target'], 5)
        self.assertEqual(self.bot.telemetry['fire_target'], 5)
        self.assertTrue(self.bot.telemetry['nearby_enemy'])
        self.assertFalse(self.bot.recover)
        self.assertTrue(action['fire'][0])
        self.assertFalse(action['reload'])
        self.assertLess(self.bot.telemetry['goal'][0], self.obs['self']['pos'][0])
        self.assertLess(action['move'][0], 0)

    def test_far_nearest_mech_still_receives_fast_approach(self):
        self.obs['mechs'] = [self.enemy(120)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry['pursuit_target'], 5)
        self.assertTrue(self.bot.telemetry['pursuit_boost'])
        self.assertGreater(action['move'][0], 0)
        self.assertTrue(action['boost'])
        self.assertTrue(action['fire'][0])

    def test_same_observation_keeps_fire_and_permissions_from_old_clamp(self):
        self.obs['mechs'] = [self.enemy(41, weapons=['gun', 'laser'])]
        with patch.object(bot_fixtures.policy, 'ArenaMap', bot_fixtures.FlatArena):
            old_bot = bot_fixtures.policy.Bot(copy.deepcopy(self.hello))
        def old_clamp(config, me, target, stats, **kw):
            desired = pursuit_distance(config, me, target, stats, **kw)
            return min(desired, math.dist(me['pos'][:2], target['pos'][:2]))
        with patch.object(bot_fixtures.policy, 'pursuit_distance', old_clamp):
            old_action = old_bot.act(copy.deepcopy(self.obs))
        action = self.bot.act(self.obs)
        for field in ('fire', 'aim', 'reload'):
            self.assertEqual(action[field], old_action[field])
        for field in ('pursuit_target', 'fire_target', 'nearby_enemy', 'allow_fire',
                      'allow_partial_reload', 'recover', 'recovery_needed'):
            self.assertEqual(self.bot.telemetry[field], old_bot.telemetry[field])
        self.assertNotEqual(self.bot.telemetry['goal'], old_bot.telemetry['goal'])


if __name__ == '__main__':
    unittest.main()
