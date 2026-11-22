"""The frozen cover consumer uses the selected horizontal gun geometry.

Captured observations plus fixed-clock geometry checks; no simulated match or
real-time budget claim. The unchanged component tests own their other limits.
"""
import copy
import json
import math
import unittest
from unittest.mock import patch

from combat import Combat, angle_delta, point_aim
import test_reload_cover as cover_fixture
import test_horizontal_barrel as aim_fixture


class AimCoverCombinedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cover_fixture.ReloadCoverTests.setUpClass()
        cls.arena = cover_fixture.ReloadCoverTests.arena

    def setUp(self):
        cover_fixture.ReloadCoverTests.setUp(self)

    def test_captured_reload_admission_consumes_one_corrected_gun_solve(self):
        with patch.object(self.bot.combat, '_horizontal_solution',
                          wraps=self.bot.combat._horizontal_solution) as solver:
            action = self.bot.combat.plan(self.obs, self.target)
            report = copy.deepcopy(self.bot.combat.last_report)
            with patch('time.perf_counter', return_value=0.):
                goal = self.helper.step(self.obs, self.target, self.stats, True, .019)
        self.assertEqual(solver.call_count, 1)
        self.assertIsNotNone(goal, self.helper.last_report)
        self.assertTrue(self.helper.last_report['admitted'])
        self.assertFalse(action['fire'][0])
        solution = report['solution']
        muzzle = [*self.obs['self']['pos'][:2], self.obs['self']['pos'][2]+self.stats['muzzle_height']]
        launch = Combat._barrel_origin(muzzle, solution['aim'], self.stats['radius']+.5)
        self.assertEqual(launch[2], muzzle[2])
        measured = point_aim(launch, solution['point'])
        self.assertLess(abs(angle_delta(measured[0], solution['aim'][0])), 1e-6)
        self.assertLess(abs(measured[1]-solution['aim'][1]), 1e-6)
        self.assertEqual(self.bot.combat.last_report, report)

    def test_return_probe_uses_corrected_solver_without_mutating_combat_state(self):
        report = copy.deepcopy(self.bot.combat.last_report)
        state = {name: copy.deepcopy(getattr(self.bot.combat, name))
                 for name in ('_full_since', '_mortar_target', '_mortar_until', '_mortar_retry_at')}
        with patch.object(self.bot.combat, '_horizontal_solution',
                          wraps=self.bot.combat._horizontal_solution) as solver, \
             patch('time.perf_counter', return_value=0.):
            solution = self.helper._outgoing(self.obs['self']['pos'], self.obs, self.target,
                                            self.stats, self.obs['self']['weapons'][0], .019)
        self.assertEqual(solver.call_count, 1)
        self.assertIsNotNone(solution)
        self.assertTrue(solution['clear'])
        self.assertEqual(self.bot.combat.last_report, report)
        for name, value in state.items():
            self.assertEqual(getattr(self.bot.combat, name), value)
        muzzle = [*self.obs['self']['pos'][:2], self.obs['self']['pos'][2]+self.stats['muzzle_height']]
        origin = Combat._barrel_origin(muzzle, solution['aim'], self.stats['radius']+.5)
        measured = point_aim(origin, solution['point'])
        self.assertLess(abs(measured[1]-solution['aim'][1]), 1e-6)

    def test_actual_965_observation_still_has_complete_reload_pair(self):
        captured = json.loads((cover_fixture.ROOT/'tests/fixtures/aim-cover-96_5.json').read_text())
        obs = captured['obs']
        target = next(a for a in obs['mechs'] if a['id'] == 12)
        stats = self.bot.stats(obs['self'])
        action = self.bot.combat.plan(obs, target)
        with patch('time.perf_counter', return_value=0.):
            goal = self.helper.step(obs, target, stats, True, .019)
        self.assertIsNotNone(goal, self.helper.last_report)
        self.assertTrue(self.helper.last_report['admitted'])
        self.assertTrue(self.helper.last_report['static_complete'])
        self.assertTrue(self.helper.last_report['incoming_complete'])
        self.assertEqual(self.helper.pair['P'], tuple(obs['self']['pos']))
        self.assertFalse(action['fire'][0])

    def test_recorded_dual_weapon_laser_fix_never_admits_gun_only_cover(self):
        case = copy.deepcopy(aim_fixture.DATA['laser_bridge'])
        controller = Combat(case['config'], self.arena.line_of_fire)
        obs, target = case['obs'], case['target']
        action = controller.plan(obs, target)
        unchanged = copy.deepcopy(action)
        helper = type(self.helper)(case['config'], self.arena, controller)
        with patch('time.perf_counter', return_value=0.):
            result = helper.step(obs, target, controller._self_stats(obs['self']), True, .019)
        self.assertIsNone(result)
        self.assertIsNone(helper.pair)
        self.assertEqual(action, unchanged)
        self.assertAlmostEqual(action['aim'][1], .14646678791560827, places=8)
        self.assertFalse(action['fire'][0])  # Existing selected-aim shared-slot cost.
        self.assertFalse(action['fire'][1])  # Existing release, never a cover charge.


if __name__ == '__main__':
    unittest.main()
