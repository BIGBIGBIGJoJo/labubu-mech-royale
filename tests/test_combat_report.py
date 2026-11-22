"""Fresh, isolated geometry metadata must not become stale fire authority."""
import copy
import importlib.util
from pathlib import Path
import unittest

_spec = importlib.util.spec_from_file_location(
    "combat_report_fixtures", Path(__file__).with_name("test_combat.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
Combat = _fixture.combat.Combat
CONFIG = _fixture.CONFIG
observation, weapon, enemy = _fixture.observation, _fixture.weapon, _fixture.enemy


class CombatReportTests(unittest.TestCase):
    def test_reload_reports_geometry_without_authorizing_a_shot(self):
        obs = observation(weapon("gun", reload=2.35, ammo=10))
        obs["self"]["aim"] = [1.0, 0.0]
        target = enemy()
        original_obs, original_target = copy.deepcopy(obs), copy.deepcopy(target)
        controller = Combat(CONFIG)
        action = controller.plan(obs, target)
        report = controller.last_report
        self.assertFalse(action["fire"][0])
        self.assertTrue(report["solution"]["clear"])
        self.assertEqual(report["tick"], obs["tick"])
        self.assertEqual(report["t"], obs["t"])
        self.assertEqual(report["target_id"], target["id"])
        self.assertEqual(report["slot"], 0)
        self.assertEqual(report["pos"], tuple(obs["self"]["pos"]))
        self.assertEqual(report["actual_aim"], tuple(obs["self"]["aim"]))
        self.assertEqual(report["action_dt"], controller.action_dt)
        self.assertEqual(obs, original_obs)
        self.assertEqual(target, original_target)

    def test_early_returns_and_unusable_target_clear_old_geometry(self):
        controller = Combat(CONFIG)
        obs = observation(weapon("gun"))
        for target, allow_fire in ((None, True), (enemy(), False), (enemy(10000), True)):
            controller.plan(obs, enemy())
            self.assertIsNotNone(controller.last_report)
            controller.plan(obs, target, allow_fire=allow_fire)
            self.assertIsNone(controller.last_report)

    def test_report_copies_solver_lists_and_cannot_rewrite_the_action(self):
        controller = Combat(CONFIG)
        captured = []
        original_solver = controller._direct_solution

        def capture(*args, **kwargs):
            result = original_solver(*args, **kwargs)
            if result is not None:
                captured.append(result)
            return result

        controller._direct_solution = capture
        obs = observation(weapon("gun"))
        action = controller.plan(obs, enemy())
        unchanged = copy.deepcopy(action)
        report = controller.last_report
        self.assertEqual(len(captured), 1)  # No second hypothetical solve.
        self.assertIsNot(report["solution"], captured[0])
        report["solution"]["aim"][0] = 123.0
        report["solution"]["point"][0] = 456.0
        self.assertNotEqual(captured[0]["aim"][0], 123.0)
        self.assertNotEqual(captured[0]["point"][0], 456.0)
        self.assertEqual(action, unchanged)
        obs["self"]["pos"][0] = 99.0
        self.assertEqual(report["pos"], (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
