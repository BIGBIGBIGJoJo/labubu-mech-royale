"""Behavioral strategy checks using the official configuration and observations.

Run from anywhere: python -m unittest discover -s path/to/repo/tests -v
The flat map isolates policy decisions; geometry has its own test suite.
"""
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bot as policy


def official_fixture():
    with gzip.open(ROOT / "check/stream.jsonl.gz", "rt", encoding="utf-8") as stream:
        hello = json.loads(next(stream))
        observation = next(json.loads(line) for line in stream if '"obs"' in line)
    hello["map"]["dir"] = str(ROOT / "arena")
    return hello, observation


class FlatArena:
    """An unobstructed controlled arena, without invented combat simulation."""
    def __init__(self, *args):
        self.available = True

    def ground_height(self, x, y):
        return 0.0

    def line_of_fire(self, start, end):
        return True

    def move_clear(self, start, end, radius, height):
        return True

    def point_clear(self, point, radius, height):
        return True

    def cover_candidates(self, pos, center, radius, body_radius, height, limit=22, deadline=None):
        return [[center[0], center[1], 0], [pos[0] + 30, pos[1], 0], [pos[0], pos[1] + 30, 0]]

    def navigate(self, pos, goal, radius, height, deadline=None):
        dx, dy = goal[0] - pos[0], goal[1] - pos[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length else (0, 0)


class StrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = official_fixture()

    def setUp(self):
        self.obs = copy.deepcopy(self.recorded)
        self.obs.update(t=20.0, tick=400, alive=16, offer=None)
        for key in ("mechs", "projectiles", "crates", "cubes", "pickups", "sounds", "beams", "events", "drops"):
            self.obs[key] = []
        me = self.obs["self"]
        me.update(pos=[0, 0, 0], vel=[0, 0, 0], aim=[0, 0], hp=1400,
                  max_hp=1400, energy=100, max_energy=100, cubes=0,
                  grounded=True, in_zone=True, upgrades=[], stats=copy.deepcopy(self.hello["config"]["mech"]))
        me["weapons"] = [self.weapon("gun"), None]
        self.obs["zone"] = {"center": [0, 0], "radius": 560, "next_center": [0, 0],
                            "next_radius": 380, "shrink_start": 60, "shrink_end": 110, "dps": 20}
        with patch.object(policy, "ArenaMap", FlatArena):
            self.bot = policy.Bot(copy.deepcopy(self.hello))

    def weapon(self, kind, **values):
        weapon = {"kind": kind, "cooldown": 0, "stats": copy.deepcopy(self.hello["config"]["weapons"][kind])}
        if kind == "gun":
            weapon.update(ammo=12, reload=0)
        if kind == "laser":
            weapon["charge"] = 0
        weapon.update(values)
        return weapon

    def enemy(self, x=100, y=0, **values):
        enemy = {"id": 5, "kind": "mech", "pos": [x, y, 0], "vel": [0, 0, 0],
                 "aim": [math.pi, 0], "hp": 1400, "max_hp": 1400,
                 "cubes": 0, "weapons": ["gun"], "charging": False}
        enemy.update(values)
        return enemy

    def test_zone_hold_and_crossing_shrink_start(self):
        self.obs["t"] = 40
        self.obs["zone"]["next_center"] = [50, 0]
        self.assertEqual(self.bot.zone_future(self.obs, 10), ([0, 0], 560))
        self.obs["t"] = 50
        center, radius = self.bot.zone_future(self.obs, 20)
        self.assertEqual(center, [10, 0])
        self.assertAlmostEqual(radius, 524)

    def test_zone_uses_remaining_shrink_not_original_duration(self):
        self.obs["t"] = 85
        self.obs["zone"].update(center=[20, 0], radius=400, next_center=[40, 0], next_radius=300)
        center, radius = self.bot.zone_future(self.obs, 10)
        self.assertEqual(center, [28, 0])
        self.assertEqual(radius, 360)
        self.assertEqual(self.bot.zone_future(self.obs, 50), ([40, 0], 300))

    def test_low_hp_stops_shooting_to_allow_recovery(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy()]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["fire"], [False, False])

    def test_urgent_zone_rotation_does_not_cancel_recovery_suppression(self):
        self.obs["self"].update(hp=500, in_zone=False)
        self.obs["mechs"] = [self.enemy()]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "rotate")
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["fire"], [False, False])

    def test_imminent_enemy_permits_defensive_fire_during_recovery(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(20)]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertTrue(action["fire"][0])

    def test_recovery_hysteresis_keeps_healing_until_healthy(self):
        self.obs["self"]["hp"] = 500
        self.bot.act(self.obs)
        self.obs["self"]["hp"] = 1100
        self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.obs["self"]["hp"] = 1350
        self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)

    def test_damaged_bot_does_not_farm_crates(self):
        self.obs["self"]["hp"] = 500
        self.obs["crates"] = [{"id": 1001, "pos": [15, 0, 0], "hp": 300}]
        action = self.bot.act(self.obs)
        self.assertNotEqual(self.bot.mode, "loot")
        self.assertEqual(action["fire"], [False, False])

    def test_crate_farming_goal_keeps_aimable_standoff(self):
        for crate_distance in (1, 5, 14, 35):
            with self.subTest(crate_distance=crate_distance):
                self.bot.loot.clear()
                self.obs["crates"] = [{"id": 1001, "pos": [crate_distance, 0, 0], "hp": 300}]
                self.bot.act(self.obs)
                self.assertEqual(self.bot.mode, "loot")
                goal = self.bot.telemetry["goal"]
                separation = math.dist(goal[:2], self.obs["crates"][0]["pos"][:2])
                self.assertGreaterEqual(separation, 12.0)

    def test_destroyed_nearby_crate_is_pruned_and_its_cube_pursued(self):
        self.obs["crates"] = [{"id": 1001, "pos": [20, 0, 0], "hp": 300}]
        self.bot.act(self.obs)
        self.assertIn(("crates", 1001), self.bot.loot)
        self.obs.update(t=20.1, tick=402)
        self.obs["crates"] = []
        self.obs["cubes"] = [{"id": 5001, "pos": [20, 0, 0]}]
        action = self.bot.act(self.obs)
        self.assertNotIn(("crates", 1001), self.bot.loot)
        self.assertIn(("cubes", 5001), self.bot.loot)
        self.assertEqual(self.bot.mode, "loot")
        self.assertEqual(self.bot.telemetry["goal"], [20, 0, 0])
        self.assertGreater(action["move"][0], 0.5)
        self.assertEqual(action["fire"], [False, False])

    def test_missing_cube_behind_wall_stays_in_memory(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [5, 0, 0]}]
        self.bot.update(self.obs)
        self.obs.update(t=20.1, tick=402)
        self.obs["cubes"] = []
        with patch.object(self.bot.map, "line_of_fire", return_value=False):
            self.bot.update(self.obs)
        self.assertIn(("cubes", 5001), self.bot.loot,
                      "A nearby object behind solid cover may still exist")

    def test_missing_cube_in_clear_near_sensors_is_pruned(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [30, 0, 0]}]
        self.bot.update(self.obs)
        self.obs.update(t=20.1, tick=402)
        self.obs["cubes"] = []
        self.bot.update(self.obs)
        self.assertNotIn(("cubes", 5001), self.bot.loot)

    def test_missing_loot_beyond_near_sensor_range_stays_in_memory(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [60, 0, 0]}]
        self.bot.update(self.obs)
        self.obs.update(t=20.1, tick=402)
        self.obs["cubes"] = []
        self.bot.update(self.obs)
        self.assertIn(("cubes", 5001), self.bot.loot,
                      "Distant loot can leave the field of view without disappearing")

    def test_safe_cube_is_pursued_but_enemy_contested_cube_is_not(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [15, 0, 0]}]
        self.bot.update(self.obs)
        goal = self.bot.resource_goal(self.obs, [])
        self.assertEqual(goal[2], "cubes")
        enemy = self.enemy(20)
        threat = {"actor": enemy, "d": 20, "los": True, "risk": 2}
        self.assertIsNone(self.bot.resource_goal(self.obs, [threat]))

    def test_safe_cube_detour_wins_movement_over_a_distant_target(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 15, 0]}]
        self.obs["mechs"] = [self.enemy(150)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "loot")
        self.assertEqual(self.bot.telemetry["goal"], [0, 15, 0])
        self.assertGreater(action["move"][1], 0.5)
        self.assertTrue(action["fire"][0],
                        "Safe resource movement can coexist with a valid distant shot")

    def test_close_enemy_blocks_resource_detour(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 15, 0]}]
        self.obs["mechs"] = [self.enemy(50)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "engage")
        self.assertNotEqual(self.bot.telemetry["goal"], [0, 15, 0])

    def test_pickup_requires_vertical_and_horizontal_reach(self):
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [1, 0, 5]}]
        self.assertEqual(self.bot.take_weapon(self.obs), {})
        self.obs["pickups"][0]["pos"] = [1, 0, 0]
        self.assertEqual(self.bot.take_weapon(self.obs), {"take": 8001})

    def test_duplicate_pickup_and_charging_laser_cannot_be_swapped(self):
        self.obs["self"]["weapons"][1] = self.weapon("laser", charge=0.5)
        self.obs["zone"].update(radius=40, next_radius=25)
        self.obs["pickups"] = [{"id": 8001, "kind": "lightning", "pos": [1, 0, 0]},
                               {"id": 8002, "kind": "laser", "pos": [1, 0, 0]}]
        self.assertEqual(self.bot.take_weapon(self.obs), {})

    def test_late_circle_ignores_laser_it_would_not_equip(self):
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        self.obs["zone"].update(radius=40, next_radius=25)
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [1, 0, 0]}]
        self.bot.update(self.obs)
        self.assertEqual(self.bot.take_weapon(self.obs), {})
        self.assertIsNone(self.bot.resource_goal(self.obs, []),
                          "Do not keep pursuing a pickup the loadout selector refuses")

    def test_offer_selection_is_valid_for_known_and_new_upgrade_ids(self):
        upgrades = self.hello["config"]["upgrades"]
        for start in range(0, len(upgrades), 3):
            choices = copy.deepcopy(upgrades[start:start + 3])
            self.obs["offer"] = {"id": start, "expires": 25, "choices": choices}
            self.assertIn(self.bot.choose_upgrade(self.obs), range(len(choices)))
        self.obs["offer"] = {"id": 100, "expires": 25, "choices": [{"id": "future_upgrade"}]}
        self.assertEqual(self.bot.choose_upgrade(self.obs), 0)

    def test_empty_area_explores_instead_of_permanently_standing(self):
        self.obs["self"]["pos"] = [100, 0, 0]
        travelled_commands = 0.0
        for second in range(5):
            self.obs.update(t=20 + second, tick=400 + second * 20)
            action = self.bot.act(self.obs)
            travelled_commands += math.hypot(*action["move"])
        self.assertGreater(travelled_commands, 0.1,
                           "Healthy empty-area policy must search for resources or useful positions")

    def test_observation_is_not_mutated(self):
        self.obs["mechs"] = [self.enemy(50)]
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [1, 0, 0]}]
        before = copy.deepcopy(self.obs)
        self.bot.act(self.obs)
        self.assertEqual(self.obs, before)


if __name__ == "__main__":
    unittest.main()
