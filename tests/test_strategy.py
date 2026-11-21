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
import time
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

    def test_cube_collision_size_scales_but_live_eye_muzzle_do_not_twice(self):
        me = self.obs["self"]
        me["cubes"] = 8
        me["stats"].update(radius=2.5, height=9, eye_height=11.2, muzzle_height=9.8)
        before = copy.deepcopy(me)
        stats = self.bot.stats(me)
        self.assertAlmostEqual(stats["radius"], 3.5)
        self.assertAlmostEqual(stats["height"], 12.6)
        self.assertAlmostEqual(stats["eye_height"], 11.2)
        self.assertAlmostEqual(stats["muzzle_height"], 9.8)
        self.assertEqual(me, before)

    def test_zone_uses_remaining_shrink_not_original_duration(self):
        self.obs["t"] = 85
        self.obs["zone"].update(center=[20, 0], radius=400, next_center=[40, 0], next_radius=300)
        center, radius = self.bot.zone_future(self.obs, 10)
        self.assertEqual(center, [28, 0])
        self.assertEqual(radius, 360)
        self.assertEqual(self.bot.zone_future(self.obs, 50), ([40, 0], 300))

    def test_low_hp_stops_shooting_to_allow_recovery(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(300)]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["fire"], [False, False])

    def test_low_health_continues_combat_against_near_visible_mech(self):
        self.obs["self"]["hp"] = 725
        self.obs["mechs"] = [self.enemy(100, hp=500)]
        self.obs["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "bearing": 0, "by": 5}]
        action = self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
        self.assertEqual(self.bot.mode, "engage")
        self.assertTrue(action["fire"][0])

    def test_reloading_recovery_faces_between_split_attackers(self):
        self.obs["self"]["hp"] = 400
        self.obs["self"]["aim"] = [2.22, 0]
        self.obs["self"]["weapons"][0].update(ammo=0, reload=1.2)
        self.obs["self"]["weapons"][0]["stats"]["range"] = 30
        angles = (.49, 2.22)
        self.obs["mechs"] = [self.enemy(60 * math.cos(a), 60 * math.sin(a), id=i + 5)
                             for i, a in enumerate(angles)]
        action = self.bot.act(self.obs)
        self.assertEqual(action["fire"], [False, False])
        for angle in angles:
            self.assertLess(abs((angle - action["aim"][0] + math.pi) % math.tau - math.pi), math.pi / 2)

    def test_open_field_recovery_retreats_while_facing_attacker(self):
        self.obs["self"]["hp"] = 500
        self.obs["self"]["weapons"][0]["stats"]["range"] = 60
        self.obs["mechs"] = [self.enemy(80)]
        self.obs["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "bearing": 0, "by": 5}]
        with patch.object(self.bot.map, "cover_candidates", return_value=[]):
            action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertLess(action["move"][0], -0.5,
                        "No nearby cover must not mean standing still under fire")
        self.assertAlmostEqual(action["aim"][0], 0.0, places=5)

    def test_protected_quiet_recovery_stays_put_to_heal(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(80)]
        with patch.object(self.bot.map, "cover_candidates", return_value=[]), \
                patch.object(self.bot.map, "line_of_fire", return_value=False):
            action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["move"], [0.0, 0.0])
        self.assertEqual(action["fire"], [False, False])

    def test_recovery_stops_fire_when_enemy_leaves_usable_range(self):
        self.obs["self"]["hp"] = 725
        self.obs["mechs"] = [self.enemy(100, hp=500)]
        self.obs["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "bearing": 0, "by": 5}]
        self.bot.act(self.obs)
        self.obs.update(t=23.1, tick=462, events=[])
        self.obs["mechs"][0]["pos"] = [300, 0, 0]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["fire"], [False, False])

    def test_zone_damage_does_not_cancel_quiet_recovery(self):
        self.obs["self"]["hp"] = 725
        self.obs["mechs"] = [self.enemy(300, hp=500)]
        self.obs["events"] = [{"type": "damaged", "amount": 20, "weapon": "zone", "bearing": None, "by": None}]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["fire"], [False, False])

    def test_near_enemy_keeps_combat_even_after_short_regen_delay(self):
        self.obs["self"]["hp"] = 725
        self.obs["self"]["stats"]["regen_delay"] = 2
        self.obs["mechs"] = [self.enemy(100, hp=500)]
        self.obs["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "bearing": 0, "by": 5}]
        self.bot.act(self.obs)
        self.obs.update(t=22.1, tick=442, events=[])
        action = self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
        self.assertTrue(action["fire"][0])

    def test_unrelated_recent_damage_does_not_change_nearest_npc_combat(self):
        self.obs["self"]["hp"] = 725
        self.obs["mechs"] = [self.enemy(50, id=100, kind="npc", hp=350, max_hp=350)]
        self.obs["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "bearing": 0, "by": 5}]
        action = self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
        self.assertTrue(action["fire"][0])
        self.assertIsNone(self.bot.resource_key)

    def test_nearest_npc_wins_before_wounded_farther_attacker(self):
        self.obs["mechs"] = [self.enemy(150),
                             self.enemy(45, id=100, kind="npc", hp=300, max_hp=350),
                             self.enemy(55, id=101, kind="npc", hp=100, max_hp=350)]
        self.obs["events"] = [{"type": "damaged", "amount": 25, "weapon": "npc", "bearing": 0, "by": attacker}
                              for attacker in (100, 101)]
        self.bot.update(self.obs)
        target = self.bot.choose_target(self.obs, self.bot.threats(self.obs, self.bot.stats(self.obs["self"])))
        self.assertEqual(target["id"], 100, "Distance decides before woundedness")

    def test_nearer_npc_wins_over_immediate_mech(self):
        self.obs["mechs"] = [self.enemy(60), self.enemy(50, id=100, kind="npc", hp=350, max_hp=350)]
        self.obs["events"] = [{"type": "damaged", "amount": 25, "weapon": "npc", "bearing": 0, "by": 100}]
        self.bot.update(self.obs)
        target = self.bot.choose_target(self.obs, self.bot.threats(self.obs, self.bot.stats(self.obs["self"])))
        self.assertEqual(target["id"], 100)

    def test_quiet_nearer_npc_is_selected_before_distant_mech(self):
        self.obs["mechs"] = [self.enemy(150), self.enemy(50, id=100, kind="npc", hp=350, max_hp=350)]
        self.bot.update(self.obs)
        target = self.bot.choose_target(self.obs, self.bot.threats(self.obs, self.bot.stats(self.obs["self"])))
        self.assertEqual(target["id"], 100)

    def test_recovery_returns_fire_at_actual_npc_then_resumes_quiet_healing(self):
        self.obs["self"]["hp"] = 725
        self.obs["mechs"] = [self.enemy(150), self.enemy(50, id=100, kind="npc", hp=350, max_hp=350)]
        self.obs["events"] = [{"type": "damaged", "amount": 25, "weapon": "npc", "bearing": 0, "by": 100}]
        action = self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
        self.assertTrue(action["fire"][0])
        self.obs.update(t=23.1, tick=462, events=[], mechs=[])
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["fire"], [False, False])

    def test_urgent_zone_rotation_does_not_cancel_recovery_suppression(self):
        self.obs["self"].update(hp=500, in_zone=False)
        self.obs["mechs"] = [self.enemy(300)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "rotate")
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["fire"], [False, False])

    def test_imminent_enemy_interrupts_quiet_recovery_for_combat(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(20)]
        action = self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
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

    def test_authorized_short_cube_detour_keeps_distant_target_fire(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 15, 0]}]
        self.obs["mechs"] = [self.enemy(150)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "detour")
        self.assertEqual(self.bot.resource_key, ("cubes", 5001))
        self.assertEqual(self.bot.telemetry["pursuit_target"], 5)
        self.assertTrue(action["fire"][0],
                        "A brief authorized detour keeps a valid nearest-enemy shot")

    def test_close_enemy_blocks_resource_detour(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 15, 0]}]
        self.obs["mechs"] = [self.enemy(50)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "engage")
        self.assertNotEqual(self.bot.telemetry["goal"], [0, 15, 0])

    def test_approaching_lightning_carrier_retains_velocity_aware_backpedal(self):
        self.obs["mechs"] = [self.enemy(75, vel=[-11.7, 0, 0], weapons=["gun", "lightning"])]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "engage")
        self.assertFalse(self.bot.recover)
        self.assertLess(action["move"][0], 0)
        self.assertTrue(action["fire"][0])

    def test_spacing_boost_preserves_energy_floor(self):
        self.obs["mechs"] = [self.enemy(75, vel=[-11.7, 0, 0], weapons=["gun", "lightning"])]
        for energy in (35, 20, 0):
            with self.subTest(energy=energy):
                self.obs["self"]["energy"] = energy
                action = self.bot.act(self.obs)
                self.assertLess(action["move"][0], 0)
                self.assertFalse(action["boost"])

    def test_stationary_enemy_at_preferred_distance_keeps_strafe(self):
        self.obs["mechs"] = [self.enemy(70, vel=[0, 0, 0])]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "engage")
        self.assertLess(abs(action["move"][0]), 0.1)
        self.assertGreater(abs(action["move"][1]), 0.9)
        self.assertFalse(action["boost"])

    def test_ranged_duel_at_new_band_strafes_without_opening_extra_range(self):
        self.obs["mechs"] = [self.enemy(70)]
        action = self.bot.act(self.obs)
        self.assertLess(abs(action["move"][0]), .1)
        self.assertGreater(abs(action["move"][1]), .9)
        self.assertTrue(action["fire"][0])

    def test_healthy_lightning_loadout_closes_to_use_secondary(self):
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        self.obs["mechs"] = [self.enemy(80)]
        action = self.bot.act(self.obs)
        self.assertGreater(action["move"][0], .5,
                           "A healthy isolated duel should not keep lightning outside its range")

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

    def test_expired_tactical_budget_keeps_clear_navigation(self):
        move, boost = self.bot.movement(self.obs, (1, 0), [], self.bot.stats(self.obs["self"]),
                                       False, time.perf_counter() - 1)
        self.assertGreater(move[0], 0.9,
                           "Exhausting tactical search time must not erase a safe navigation direction")

    def test_expired_tactical_budget_does_not_walk_into_obstruction(self):
        with patch.object(self.bot.map, "move_clear", return_value=False):
            move, boost = self.bot.movement(self.obs, (1, 0), [], self.bot.stats(self.obs["self"]),
                                           False, time.perf_counter() - 1)
        self.assertEqual(tuple(move), (0, 0))


if __name__ == "__main__":
    unittest.main()
