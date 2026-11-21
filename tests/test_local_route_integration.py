"""Root contracts keep strategic intent separate from a checked local exit."""
import unittest
from unittest.mock import patch

import test_strategy as fixtures
from local_route import LocalRouteRecovery


class LocalRouteIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    enemy = fixtures.StrategyTests.enemy
    weapon = fixtures.StrategyTests.weapon

    def test_ordinary_navigation_keeps_the_strategic_goal(self):
        self.obs["mechs"] = [self.enemy(160)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["goal"], self.bot.telemetry["tactical_goal"])
        self.assertFalse(self.bot.route_recovery.active)
        self.assertIs(self.bot.route_recovery.arena, self.bot.map)

    def test_discovery_does_not_retire_goal_during_deliberate_search_wait(self):
        self.bot.mode = "rotate"
        self.bot.goal = [100, 0, 0]
        self.bot.goal_until = self.obs["t"] + 10
        self.bot.goal_progress = {"goal": [100, 0, 0], "distance": 100,
                                  "since": self.obs["t"] - 5}
        self.bot.check_route_progress(self.obs, [100, 0, 0], (0, 0), True,
                                      "local_searching")
        self.assertEqual(self.bot.failed_goals, [])
        self.assertGreater(self.bot.goal_until, self.obs["t"])
        self.assertEqual(self.bot.goal, [100, 0, 0])

    def test_completed_local_phase_restores_ordinary_failed_goal_retirement(self):
        self.bot.mode = "rotate"
        self.bot.check_route_progress(self.obs, [100, 0, 0], (0, 0), True,
                                      "unreachable")
        self.assertEqual(self.bot.failed_goals[0][0], [100, 0, 0])
        self.assertEqual(self.bot.goal_until, -1)

    def test_exit_guides_movement_without_replacing_combat_target(self):
        self.obs["mechs"] = [self.enemy(100)]
        self.bot.route_recovery = LocalRouteRecovery(self.bot.map)
        exit_goal = [-25, 0, 0]

        def local_route(obs, goal, stats, **kwargs):
            self.bot.route_recovery.status = "local_following"
            self.bot.route_recovery.last_report = {"status": "local_following"}
            return (-1, 0), exit_goal

        with patch.object(self.bot.route_recovery, "navigate", side_effect=local_route), \
                patch.object(self.bot, "movement", wraps=self.bot.movement) as movement:
            action = self.bot.act(self.obs)
        self.assertEqual(movement.call_args.args[6], exit_goal)
        self.assertEqual(self.bot.telemetry["tactical_goal"], exit_goal)
        self.assertNotEqual(self.bot.telemetry["goal"], exit_goal)
        self.assertEqual(self.bot.telemetry["target"], self.obs["mechs"][0]["id"])
        self.assertTrue(action["fire"][0])
        self.assertEqual(self.bot.failed_goals, [])


if __name__ == "__main__":
    unittest.main()
