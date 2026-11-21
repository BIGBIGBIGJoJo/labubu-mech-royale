"""Captured blocked pursuit geometry and bounded target-memory behavior."""
import gzip
import json
import math
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena_map import ArenaMap
from positioning import CombatPositioning
import test_strategy as fixtures


class ObstacleArena:
    """A wall blocks the local pursuit point but permits a detour to its side."""
    def __init__(self):
        self.block_all = False

    def ground_height(self, x, y):
        return 0.0

    def point_clear(self, point, radius, height):
        return not self.block_all and not (8-radius < point[0] < 30+radius and abs(point[1]) < 8+radius)


class PositioningTests(unittest.TestCase):
    def setUp(self):
        self.arena = ObstacleArena()
        self.policy = CombatPositioning({}, self.arena)
        self.stats = {"radius": 2.5, "height": 9.0}
        self.obs = {"t": 10.0, "self": {"pos": [0, 0, 0]},
                    "zone": {"center": [0, 0], "radius": 300, "next_center": [0, 0],
                             "next_radius": 300, "shrink_start": 100, "shrink_end": 120}}
        self.target = {"id": 7, "pos": [100, 0, 30]}

    def blocked(self):
        return self.policy.choose(self.obs, self.target, [20, 0, 0], 33, self.stats,
                                  time.perf_counter()+.02)

    def test_blocked_local_goal_gets_grounded_incremental_anchor(self):
        anchor = self.blocked()
        self.assertIsNotNone(anchor)
        self.assertTrue(self.arena.point_clear(anchor, 2.5, 9))
        self.assertEqual(anchor[2], 0)
        # Actual preferred range is 33; approach from 100 m stops 20 m nearer.
        self.assertAlmostEqual(math.dist(anchor[:2], self.target["pos"][:2]), 80)
        self.assertGreater(abs(anchor[1]), 10)

    def test_unblocked_local_intention_is_preserved(self):
        ideal = [-12, 3, 0]
        self.assertEqual(self.policy.choose(self.obs, self.target, ideal, 33, self.stats), tuple(ideal))

    def test_temporary_occlusion_preserves_anchor_then_expires(self):
        anchor = self.blocked()
        self.obs["t"] += 1.5
        self.assertEqual(self.policy.continuation(self.obs, self.stats), anchor)
        self.obs["t"] += .6
        self.assertIsNone(self.policy.continuation(self.obs, self.stats))

    def test_small_target_motion_does_not_reverse_detour(self):
        anchor = self.blocked()
        self.obs["t"] += .5
        self.target["pos"][1] = 2
        self.assertEqual(self.blocked(), anchor)

    def test_large_target_motion_invalidates_old_anchor(self):
        anchor = self.blocked()
        self.obs["t"] += .5
        self.target["pos"][1] = 35
        self.assertNotEqual(self.blocked(), anchor)

    def test_body_growth_and_new_obstacle_invalidate_memory(self):
        self.blocked()
        self.assertIsNone(self.policy.continuation(self.obs, {"radius": 3, "height": 10.8}))
        self.blocked()
        self.arena.block_all = True
        self.assertIsNone(self.policy.continuation(self.obs, self.stats))
        self.assertIsNone(self.blocked())

    def test_stationary_detour_is_invalidated_and_not_reselected(self):
        anchor = self.blocked()
        # Keep the target visible while the observed mech fails to move.
        self.obs["t"] += 1
        self.assertEqual(self.blocked(), anchor)
        self.obs["t"] += 1.1
        replacement = self.blocked()
        self.assertNotEqual(replacement, anchor)

    def test_observed_progress_keeps_longer_detour(self):
        anchor = self.blocked()
        self.obs["t"] += 1
        self.blocked()
        self.obs["t"] += 1.1
        self.obs["self"]["pos"][1] = 4
        self.assertEqual(self.blocked(), anchor)

    def test_clear_but_stalled_destination_is_not_reselected(self):
        # A clear destination can still lack a usable route. Lack of observed
        # progress must also invalidate an initially valid local intention.
        ideal = [-12, 3, 0]
        first = self.policy.choose(self.obs, self.target, ideal, 33, self.stats)
        self.obs["t"] += 1
        self.policy.choose(self.obs, self.target, ideal, 33, self.stats)
        self.obs["t"] += 1.1
        replacement = self.policy.choose(self.obs, self.target, ideal, 33, self.stats)
        self.assertNotEqual(replacement, first)

    def test_zone_shrink_cancels_now_unsafe_anchor(self):
        self.blocked()
        self.obs["zone"].update(next_radius=4, shrink_start=10, shrink_end=11)
        self.assertIsNone(self.policy.continuation(self.obs, self.stats))

    def test_cancel_preempts_target_memory(self):
        self.blocked()
        self.policy.cancel()
        self.assertIsNone(self.policy.continuation(self.obs, self.stats))

    def test_expired_budget_does_not_scan_candidates(self):
        self.assertIsNone(self.policy.choose(self.obs, self.target, [20,0,0], 33,
                                            self.stats, time.perf_counter()-1))


class CapturedArenaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT/"check/stream.jsonl.gz", "rt", encoding="utf-8") as stream:
            cls.config = json.loads(next(stream))["config"]
        cls.arena = ArenaMap(ROOT/"arena", cls.config)
        if not cls.arena.available:
            raise RuntimeError(cls.arena.error)

    def test_captured_lightning_pursuit_has_complete_detour_route(self):
        # Actual baseline observation at 113.8 s: enemy airborne north of a
        # building; the short local pursuit point was inside that building.
        obs = {"t": 113.8, "self": {"pos": [-29.39,-58.32,-.01]},
               "zone": {"center": [31.87,-54.85], "radius": 240,
                        "next_center": [86.01,-87.05], "next_radius": 140,
                        "shrink_start": 115, "shrink_end": 132.5}}
        target = {"id": 7, "pos": [-29.09,81.63,41.53]}
        ideal = [-29.347127644053646,-38.3200459510254,-.01]
        stats = {"radius": 2.875, "height": 10.35}
        self.assertFalse(self.arena.point_clear(ideal, **stats))
        policy = CombatPositioning(self.config, self.arena)
        # The equipped lightning policy actually preferred 33 m, not 120 m.
        anchor = policy.choose(obs, target, ideal, 33, stats, time.perf_counter()+.02)
        self.assertIsNotNone(anchor)
        self.assertTrue(self.arena.point_clear(anchor, **stats))
        self.assertAlmostEqual(math.dist(anchor[:2], target["pos"][:2]),
                               math.dist(obs["self"]["pos"][:2], target["pos"][:2])-20)
        self.assertGreater(anchor[0], obs["self"]["pos"][0]+25)
        # Point clearance is not sufficient: establish a real A* detour too.
        self.arena._search = None
        for _ in range(50):
            direction = self.arena.navigate(obs["self"]["pos"], anchor, **stats,
                                            deadline=time.perf_counter()+.008)
            if self.arena._search and self.arena._search["done"]:
                break
        self.assertTrue(self.arena._search["done"])
        self.assertGreater(len(self.arena._path), 2)
        self.assertGreater(direction[0], .8)
        for start, end in zip(self.arena._path, self.arena._path[1:]):
            self.assertTrue(self.arena.move_clear(start, end, **stats))


class PositioningIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def remember(self):
        return self.bot.positioning.choose(self.obs, self.enemy(140), [-20, 10, 0], 120,
                                            self.bot.stats(self.obs["self"]))

    def test_visible_combat_uses_validated_destination(self):
        self.obs["mechs"] = [self.enemy(140)]
        with patch.object(self.bot.positioning, "choose", return_value=(-25,12,0)) as choose:
            self.bot.act(self.obs)
        choose.assert_called_once()
        self.assertEqual(self.bot.telemetry["goal"], (-25,12,0))

    def test_occlusion_continues_movement_without_inventing_target_or_fire(self):
        anchor = self.remember()
        self.obs["t"] += .5
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["goal"], anchor)
        self.assertEqual(self.bot.mode, "position")
        self.assertIsNone(self.bot.telemetry["target"])
        self.assertEqual(action["fire"], [False,False])

    def test_recovery_zone_and_resource_objectives_preempt_memory(self):
        for reason in ("recovery", "zone", "resource"):
            with self.subTest(reason=reason):
                self.setUp()
                self.remember()
                if reason == "recovery":
                    self.obs["self"]["hp"] = 500
                elif reason == "zone":
                    self.obs["self"]["in_zone"] = False
                else:
                    self.obs["cubes"] = [{"id": 5001, "pos": [-10,0,0]}]
                with patch.object(self.bot.positioning, "continuation", wraps=self.bot.positioning.continuation) as continuation:
                    self.bot.act(self.obs)
                continuation.assert_not_called()
                self.assertIsNone(self.bot.positioning.anchor)

    def test_no_clear_combat_candidate_holds_current_position(self):
        self.obs["mechs"] = [self.enemy(140)]
        with patch.object(self.bot.positioning, "choose", return_value=None):
            self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["goal"], self.obs["self"]["pos"])


if __name__ == "__main__":
    unittest.main()
