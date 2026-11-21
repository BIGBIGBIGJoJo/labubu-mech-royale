"""Directed closure, uncertainty, connector validity and safe-goal-only scope."""
import copy
import gzip
import json
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest.mock import patch

from arena_map import ArenaMap
import ground_reachability as gr
import test_strategy as strategy
import test_geometry as fixtures


ROOT = Path(__file__).resolve().parents[1]
DIMS = (2.5, 9.)


def index(grid=(3, 1), free=b"\x07", edges=b"\x01\x01\x00"):
    count, payload = gr.build_components(grid, free, edges)
    return gr.ReachabilityIndex(grid, [{"dims": DIMS, "components": count}], payload)


class TinyArena:
    step_up = 1.2
    CONTACT_EPS = .015
    def __init__(self):
        self.calls = []
        self.rule = lambda a, b: a == b

    def ground_height(self, x, y):
        return 0.

    def _cell(self, point):
        return (round(point[0] / 5), 0)

    def _nearest_free(self, cell, dims, deadline):
        return cell if 0 <= cell[0] < 3 else None

    def _point(self, cell):
        return (cell[0] * 5., 0., 0.)

    def move_clear(self, start, end, radius, height):
        self.calls.append((tuple(start), tuple(end), radius, height))
        return self.rule(tuple(start), tuple(end))


class DirectedIndexTests(unittest.TestCase):
    def test_one_way_transitive_path_does_not_authorize_reverse(self):
        graph = index()
        self.assertTrue(graph.reaches((0, 0), (2, 0), DIMS))
        self.assertFalse(graph.reaches((2, 0), (0, 0), DIMS))
        self.assertTrue(graph.reaches((1, 0), (1, 0), DIMS))
        self.assertIsNone(graph.reaches((0, 0), (3, 0), DIMS))
        self.assertIsNone(graph.reaches((0, 0), (1, 0), (3., 10.)))

    def test_diagonal_corner_rule_is_part_of_graph(self):
        # 0 -> 3 raw diagonal exists, but intervening cell 1 is not free.
        graph = index((2, 2), b"\x0d", b"\x10\x00\x00\x00")
        self.assertFalse(graph.reaches((0, 0), (1, 1), DIMS))
        self.assertIsNone(graph.reaches((0, 0), (1, 0), DIMS))


class GoalContextTests(unittest.TestCase):
    def setUp(self):
        self.arena = TinyArena()
        self.owner = gr.GroundReachability(self.arena, index())

    def context(self, pos=(0., 0., 0.), radius=2.5, height=9., seconds=1):
        return self.owner.begin(pos, radius, height, time.perf_counter() + seconds)

    def test_graph_yes_requires_actual_start_and_goal_connectors(self):
        self.assertEqual(self.context().classify((10., 0., 0.)), gr.YES)
        self.assertEqual(len(self.arena.calls), 2)
        # The immutable final connector is reused, but a new start is checked.
        self.assertEqual(self.context().classify((10., 0., 0.)), gr.YES)
        self.assertEqual(len(self.arena.calls), 3)
        self.assertEqual(self.context((1., 0., 0.)).classify((10., 0., 0.)), gr.UNKNOWN)

    def test_clear_continuous_route_preserves_goal_across_graph_gap(self):
        self.arena.rule = lambda a, b: True
        self.assertEqual(self.context((10., 0., 0.)).classify((0., 0., 0.)), gr.YES)
        self.assertEqual(len(self.arena.calls), 1)

    def test_no_requires_blocked_direct_route_and_valid_start_connector(self):
        self.assertEqual(self.context((10., 0., 0.)).classify((0., 0., 0.)), gr.NO)
        self.arena.calls.clear()
        self.arena.rule = lambda a, b: False
        self.assertEqual(self.context((10., 0., 0.)).classify((0., 0., 0.)), gr.UNKNOWN)

    def test_failed_goal_connector_is_unknown_when_graph_has_route(self):
        self.arena.rule = lambda a, b: a == b == (0., 0., 0.)
        self.assertEqual(self.context().classify((10., 0., 0.)), gr.UNKNOWN)

    def test_raw_body_dimensions_are_in_connector_cache_key(self):
        self.assertEqual(self.context(radius=2.49).classify((10., 0., 0.)), gr.YES)
        first = len(self.arena.calls)
        self.assertEqual(self.context(radius=2.5).classify((10., 0., 0.)), gr.YES)
        self.assertEqual(len(self.arena.calls) - first, 2)

    def test_expired_and_insufficient_budget_are_unknown_without_geometry(self):
        for seconds in (-1, .0001):
            context = self.context(seconds=seconds)
            self.assertEqual(context.classify((10., 0., 0.)), gr.UNKNOWN)
            self.assertTrue(context.budget_exhausted)
        self.assertEqual(self.arena.calls, [])

    def test_call_finishing_after_deadline_is_not_cached_or_claimed_yes(self):
        context = self.owner.begin((0., 0., 0.), *DIMS, 101.)
        with patch.object(gr.time, "perf_counter", side_effect=[100., 100., 102.]):
            self.assertEqual(context.classify((10., 0., 0.)), gr.UNKNOWN)
        self.assertTrue(context.budget_exhausted)
        self.assertFalse(self.owner.goal_connectors)

    def test_missing_size_or_rooftop_goal_remains_unknown(self):
        self.assertEqual(self.context(radius=8).classify((10., 0., 0.)), gr.UNKNOWN)
        self.assertEqual(self.context().classify((10., 0., 4.)), gr.UNKNOWN)
        self.assertEqual(self.arena.calls, [])

    def test_goal_connector_cache_is_bounded(self):
        for i in range(520):
            self.owner.remember(self.owner.goal_connectors, i, True)
        self.assertEqual(len(self.owner.goal_connectors), 512)
        self.assertNotIn(0, self.owner.goal_connectors)

    def test_nearby_xy_does_not_certify_a_different_floor(self):
        context = self.context((0., 0., 0.))
        self.assertEqual(context.classify((0., 0., 14.)), gr.UNKNOWN)
        self.assertEqual(context.classify((0., 0., 0.)), gr.YES)
        self.assertEqual(context.classify((.5, 0., .01)), gr.YES)
        self.assertEqual(self.arena.calls, [])

    def test_airborne_or_rooftop_start_never_claims_a_ground_route(self):
        self.arena.rule = lambda a, b: True
        for z in (1.23, 14., -1.23):
            context = self.context((0., 0., z))
            self.assertEqual(context.classify((10., 0., 0.)), gr.UNKNOWN)
            self.assertEqual(context.classify((0., 0., z)), gr.UNKNOWN)
        self.assertEqual(self.arena.calls, [])

    def test_bridge_roof_and_underpass_are_distinct_close_xy_goals(self):
        # Existing real geometry fixture: bridge base12/top14 over ground0.
        # Both bodies are clear, but holding XY on the roof cannot reach below.
        with tempfile.TemporaryDirectory(prefix="mechfight-bridge-goal-") as temp:
            root = Path(temp)
            fixtures.GeometryTests.write_map(root)
            arena = ArenaMap(root, {"mech": {"step_up": 1.2, "max_slope_deg": 50}},
                             use_navigation_cache=False)
            roof, underpass = (22., 10., 14.), (22., 10., 0.)
            self.assertTrue(arena.point_clear(roof, *DIMS))
            self.assertTrue(arena.point_clear(underpass, *DIMS))
            owner = gr.GroundReachability(arena, index())
            context = owner.begin(roof, *DIMS, time.perf_counter() + 1)
            self.assertEqual(context.classify(underpass), gr.UNKNOWN)
            self.assertEqual(context.classify(roof), gr.UNKNOWN)


class RealReachabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT / "check/stream.jsonl.gz", "rt", encoding="utf-8") as file:
            config = json.loads(next(file))["config"]
        cls.arena = ArenaMap(ROOT / "arena", config)
        cls.owner = gr.GroundReachability(cls.arena)
        if cls.owner.status != "loaded":
            raise AssertionError(cls.owner.status)

    def test_c1_unreachable_target_is_rejected_and_existing_cover_is_reachable(self):
        start = (-357.41, 38.77, -5.1)
        unreachable = (-334.91728166658424, 36.48866941170657, 5.643030932368491)
        cover = (-328.4641161180888, -8.536164429948965, -4.737514379941525)
        context = self.owner.begin(start, 2.875, 10.35, time.perf_counter() + 10)
        self.assertEqual(context.classify(unreachable), gr.NO)
        self.assertEqual(context.classify(cover), gr.YES)
        self.arena._search = None
        self.arena.navigate(start, cover, 2.875, 10.35, time.perf_counter() + 10)
        self.assertTrue(self.arena._search["done"])
        self.assertEqual(len(self.arena._search["closed"]), 38)

    def test_recorded_low_bridge_roof_cannot_certify_ground_underpass(self):
        # Inside the same bridge implicated by the recorded low-clearance case
        # in test_geometry: base6.59/top8.59, terrain about -4.80.
        x, y = -114.84, -29.77
        roof = (x, y, 8.59)
        underpass = (x, y, self.arena.ground_height(x, y))
        self.assertTrue(self.arena.point_clear(roof, *DIMS))
        self.assertTrue(self.arena.point_clear(underpass, *DIMS))
        # move_clear retains roof support and does not certify requested end Z.
        self.assertTrue(self.arena.move_clear(roof, underpass, *DIMS))
        context = self.owner.begin(roof, *DIMS, time.perf_counter() + 1)
        self.assertEqual(context.classify(underpass), gr.UNKNOWN)
        farther = (-112.84, -31.77, self.arena.ground_height(-112.84, -31.77))
        self.assertGreater(abs(farther[0] - roof[0]), 1)
        self.assertEqual(context.classify(farther), gr.UNKNOWN)

    def test_asset_rejects_corruption_or_different_geometry_asset(self):
        with tempfile.TemporaryDirectory(prefix="mechfight-reachability-") as temp:
            path = Path(temp) / "metadata.bin"
            data = (ROOT / "ground-reachability.bin").read_bytes()
            path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            self.assertIsNone(gr.load(self.arena, path=path)[0])
            path.write_bytes(data)
            other = Path(temp) / "other-cache.bin"
            other.write_bytes(b"different exact geometry")
            self.assertIsNone(gr.load(self.arena, path=path, cache_path=other)[0])

    def test_missing_navigation_cache_disables_metadata(self):
        fake = TinyArena()
        loaded, _ = gr.load(fake)
        self.assertIsNone(loaded)

    def test_runtime_load_and_query_never_build_a_graph(self):
        with patch.object(gr, "build_components", side_effect=AssertionError("runtime graph build")):
            owner = gr.GroundReachability(self.arena)
            self.assertEqual(owner.status, "loaded")
            context = owner.begin((-357.41, 38.77, -5.1), 2.875, 10.35, time.perf_counter() + 10)
            self.assertEqual(context.classify((-334.91728166658424, 36.48866941170657,
                                               5.643030932368491)), gr.NO)

    def test_real_closure_matches_independent_directed_graph_floods(self):
        arena = self.arena
        rng = random.Random(1122)
        targets = [(i % arena.gx, i // arena.gx)
                   for i in rng.sample(range(arena.gx * arena.gy), 128)]
        for dims in ((2.5, 9.), (3., 10.5), (4., 13.5)):
            for start in ((31, 74), (35, 73)):
                self.assertTrue(arena._free(start, dims))
                reached, pending = {start}, [start]
                while pending:
                    cell = pending.pop()
                    for dx, dy in gr.DIRECTIONS:
                        nxt = (cell[0] + dx, cell[1] + dy)
                        if nxt in reached or not arena._free(nxt, dims):
                            continue
                        if dx and dy and (not arena._free((cell[0] + dx, cell[1]), dims)
                                          or not arena._free((cell[0], cell[1] + dy), dims)):
                            continue
                        if arena._traversable(cell, nxt, dims):
                            reached.add(nxt)
                            pending.append(nxt)
                for target in targets:
                    expected = target in reached if arena._free(target, dims) else None
                    self.assertEqual(self.owner.index.reaches(start, target, dims), expected)


class SafeGoalScopeTests(unittest.TestCase):
    def test_verified_previous_safe_goal_precedes_unverified_zone_projection(self):
        hello, obs = strategy.official_fixture()
        obs = copy.deepcopy(obs)
        obs["self"]["pos"] = [0., 0., 0.]
        obs["t"] = 0
        obs["zone"].update(center=[100., 0.], radius=50., next_center=[100., 0.],
                           next_radius=50., shrink_start=100., shrink_end=200.)
        with patch.object(strategy.policy, "ArenaMap", strategy.FlatArena):
            bot = strategy.policy.Bot(hello)
        bot.recover = True
        bot.goal, bot.goal_kind = [80., 0., 0.], "rotate"
        bot.map.cover_candidates = lambda *a, **k: []
        class Context:
            budget_exhausted = False
            def classify(self, point):
                return gr.YES if point[0] == 80 else gr.UNKNOWN
        class Routes:
            def begin(self, *a):
                return Context()
        bot.ground_routes = Routes()
        stats = bot.stats(obs["self"])
        self.assertEqual(bot.safe_goal(obs, [], stats, time.perf_counter() + 1), bot.goal)
        # Resource goals are not carried into this fallback.
        bot.goal_kind = "loot"
        self.assertNotEqual(bot.safe_goal(obs, [], stats, time.perf_counter() + 1), bot.goal)
        # A goal outside the future circle is never retained, even if reachable.
        bot.goal, bot.goal_kind = [20., 0., 0.], "rotate"
        self.assertNotEqual(bot.safe_goal(obs, [], stats, time.perf_counter() + 1), bot.goal)

    def test_only_no_candidates_are_rejected_and_unknown_preserves_scoring(self):
        hello, obs = strategy.official_fixture()
        obs = copy.deepcopy(obs)
        obs["self"]["pos"] = [0., 0., 0.]
        obs["t"] = 0
        obs["zone"].update(center=[100., 0.], radius=50., next_center=[100., 0.],
                           next_radius=50., shrink_start=100., shrink_end=200.)
        with patch.object(strategy.policy, "ArenaMap", strategy.FlatArena):
            bot = strategy.policy.Bot(hello)
        bot.recover = True
        bot.map.cover_candidates = lambda *a, **k: [[80., 0., 0.], [100., 0., 0.]]
        class Context:
            budget_exhausted = False
            verdict = gr.NO
            def classify(self, point):
                return self.verdict if point[0] == 80 else gr.UNKNOWN
        context = Context()
        class Routes:
            def begin(self, *a):
                return context
        bot.ground_routes = Routes()
        stats = bot.stats(obs["self"])
        self.assertEqual(bot.safe_goal(obs, [], stats, time.perf_counter() + 1), [100., 0., 0.])
        context.verdict = gr.UNKNOWN
        self.assertEqual(bot.safe_goal(obs, [], stats, time.perf_counter() + 1), [80., 0., 0.])


if __name__ == "__main__":
    unittest.main()
