"""Behavioral weapon-controller tests using the official recorded config."""
import copy
import gzip
import importlib.util
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("combat", ROOT / "combat.py")
combat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(combat)
with gzip.open(ROOT / "check/stream.jsonl.gz", "rt") as stream:
    CONFIG = json.loads(next(stream))["config"]


def weapon(kind, **changes):
    item = {"kind": kind, "stats": dict(CONFIG["weapons"][kind]), "cooldown": 0}
    if kind == "gun":
        item.update(ammo=12, reload=0)
    if kind == "laser":
        item["charge"] = 0
    item.update(changes)
    return item


def observation(*weapons):
    return {"tick": 100, "t": 5.0, "self": {
        "pos": [0, 0, 0], "vel": [0, 0, 0], "aim": [0, -0.025],
        "hp": 1400, "energy": 100, "cubes": 0,
        "stats": dict(CONFIG["mech"]),
        "weapons": list(weapons) + [None] * (2 - len(weapons))}}


def enemy(x=100, y=0, velocity=None):
    return {"id": 5, "kind": "mech", "pos": [x, y, 0],
            "vel": velocity or [0, 0, 0], "cubes": 0, "hp": 1400}


class CombatTests(unittest.TestCase):
    def test_intercept_stationary_and_out_running(self):
        self.assertAlmostEqual(combat.intercept_time([100, 0, 0], [0, 0, 0], 250), 0.4)
        self.assertIsNone(combat.intercept_time([100, 0, 0], [300, 0, 0], 250))

    def test_gun_leads_crossing_target(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun")), enemy(150, 0, [0, 15, 0]))
        self.assertGreater(action["aim"][0], 0.05)
        self.assertLess(action["aim"][0], 0.08)

    def test_fast_torso_cannot_shoot_through_half_turn(self):
        obs = observation(weapon("gun"))
        obs["self"]["aim"] = [math.pi, 0]
        action = combat.Combat(CONFIG).plan(obs, enemy())
        self.assertFalse(action["fire"][0])

    def test_stationary_target_can_be_hit(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun")), enemy())
        self.assertTrue(action["fire"][0])

    def test_large_mech_can_aim_at_close_opponents_upper_body(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"))
        obs["self"]["cubes"] = 10
        obs["self"]["stats"].update(radius=3.75, height=13.5, muzzle_height=10.5)
        obs["self"]["aim"] = [0, -0.7]
        action = controller.plan(obs, enemy(6.5))
        self.assertGreaterEqual(action["aim"][1], -0.7)
        self.assertTrue(action["fire"][0])

    def test_wall_blocks_remembered_target(self):
        action = combat.Combat(CONFIG, lambda a, b: False).plan(
            observation(weapon("gun"), weapon("laser")), enemy())
        self.assertEqual(action["fire"], [False, False])

    def test_upper_body_can_be_targeted_over_low_cover(self):
        controller = combat.Combat(CONFIG, lambda a, b: b[2] >= 8.0)
        obs = observation(weapon("gun"))
        action = controller.plan(obs, enemy())
        self.assertGreater(action["aim"][1], 0.0)
        self.assertTrue(action["fire"][0])

    def test_recovery_releases_laser_and_reloads_gun(self):
        obs = observation(weapon("gun", ammo=6), weapon("laser", charge=0.5))
        action = combat.Combat(CONFIG).plan(obs, enemy(), allow_fire=False)
        self.assertEqual(action["fire"], [False, False])
        self.assertTrue(action["reload"])

    def test_laser_charges_then_releases_at_full(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("laser"))
        self.assertTrue(controller.plan(obs, enemy())["fire"][0])
        obs["self"]["weapons"][0]["charge"] = 0.5
        self.assertTrue(controller.plan(obs, enemy())["fire"][0])
        obs["self"]["weapons"][0]["charge"] = 0.75
        self.assertFalse(controller.plan(obs, enemy())["fire"][0])

    def test_full_laser_waits_for_alignment_but_not_forever(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("laser", charge=0.75))
        obs["self"]["aim"] = [math.pi, 0]
        self.assertTrue(controller.plan(obs, enemy())["fire"][0])
        obs["t"] += 0.4
        self.assertFalse(controller.plan(obs, enemy())["fire"][0])

    def test_emergency_does_not_start_charge(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("laser")), enemy(), emergency=True)
        self.assertFalse(action["fire"][0])

    def test_lightning_is_range_and_energy_gated(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("lightning"))
        self.assertFalse(controller.plan(obs, enemy(100))["fire"][0])
        self.assertTrue(controller.plan(obs, enemy(30))["fire"][0])
        obs["self"]["energy"] = 5
        self.assertFalse(controller.plan(obs, enemy(30))["fire"][0])

    def test_lightning_can_hit_low_crate_by_yaw(self):
        target = {"kind": "crate", "id": 1001, "pos": [5, 0, 0], "hp": 300}
        action = combat.Combat(CONFIG).plan(observation(weapon("lightning")), target)
        self.assertTrue(action["fire"][0])

    def test_shared_aim_does_not_fire_unaligned_gun_with_laser(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"), weapon("laser", charge=0.75))
        target = enemy(200, 0, [0, 20, 0])
        action = controller.plan(obs, target)
        self.assertLess(abs(action["aim"][0]), 0.01)
        self.assertFalse(action["fire"][0])
        self.assertFalse(action["fire"][1])

    def test_mortar_never_fires_into_own_blast(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("mortar")), enemy(10))
        self.assertFalse(action["fire"][0])

    def test_mortar_valid_arc_and_obstruction(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("mortar"))
        target = enemy(120)
        first = controller.plan(obs, target)
        self.assertGreater(first["aim"][1], 0.1)
        obs["self"]["aim"] = first["aim"]
        self.assertTrue(controller.plan(obs, target)["fire"][0])
        blocked = combat.Combat(CONFIG, lambda a, b: False).plan(obs, target)
        self.assertFalse(blocked["fire"][0])

    def test_cube_geometry_and_input_unchanged(self):
        controller = combat.Combat(CONFIG)
        target = enemy()
        target["cubes"] = 10
        self.assertEqual(controller._body(target), (3.75, 13.5))
        obs = observation(weapon("gun"))
        original = copy.deepcopy(obs)
        controller.plan(obs, target)
        self.assertEqual(obs, original)

    def test_no_target_safe_and_idle_reload(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun", ammo=11)), None)
        self.assertEqual(action["fire"], [False, False])
        self.assertTrue(action["reload"])


if __name__ == "__main__":
    unittest.main()

