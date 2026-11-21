"""Portable collision/navigation fixtures: no downloaded arena is required."""
from array import array
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("arena_map", ROOT / "arena_map.py")
geometry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geometry)


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="mechfight-geometry-")
        cls.root = Path(cls.directory.name)
        cls.write_map(cls.root)
        cls.map = geometry.ArenaMap(cls.root, {"mech": {"step_up": 1.2, "max_slope_deg": 50}})
        if not cls.map.available:
            raise RuntimeError(cls.map.error)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @staticmethod
    def write_map(root, sloped=False):
        path = root / "v2"
        path.mkdir(parents=True, exist_ok=True)
        world = {
            "bounds": {"minX": 0, "maxX": 40, "minY": 0, "maxY": 40},
            "terrain": {"file": "terrain.i16", "minX": 0, "minY": 0,
                        "step": 1, "nx": 41, "ny": 41, "scale": 0.01},
            "prisms": [
                {"kind": "building", "base": 0, "top": 15,
                 "ring": [6, 6, 14, 6, 14, 14, 6, 14],
                 "holes": [[8, 8, 12, 8, 12, 12, 8, 12]]},
                {"kind": "bridge", "base": 12, "top": 14,
                 "ring": [20, 6, 24, 6, 24, 14, 20, 14], "holes": []},
            ],
        }
        values = [round(max(0, min(10, (x - 21) * 10 / 3)) * 100) if sloped else 0
                  for y in range(41) for x in range(41)]
        samples = array("h", values)
        if sys.byteorder != "little":
            samples.byteswap()
        (path / "world.json").write_text(json.dumps(world), encoding="utf-8")
        (path / "terrain.i16").write_bytes(samples.tobytes())

    def test_courtyard_fits_small_mech(self):
        self.assertTrue(self.map.point_clear((10, 10, 0), 1, 9))

    def test_courtyard_rejects_oversize_mech(self):
        self.assertFalse(self.map.point_clear((10, 10, 0), 3, 9))

    def test_courtyard_hole_permits_vertical_shot(self):
        self.assertTrue(self.map.line_of_fire((10, 10, 2), (10, 10, 20)))

    def test_solid_wall_blocks_shot(self):
        self.assertFalse(self.map.line_of_fire((3, 10, 5), (17, 10, 5)))

    def test_bridge_permits_shot_underneath(self):
        self.assertTrue(self.map.line_of_fire((17, 10, 7), (27, 10, 7)))

    def test_bridge_deck_blocks_shot(self):
        self.assertFalse(self.map.line_of_fire((17, 10, 13), (27, 10, 13)))

    def test_bridge_permits_shot_above(self):
        self.assertTrue(self.map.line_of_fire((17, 10, 18), (27, 10, 18)))

    def test_bridge_permits_short_mech_below(self):
        self.assertTrue(self.map.move_clear((17, 10, 0), (27, 10, 0), 1, 9))

    def test_bridge_blocks_tall_mech(self):
        self.assertFalse(self.map.move_clear((17, 10, 0), (27, 10, 0), 1, 13))

    def test_swept_cylinder_catches_grazing_wall(self):
        self.assertFalse(self.map.move_clear((3, 4, 0), (16, 4, 0), 2.5, 9))

    def test_swept_cylinder_permits_clear_route(self):
        self.assertTrue(self.map.move_clear((3, 3, 0), (16, 3, 0), 2.5, 9))

    def test_terrain_blocks_shot(self):
        self.assertFalse(self.map.line_of_fire((2, 2, 1), (3, 2, -1)))

    def test_world_bounds_account_for_radius(self):
        self.assertFalse(self.map.point_clear((1, 1, 0), 2.5, 9))

    def test_cached_descent_does_not_authorize_steep_ascent(self):
        root = self.root / "slope"
        self.write_map(root, sloped=True)
        terrain = geometry.ArenaMap(root, {"mech": {"step_up": 1.2, "max_slope_deg": 50}})
        high, low = (5, 6), (4, 6)  # Grid centers (25, 30) and (20, 30).
        dims = (2.5, 9)
        self.assertTrue(terrain._free(high, dims))
        self.assertTrue(terrain._free(low, dims))
        self.assertTrue(terrain._traversable(high, low, dims))
        self.assertFalse(terrain._traversable(low, high, dims))
        self.assertTrue(terrain._traversable(high, low, dims))


if __name__ == "__main__":
    unittest.main()
