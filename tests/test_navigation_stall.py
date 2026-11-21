"""Root diagnostics distinguish lost navigation intent from intentional holding.

These are observed-input Bot.act tests, not a physics simulation. Most isolate
the local planner's result; a blocked-geometry case exercises the real planner.
"""
import copy
import math
import unittest
from unittest.mock import patch

import test_strategy as fixtures


class NavigationStallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def advance(self, seconds=.1):
        self.obs["t"] = round(self.obs["t"] + seconds, 4)
        self.obs["tick"] = round(self.obs["t"] * 20)
        self.obs["events"] = []

    def controlled_action(self, move=(0.0, 0.0), fallback=True):
        def choose(*args, **kwargs):
            self.bot.tactical.last_report = {"fallback": fallback}
            return move, False
        with patch.object(self.bot.tactical, "choose", side_effect=choose):
            return self.bot.act(self.obs)

    def stationary_window(self, count=18, **options):
        actions = []
        for _ in range(count):
            actions.append(self.controlled_action(**options))
            self.advance()
        return actions

    def test_sustained_pursuit_fallback_reports_stall_without_forcing_motion(self):
        self.obs["mechs"] = [self.enemy(220)]
        actions = self.stationary_window()
        self.assertEqual(self.bot.mode, "engage")
        self.assertTrue(self.bot.telemetry["planner_stalled"])
        self.assertEqual(self.bot.telemetry["stall_reason"], "navigation_neutral_fallback")
        self.assertGreater(math.hypot(*self.bot.telemetry["navigation"]), .6)
        self.assertTrue(self.bot.telemetry["navigation_fallback"])
        self.assertFalse(self.bot.telemetry["stuck"], "Physical obstruction signal is unchanged")
        self.assertTrue(all(a["move"] == [0.0, 0.0] and not a["boost"] and not a["jump"] for a in actions))

    def test_urgent_rotation_stall_keeps_zone_priority(self):
        self.obs["self"]["in_zone"] = False
        self.obs["zone"].update(center=[100, 0], radius=60,
                                next_center=[100, 0], next_radius=50)
        self.obs["mechs"] = [self.enemy(-100)]
        actions = self.stationary_window()
        self.assertEqual(self.bot.state, "ROTATE")
        self.assertEqual(self.bot.mode, "rotate")
        self.assertGreater(self.bot.telemetry["goal"][0], 0)
        self.assertTrue(self.bot.telemetry["planner_stalled"])
        self.assertFalse(any(a["jump"] for a in actions))

    def test_quiet_recovery_at_cover_is_not_a_navigation_stall(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(100)]
        with patch.object(self.bot, "safe_goal", return_value=[0, 0, 0]):
            actions = self.stationary_window(25)
        self.assertEqual(self.bot.state, "RECOVER")
        self.assertEqual(self.bot.telemetry["navigation"], [0, 0])
        self.assertFalse(self.bot.telemetry["planner_stalled"])
        self.assertIsNone(self.bot.telemetry["stall_reason"])
        self.assertTrue(all(a["fire"] == [False, False] for a in actions))

    def test_arrived_resource_goal_does_not_count_as_translation_demand(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 0, 0]}]
        self.stationary_window(25)
        self.assertEqual(self.bot.resource_key, ("cubes", 5001))
        self.assertEqual(self.bot.telemetry["navigation"], [0, 0])
        self.assertFalse(self.bot.telemetry["planner_stalled"])

    def test_valid_selected_neutral_is_not_labeled_planner_failure(self):
        self.obs["mechs"] = [self.enemy(220)]
        self.stationary_window(25, fallback=False)
        self.assertGreater(math.hypot(*self.bot.telemetry["navigation"]), .6)
        self.assertFalse(self.bot.telemetry["planner_stalled"])
        self.assertFalse(self.bot.telemetry["navigation_fallback"])

    def test_brief_fallback_does_not_satisfy_sustained_window(self):
        self.obs["mechs"] = [self.enemy(220)]
        self.stationary_window(4)
        self.assertFalse(self.bot.telemetry["planner_stalled"])
        self.obs["self"]["pos"] = [2, 0, 0]
        self.controlled_action(move=(1, 0), fallback=False)
        self.assertFalse(self.bot.telemetry["planner_stalled"])

    def test_observed_progress_clears_stall_and_starts_fresh_window(self):
        self.obs["mechs"] = [self.enemy(220)]
        self.stationary_window()
        self.assertTrue(self.bot.telemetry["planner_stalled"])
        self.obs["self"]["pos"] = [2, 0, 0]
        self.controlled_action()
        self.assertFalse(self.bot.telemetry["planner_stalled"])
        self.assertEqual(len(self.bot.navigation_history), 1)
        self.advance()
        self.controlled_action()
        self.assertFalse(self.bot.telemetry["planner_stalled"])

    def test_changing_target_without_displacement_does_not_reset_window(self):
        for i in range(18):
            self.obs["mechs"] = [self.enemy(220 if i % 2 else 0,
                                            0 if i % 2 else 220,
                                            id=5 if i % 2 else 6)]
            self.controlled_action()
            self.advance()
        self.assertTrue(self.bot.telemetry["planner_stalled"])

    def test_simulation_time_reset_discards_prior_intent(self):
        self.obs["mechs"] = [self.enemy(220)]
        self.stationary_window()
        self.assertTrue(self.bot.telemetry["planner_stalled"])
        self.obs.update(t=0.0, tick=0)
        self.controlled_action()
        self.assertFalse(self.bot.telemetry["planner_stalled"])
        self.assertEqual(len(self.bot.navigation_history), 1)
        self.assertEqual(self.bot.navigation_history[0][2], 0)
        self.advance()
        self.controlled_action()
        self.assertFalse(self.bot.telemetry["planner_stalled"])

    def test_duplicate_timestamp_does_not_inflate_history(self):
        self.obs["mechs"] = [self.enemy(220)]
        for _ in range(30):
            self.controlled_action()
        self.assertEqual(len(self.bot.navigation_history), 1)
        self.assertFalse(self.bot.telemetry["planner_stalled"])

    def test_navigation_history_is_bounded_to_recent_observations(self):
        self.obs["mechs"] = [self.enemy(220)]
        self.stationary_window(70)
        self.assertLessEqual(len(self.bot.navigation_history), 21)
        latest = self.bot.navigation_time
        self.assertTrue(all(t >= latest - 2.0 for t, *_ in self.bot.navigation_history))
        self.assertEqual(self.bot.navigation_history.maxlen, 64)

    def test_deadline_verified_route_replaces_stale_fallback_report(self):
        self.obs["mechs"] = [self.enemy(220)]
        stale = self.bot.tactical.last_report = {"fallback": True}
        original = self.bot.movement
        def expired(obs, navigation, threats, stats, urgent, deadline, goal=None, **kwargs):
            return original(obs, navigation, threats, stats, urgent, -1, goal, **kwargs)
        with patch.object(self.bot, "movement", side_effect=expired), \
             patch.object(self.bot.tactical, "choose") as choose:
            action = self.bot.act(self.obs)
        choose.assert_not_called()
        self.assertIsNot(self.bot.tactical.last_report, stale)
        self.assertEqual(self.bot.telemetry["tactical"]["boost_reason"], "policy_deadline")
        self.assertGreater(math.hypot(*action["move"]), .6)
        self.assertFalse(self.bot.telemetry["navigation_fallback"])
        self.assertFalse(self.bot.last_navigation_fallback)

    def test_deadline_blocked_route_reports_current_fallback_and_stall(self):
        self.obs["mechs"] = [self.enemy(220)]
        self.bot.tactical.last_report = {"fallback": False}
        original = self.bot.movement
        def expired(obs, navigation, threats, stats, urgent, deadline, goal=None, **kwargs):
            return original(obs, navigation, threats, stats, urgent, -1, goal, **kwargs)
        actions = []
        with patch.object(self.bot, "movement", side_effect=expired), \
             patch.object(self.bot.map, "move_clear", return_value=False), \
             patch.object(self.bot.tactical, "choose") as choose:
            for _ in range(18):
                actions.append(self.bot.act(self.obs))
                self.assertTrue(self.bot.telemetry["navigation_fallback"])
                self.advance()
        choose.assert_not_called()
        self.assertTrue(self.bot.telemetry["planner_stalled"])
        self.assertEqual(self.bot.telemetry["tactical"]["boost_reason"], "policy_deadline")
        self.assertTrue(all(a["move"] == [0.0, 0.0] and not a["boost"] and not a["jump"] for a in actions))

    def test_all_blocked_trajectories_remain_neutral_even_after_stall(self):
        self.obs["mechs"] = [self.enemy(220)]
        actions = []
        with patch.object(self.bot.map, "move_clear", return_value=False):
            for _ in range(18):
                actions.append(self.bot.act(self.obs))
                self.advance()
        self.assertTrue(self.bot.telemetry["planner_stalled"])
        self.assertTrue(all(a["move"] == [0.0, 0.0] and not a["boost"] and not a["jump"] for a in actions))

    def test_local_planner_stall_does_not_blacklist_eligible_resource(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [20, 0, 0]}]
        self.stationary_window()
        self.assertEqual(self.bot.mode, "loot")
        self.assertTrue(self.bot.telemetry["planner_stalled"])
        self.assertEqual(self.bot.resource_key, ("cubes", 5001))
        self.assertNotIn(("cubes", 5001), self.bot.blacklist)

    def test_existing_physical_stuck_response_is_preserved(self):
        self.obs["mechs"] = [self.enemy(220)]
        actions = self.stationary_window(move=(1, 0), fallback=False)
        self.assertTrue(self.bot.telemetry["stuck"])
        self.assertFalse(self.bot.telemetry["planner_stalled"])
        self.assertTrue(any(a["jump"] for a in actions))

    def test_recording_intent_does_not_mutate_observation(self):
        self.obs["mechs"] = [self.enemy(220)]
        before = copy.deepcopy(self.obs)
        self.controlled_action()
        self.assertEqual(self.obs, before)


if __name__ == "__main__":
    unittest.main()
