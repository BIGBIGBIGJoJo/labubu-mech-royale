"""Priority, one-plan and arrival contracts for the local cover override."""
import copy
from collections import deque
from unittest.mock import patch
import unittest

import test_reload_cover as fixtures


class CoverIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ReloadCoverTests.setUpClass()
        cls.arena = fixtures.ReloadCoverTests.arena

    def setUp(self):
        fixtures.ReloadCoverTests.setUp(self)
        self.observed_navigation = None
        self.boost_preference = None

    def movement(self, obs, navigation, threats, stats, urgent, deadline, goal):
        self.observed_navigation = navigation
        self.boost_preference = self.bot.spacing_boost
        return navigation, False

    def act(self, resource=None, urgent=False):
        with patch('time.perf_counter', return_value=0.), \
             patch.object(self.bot, 'resource_goal', return_value=resource), \
             patch.object(self.bot.zone_resources, 'rotation_required', return_value=urgent), \
             patch.object(self.bot, 'movement', side_effect=self.movement), \
             patch.object(self.bot, 'safe_goal', return_value=[0., 0., 0.]), \
             patch.object(self.bot.combat, 'plan', wraps=self.bot.combat.plan) as planner:
            result = self.bot.act(self.obs)
        self.assertEqual(planner.call_count, 1)
        return result

    def test_captured_pair_admission_changes_local_goal_without_held_goal_or_fire(self):
        expected = self.bot.combat.plan(self.obs, self.target)
        self.bot.goal, self.bot.goal_kind, self.bot.goal_until = [9., 8., 7.], 'position', 150.
        action = self.act()
        self.assertTrue(self.helper.last_report['admitted'])
        self.assertEqual(self.bot.goal, [9., 8., 7.])
        self.assertEqual(self.bot.goal_kind, 'position')
        self.assertEqual(self.bot.goal_until, 150.)
        for key in ('aim', 'fire', 'reload'):
            self.assertEqual(action[key], expected[key])
        self.assertFalse(self.boost_preference)
        self.assertGreater(sum(abs(x) for x in action['move']), 0)

    def test_same_observed_target_survives_outgoing_occlusion(self):
        self.act()
        pair = self.helper.pair
        self.obs['self'].update(pos=list(pair['S']), vel=[0, 0, 0])
        self.obs.update(t=96.9, tick=1938)
        self.obs['self']['weapons'][0]['reload'] = 1.85
        with patch.object(self.bot, 'choose_target', return_value=None):
            action = self.act()
        self.assertEqual(self.bot.telemetry['mode'], 'engage')
        self.assertEqual(self.bot.telemetry['target'], 12)
        self.assertTrue(self.helper.last_report['active'])
        self.assertEqual(self.helper.last_report['phase'], 'hold')
        self.assertTrue(self.helper.last_report['actual_protected'])
        self.assertEqual(action['move'], [0, 0])

    def test_early_return_to_exposed_firing_point_resumes_combat_stride(self):
        self.act()
        pair = self.helper.pair
        self.assertIsNotNone(pair)
        pair['phase'] = 'return'
        self.obs.update(t=98.3, tick=1966)
        self.obs['self'].update(pos=list(pair['P']), vel=[0, 0, 0])
        self.obs['self']['weapons'][0]['reload'] = .45
        action = self.act()
        self.assertEqual(self.bot.telemetry['mode'], 'engage')
        self.assertIsNone(self.helper.pair)
        self.assertEqual(self.helper.last_report['reason'], 'returned_to_firing_point')
        self.assertGreater(sum(abs(v) for v in action['move']), .9)
        self.assertNotEqual(self.bot.telemetry['goal'], list(pair['P']))
        self.assertFalse(action['fire'][0])

    def test_only_observed_protection_can_apply_cover_arrival_stop(self):
        p = self.obs['self']['pos']
        near = [p[0]+.2, p[1], p[2]]
        def override(*args, **kwargs):
            self.helper.last_report = {'active': True, 'phase': 'return', 'actual_protected': False}
            return near
        with patch.object(self.helper, 'step', side_effect=override):
            action = self.act()
        self.assertEqual(action['move'], [1., 0.])

    def test_low_health_rotation_and_resources_all_preempt(self):
        for priority in ('recover', 'rotate', 'resource'):
            with self.subTest(priority=priority):
                self.setUp()
                self.act()
                resource = None
                if priority == 'recover':
                    self.obs['self']['hp'] = 600
                if priority == 'resource':
                    item = {'id': 999, 'kind': 'laser', 'pos': [-50., 80., 0.]}
                    resource = (1., item['pos'], 'pickups', ('pickups', 999), item)
                self.act(resource=resource, urgent=priority == 'rotate')
                self.assertIsNone(self.helper.pair)
                self.assertNotEqual(self.bot.telemetry['mode'], 'engage')

    def test_near_shelter_exposed_goal_does_not_hit_generic_arrival_brake(self):
        p = self.obs['self']['pos']
        shelter = [p[0]+.2, p[1], p[2]]
        def override(*args, **kwargs):
            self.helper.last_report = {'active': True, 'phase': 'out', 'actual_protected': False}
            return shelter
        with patch.object(self.helper, 'step', side_effect=override), \
             patch.object(self.bot.map, 'navigate', side_effect=AssertionError('generic arrival path')):
            self.act()
        self.assertAlmostEqual(self.observed_navigation[0], 1.)
        self.assertAlmostEqual(self.observed_navigation[1], 0.)

    def test_dead_target_or_unknown_loadout_cannot_start_cycle(self):
        self.target['hp'] = 0
        self.act()
        self.assertIsNone(self.helper.pair)
        self.target['hp'] = 1400
        self.target['weapons'] = ['unknown']
        self.act()
        self.assertIsNone(self.helper.pair)

    def test_recent_unseen_attacker_prevents_protection_claim(self):
        self.bot.recent_attackers[99] = self.obs['t']-.1
        self.act()
        self.assertIsNone(self.helper.pair)

    def test_preexisting_stuck_keeps_ordinary_jump_without_active_ground_pair(self):
        t, p = self.obs['t'], tuple(self.obs['self']['pos'])
        self.bot.history = deque((t-1.9+i*.2, p, 1.) for i in range(10))
        action = self.act()
        self.assertTrue(self.bot.telemetry['stuck'])
        self.assertTrue(action['jump'])
        self.assertIsNone(self.helper.pair)
        self.assertFalse(self.helper.last_report['active'])

    def test_structural_abort_precedes_target_retention_and_combat(self):
        self.act()
        self.obs['self']['weapons'][1] = {'kind': 'laser', 'cooldown': 1., 'charge': 0}
        with patch.object(self.bot, 'choose_target', return_value=None):
            self.act()
        self.assertIsNone(self.helper.pair)
        self.assertEqual(self.bot.telemetry['mode'], 'position')
        self.assertIsNone(self.bot.telemetry['target'])


if __name__ == '__main__':
    unittest.main()
