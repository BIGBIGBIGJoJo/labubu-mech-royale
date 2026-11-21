"""Portable collision/navigation fixtures: no downloaded arena is required."""
from array import array
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


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

    def test_centimetre_rounded_wall_contact_can_escape_but_not_enter_wall(self):
        contact=(3.501,10,0)
        self.assertTrue(self.map.point_clear(contact,2.5,9))
        self.assertTrue(self.map.move_clear(contact,(2.75,10,0),2.5,9))
        self.assertFalse(self.map.move_clear(contact,(4,10,0),2.5,9))

    def test_match_margin_is_center_limit_without_double_counting_radius(self):
        inset=geometry.ArenaMap(self.root,{"match":{"arena_margin":5},"mech":{"step_up":1.2,"max_slope_deg":50}})
        self.assertFalse(inset.point_clear((3,30,0),2.5,9))
        self.assertTrue(inset.point_clear((5,30,0),2.5,9))
        self.assertTrue(inset.move_clear((5,30,0),(6,30,0),2.5,9))

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

    def test_cover_candidates_are_separated_and_clear(self):
        with patch.object(geometry.time, "perf_counter", return_value=100.0):
            candidates=self.map.cover_candidates((19,20,0),(20,20),40,1,9,22,deadline=101.0)
        self.assertTrue(candidates)
        self.assertLessEqual(len(candidates),12)
        for i,point in enumerate(candidates):
            self.assertTrue(self.map.point_clear(point,1,9))
            for previous in candidates[:i]:
                self.assertGreaterEqual((point[0]-previous[0])**2+(point[1]-previous[1])**2,49)


class RecordedCoverRegression(unittest.TestCase):
    """A recorded gameplay position once exhausted the cover scoring budget."""
    def test_diverse_shortlist_includes_nearby_protected_position(self):
        arena=ROOT / "arena"
        if not (arena / "v2/world.json").exists():
            self.skipTest("Bundled official arena is unavailable")
        world=geometry.ArenaMap(arena,{"mech":{"radius":2.5,"height":9,"step_up":1.2,"max_slope_deg":50}})
        self.assertTrue(world.available,world.error)
        pos=(-33.4,-301.67,-1.03)
        enemy=(10.87,-303.09,-1.02+4.5)
        with patch.object(geometry.time,"perf_counter",return_value=100.0):
            candidates=world.cover_candidates(pos,(-27.41,-140.58),380,2.5,9,12,deadline=101.0)
        protected=[p for p in candidates if (p[0]-pos[0])**2+(p[1]-pos[1])**2<35**2
                   and not world.line_of_fire((p[0],p[1],p[2]+7),enemy)]
        self.assertTrue(protected,"Shortlist must include the reachable-around-building protected side")

    def test_eight_cube_mech_cannot_pass_recorded_low_bridge(self):
        arena=ROOT / "arena"
        if not (arena / "v2/world.json").exists():
            self.skipTest("Bundled official arena is unavailable")
        world=geometry.ArenaMap(arena,{"match":{"arena_margin":30},"mech":{"radius":2.5,"height":9,"step_up":1.2,"max_slope_deg":50}})
        pos=(-117.66,-25.95,-4.87)
        southeast=(-116.84,-27.77,-4.87)
        self.assertTrue(world.move_clear(pos,southeast,2.5,9))
        self.assertFalse(world.move_clear(pos,southeast,3.5,12.6))
        self.assertTrue(world.point_clear(pos,3.5,12.6),"Rounded contact should not trap the mech")
        self.assertTrue(world.move_clear(pos,(-118.48,-24.13,-4.87),3.5,12.6))


if __name__ == "__main__":
    unittest.main()
