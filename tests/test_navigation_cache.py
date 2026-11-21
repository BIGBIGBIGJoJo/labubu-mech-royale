"""Exact predicates, directed geometry, rejection and search parity."""
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
import navigation_cache as cache
import test_geometry as fixtures


ROOT = Path(__file__).resolve().parents[1]


def fixture_asset(arena, map_dir, dimensions):
    n = arena.gx * arena.gy
    free_bytes = (n + 7) // 8
    stride = free_bytes + n
    payload = bytearray(stride * len(dimensions))
    for d, dims in enumerate(dimensions):
        base = d * stride
        for i in range(n):
            cell = (i % arena.gx, i // arena.gx)
            if arena._free(cell, dims):
                payload[base + (i >> 3)] |= 1 << (i & 7)
            for bit, (dx, dy) in enumerate(cache.DIRECTIONS):
                nxt = (cell[0] + dx, cell[1] + dy)
                if 0 <= nxt[0] < arena.gx and 0 <= nxt[1] < arena.gy:
                    if arena._traversable(cell, nxt, dims):
                        payload[base + free_bytes + i] |= 1 << bit
    key = cache.geometry_key(arena, map_dir, ROOT / "arena_map.py")
    return cache.encode(key, dimensions, payload)


class NavigationCacheFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="mechfight-cache-")
        cls.root = Path(cls.directory.name)
        fixtures.GeometryTests.write_map(cls.root, sloped=True)
        cls.config = {"mech": {"step_up": 1.2, "max_slope_deg": 50}}
        cls.original = ArenaMap(cls.root, cls.config, use_navigation_cache=False)
        cls.dimensions = ((2.5, 9), (3, 13))
        cls.asset = fixture_asset(cls.original, cls.root, cls.dimensions)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.path = self.root / "test-cache.bin"
        self.path.write_bytes(self.asset)

    def load(self, arena=None, source=None):
        return cache.load(self.path, arena or self.original, self.root,
                          source or ROOT / "arena_map.py")

    def test_all_fixture_cells_and_directed_edges_match(self):
        loaded, status = self.load()
        self.assertEqual(status, "loaded")
        for dims in self.dimensions:
            for y in range(self.original.gy):
                for x in range(self.original.gx):
                    cell = (x, y)
                    self.assertEqual(loaded.free(cell, dims), self.original._free(cell, dims))
                    for dx, dy in cache.DIRECTIONS:
                        nxt = (x + dx, y + dy)
                        if 0 <= nxt[0] < self.original.gx and 0 <= nxt[1] < self.original.gy:
                            self.assertEqual(loaded.traversable(cell, nxt, dims),
                                             self.original._traversable(cell, nxt, dims))
        self.assertTrue(loaded.traversable((5, 6), (4, 6), (2.5, 9)))
        self.assertFalse(loaded.traversable((4, 6), (5, 6), (2.5, 9)))

    def test_unknown_dimensions_and_nonadjacent_queries_use_geometry(self):
        arena = ArenaMap(self.root, self.config, use_navigation_cache=False)
        arena._navigation_cache, _ = self.load(arena)
        self.assertIsNone(arena._navigation_cache.free((3, 3), (2.75, 9)))
        self.assertIsNone(arena._navigation_cache.traversable((3, 3), (3, 5), (2.5, 9)))
        with patch.object(arena, "move_clear", return_value=True) as move:
            self.assertTrue(arena._traversable((3, 3), (3, 4), (2.75, 9)))
            self.assertTrue(arena._traversable((3, 3), (3, 5), (2.5, 9)))
            self.assertEqual(move.call_count, 2)
        with patch.object(arena, "point_clear", return_value=False) as point:
            self.assertFalse(arena._free((3, 3), (2.75, 9)))
            point.assert_called_once()

    def test_supported_queries_do_not_call_geometry_or_write(self):
        arena = ArenaMap(self.root, self.config, use_navigation_cache=False)
        arena._navigation_cache, _ = self.load(arena)
        with patch.object(arena, "move_clear", side_effect=AssertionError("geometry")), \
             patch.object(arena, "point_clear", side_effect=AssertionError("geometry")), \
             patch.object(Path, "write_bytes", side_effect=AssertionError("write")):
            for dims in self.dimensions:
                self.assertEqual(arena._free((5, 6), dims), self.original._free((5, 6), dims))
                self.assertEqual(arena._traversable((5, 6), (4, 6), dims),
                                 self.original._traversable((5, 6), (4, 6), dims))
            self.assertFalse(arena._free((-1, 0), self.dimensions[0]))

    def test_missing_and_corrupt_asset_fall_back(self):
        for data in (b"", b"wrong", self.asset[:-1], self.asset[:-1] + bytes([self.asset[-1] ^ 1])):
            self.path.write_bytes(data)
            loaded, status = self.load()
            self.assertIsNone(loaded)
            self.assertTrue(status.startswith("fallback:"))
        self.path.unlink()
        self.assertIsNone(self.load()[0])

    def test_changed_map_or_algorithm_rejects_asset(self):
        changed = self.root / "different-source.py"
        changed.write_text("different algorithm", encoding="utf-8")
        self.assertIsNone(self.load(source=changed)[0])
        world = self.root / "v2/world.json"
        original = world.read_bytes()
        try:
            world.write_bytes(original + b"\n")
            self.assertIsNone(self.load()[0])
        finally:
            world.write_bytes(original)
        terrain = self.root / "v2/terrain.i16"
        original = terrain.read_bytes()
        try:
            terrain.write_bytes(bytes([original[0] ^ 1]) + original[1:])
            self.assertIsNone(self.load()[0])
        finally:
            terrain.write_bytes(original)

    def test_changed_geometry_config_rejects_but_match_duration_does_not(self):
        for field, value in (("step_up", 1.3), ("max_slope_deg", 49)):
            cfg = copy.deepcopy(self.config)
            cfg["mech"][field] = value
            arena = ArenaMap(self.root, cfg, use_navigation_cache=False)
            self.assertIsNone(self.load(arena)[0])
        cfg = {**self.config, "match": {"arena_margin": 2}}
        self.assertIsNone(self.load(ArenaMap(self.root, cfg, use_navigation_cache=False))[0])
        cfg = {**self.config, "match": {"duration": 240}}
        self.assertIsNotNone(self.load(ArenaMap(self.root, cfg, use_navigation_cache=False))[0])

    def test_crlf_source_matches_lf_source(self):
        source = self.root / "normalized-source.py"
        source.write_bytes((ROOT / "arena_map.py").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        self.assertIsNotNone(self.load(source=source)[0])


class RealNavigationCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT / "check/stream.jsonl.gz", "rt", encoding="utf-8") as stream:
            cls.config = json.loads(next(stream))["config"]
        cls.cached = ArenaMap(ROOT / "arena", cls.config)
        cls.original = ArenaMap(ROOT / "arena", cls.config, use_navigation_cache=False)
        if cls.cached.navigation_cache_status != "loaded":
            raise AssertionError(cls.cached.navigation_cache_status)

    def test_real_asset_exact_random_geometry(self):
        rng = random.Random(1122)
        cells = [(i % self.original.gx, i // self.original.gx)
                 for i in rng.sample(range(self.original.gx * self.original.gy), 128)]
        for dims in self.cached._navigation_cache.dimensions:
            for cell in cells:
                self.assertEqual(self.cached._free(cell, dims), self.original._free(cell, dims))
                for dx, dy in cache.DIRECTIONS:
                    nxt = (cell[0] + dx, cell[1] + dy)
                    if 0 <= nxt[0] < self.original.gx and 0 <= nxt[1] < self.original.gy:
                        self.assertEqual(self.cached._traversable(cell, nxt, dims),
                                         self.original._traversable(cell, nxt, dims))

    def test_real_search_path_and_state_parity_with_generous_budgets(self):
        # Captured C1 rotation route; includes an expensive detour, not an empty-grid toy.
        pos = (-357.41, 38.77, -5.1)
        goal = (-334.91728166658424, 36.48866941170657, 5.643030932368491)
        for arena in (self.original, self.cached):
            arena._search = None
            arena._path = []
        for _ in range(8):
            original = self.original.navigate(pos, goal, 2.875, 10.35, time.perf_counter() + 10)
            cached = self.cached.navigate(pos, goal, 2.875, 10.35, time.perf_counter() + 10)
            self.assertEqual(original, cached)
            self.assertEqual(self.original._search, self.cached._search)
            self.assertEqual(self.original._path, self.cached._path)
            if self.original._search["done"] or not self.original._search["heap"]:
                break

    def test_expired_deadline_preserves_empty_search(self):
        self.cached._search = None
        result = self.cached.navigate((-357.41, 38.77, -5.1), (-334.9, 36.49, 5.64),
                                      2.875, 10.35, time.perf_counter() - 1)
        self.assertEqual(result, (0, 0))
        self.assertIsNone(self.cached._search)

    def test_cache_does_not_override_steering_reserve(self):
        self.cached._search = None
        with patch("arena_map.time.perf_counter", return_value=100):
            self.cached.navigate((-357.41, 38.77, -5.1), (-334.9, 36.49, 5.64),
                                 2.875, 10.35, 100.002)
        self.assertIsNotNone(self.cached._search)
        self.assertEqual(len(self.cached._search["closed"]), 0)
        self.assertFalse(self.cached._search["done"])


if __name__ == "__main__":
    unittest.main()
