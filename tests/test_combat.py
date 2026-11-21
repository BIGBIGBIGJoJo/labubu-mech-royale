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


def low_wall_clear(a, b):
    """Thin wall at x=95, top 7.9: a distant mech's upper body is exposed."""
    if min(a[0], b[0]) <= 95 <= max(a[0], b[0]) and a[0] != b[0]:
        fraction = (95 - a[0]) / (b[0] - a[0])
        return a[2] + fraction * (b[2] - a[2]) > 7.9
    return True


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

    def test_gun_ready_on_second_simulation_tick_fires(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun", cooldown=0.09)), enemy())
        self.assertTrue(action["fire"][0])

    def test_gun_not_ready_during_action_stays_off(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun", cooldown=0.11)), enemy())
        self.assertFalse(action["fire"][0])

    def test_aim_slew_uses_first_available_weapon_tick(self):
        target = enemy(100 * math.cos(0.32), 100 * math.sin(0.32))
        delayed = observation(weapon("gun", cooldown=0.09))
        immediate = observation(weapon("gun", cooldown=0.02))
        self.assertTrue(combat.Combat(CONFIG).plan(delayed, target)["fire"][0])
        self.assertFalse(combat.Combat(CONFIG).plan(immediate, target)["fire"][0])

    def test_reload_finishing_within_held_action_can_fire(self):
        obs = observation(weapon("gun", ammo=0, reload=0.08))
        action = combat.Combat(CONFIG).plan(obs, enemy())
        self.assertFalse(action["reload"])
        self.assertTrue(action["fire"][0])

    def test_later_launch_gets_additional_target_motion(self):
        target = enemy(100, 0, [0, 12, 0])
        immediate = combat.Combat(CONFIG).plan(observation(weapon("gun")), target)
        delayed = combat.Combat(CONFIG).plan(observation(weapon("gun", cooldown=0.09)), target)
        self.assertGreater(delayed["aim"][0], immediate["aim"][0] + 0.004)

    def test_large_mech_can_aim_at_close_opponents_upper_body(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"))
        obs["self"]["cubes"] = 10
        obs["self"]["stats"].update(radius=2.5, height=9.0, muzzle_height=10.5)
        obs["self"]["aim"] = [0, -0.7]
        action = controller.plan(obs, enemy(6.5))
        self.assertGreaterEqual(action["aim"][1], -0.7)
        self.assertTrue(action["fire"][0])

    def test_live_cube_stats_scale_body_but_not_eye_or_muzzle_twice(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"))
        obs["self"]["cubes"] = 8
        obs["self"]["stats"].update(radius=2.5, height=9, eye_height=11.2, muzzle_height=9.8)
        stats = controller._self_stats(obs["self"])
        self.assertAlmostEqual(stats["radius"], 3.5)
        self.assertAlmostEqual(stats["height"], 12.6)
        self.assertAlmostEqual(stats["eye_height"], 11.2)
        self.assertAlmostEqual(stats["muzzle_height"], 9.8)
        obs["self"]["stats"] = {}
        fallback = controller._self_stats(obs["self"])
        for key in ("radius", "height", "eye_height", "muzzle_height"):
            self.assertAlmostEqual(fallback[key], stats[key])

    def test_live_cube_body_reaches_mortar_origin_and_barrel_offset(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"), weapon("mortar"))
        obs["self"]["cubes"] = 8
        obs["self"]["pos"][2] = 2.0
        obs["self"]["stats"].update(radius=2.5, height=9, eye_height=11.2, muzzle_height=9.8)
        captured = {}
        original_direct = controller._direct_solution
        original_mortar = controller._mortar_solution
        def direct(*args):
            captured["barrel_offset"] = args[5]
            captured["gun_origin"] = list(args[2])
            return original_direct(*args)
        def mortar(*args):
            captured["mortar_origin"] = list(args[1])
            return original_mortar(*args)
        controller._direct_solution = direct
        controller._mortar_solution = mortar
        controller.plan(obs, enemy(120))
        self.assertAlmostEqual(captured["barrel_offset"], 4.0)
        self.assertAlmostEqual(captured["gun_origin"][2], 11.8)
        self.assertAlmostEqual(captured["mortar_origin"][2], 15.1)

    def test_wall_blocks_remembered_target(self):
        action = combat.Combat(CONFIG, lambda a, b: False).plan(
            observation(weapon("gun"), weapon("laser")), enemy())
        self.assertEqual(action["fire"], [False, False])

    def test_upper_body_can_be_targeted_over_low_cover(self):
        controller = combat.Combat(CONFIG, low_wall_clear)
        obs = observation(weapon("gun"))
        action = controller.plan(obs, enemy())
        self.assertGreater(action["aim"][1], 0.0)
        self.assertTrue(action["fire"][0])

    def test_gun_waits_for_actual_ray_to_clear_low_wall(self):
        controller = combat.Combat(CONFIG, low_wall_clear)
        obs = observation(weapon("gun"))
        obs["self"]["aim"] = [0, -0.2]
        action = controller.plan(obs, enemy())
        self.assertGreater(action["aim"][1], 0)
        self.assertFalse(action["fire"][0])
        obs["self"]["aim"] = controller._slewed(
            obs["self"]["aim"], action["aim"], obs["self"]["stats"], 0.1)
        obs["t"] += 0.1
        self.assertTrue(controller.plan(obs, enemy())["fire"][0])

    def test_gun_ready_in_second_frame_uses_that_frames_clear_ray(self):
        controller = combat.Combat(CONFIG, low_wall_clear)
        obs = observation(weapon("gun", cooldown=0.09))
        obs["self"]["aim"] = [0, -0.2]
        # Frame one is obstructed, but the gun cannot fire until frame two.
        self.assertTrue(controller.plan(obs, enemy())["fire"][0])

    def test_laser_holds_until_actual_ray_clears_low_wall(self):
        controller = combat.Combat(CONFIG, low_wall_clear)
        obs = observation(weapon("laser", charge=0.75))
        obs["self"]["aim"] = [0, -0.2]
        action = controller.plan(obs, enemy())
        self.assertTrue(action["fire"][0])
        obs["self"]["aim"] = controller._slewed(
            obs["self"]["aim"], action["aim"], obs["self"]["stats"], 0.1)
        obs["t"] += 0.1
        self.assertFalse(controller.plan(obs, enemy())["fire"][0])

    def test_gun_validates_every_launch_in_held_action(self):
        target = enemy(100, 0, [0, 20, 0])
        obs = observation(weapon("gun"), weapon("laser", charge=0.75))
        obs["self"]["stats"]["turn_rate"] = 0.8
        obs["self"]["aim"] = [0.12, -0.025]
        # The laser owns aim. On frame one the slewing torso still leads the
        # target enough for the gun; on frame two it no longer does.
        self.assertTrue(combat.Combat(CONFIG).plan(obs, target)["fire"][0])
        obs["self"]["weapons"][0]["stats"]["cooldown"] = 0.05
        self.assertFalse(combat.Combat(CONFIG).plan(obs, target)["fire"][0])

    def test_actual_ray_stops_at_near_target_surface(self):
        # A different body point from the commanded point must be checked only
        # until impact, not extended through the body into further geometry.
        controller = combat.Combat(CONFIG, lambda a, b: max(a[0], b[0]) < 99)
        solution = {"point": [100, 0, 4.5], "muzzle": [0, 0, 7],
                    "center_z": 4.5, "barrel_offset": 3.0, "clear": True}
        self.assertTrue(controller._actual_ray_clear([0.01, -0.025], solution, 2.5, 9))

    def test_laser_origin_matches_recorded_current_server_beam(self):
        # Recorded enemy beam: the firing frame precedes this observation by
        # one physics step. Cube-scaled muzzle height has no pitch extension.
        feet = [-28.88, 80.64, 41.03]
        velocity = [-2.74, 9.23, 6.7]
        start, end = [-24.32, 78.31, 53.29], [127.68, 14.2, 5.86]
        muzzle = [feet[i] - 0.05 * velocity[i] for i in range(3)]
        muzzle[2] += 7 * 1.8
        actual = combat.Combat._barrel_origin(muzzle, combat.point_aim(start, end), 5)
        self.assertLess(math.dist(actual, start), 0.02)

    def test_gun_origin_matches_recorded_current_server_projectile(self):
        feet, velocity = [-31.41, 88.96, 34.52], [0.23, 1.14, -16.3]
        projectile, projectile_velocity = [-30.05, 60.07, 40.53], [11.43, -240.61, -74.03]
        muzzle = [feet[i] - 0.05 * velocity[i] for i in range(3)]
        muzzle[2] += 7 * 1.8
        actual = combat.Combat._barrel_origin(muzzle, [-1.528, -0.311], 5)
        recorded = [projectile[i] - 0.1 * projectile_velocity[i] for i in range(3)]
        self.assertLess(math.dist(actual, recorded), 0.05)

    def test_high_angle_aim_reaches_target_from_horizontal_barrel(self):
        controller = combat.Combat(CONFIG)
        solution = controller._direct_solution("laser", CONFIG["weapons"]["laser"],
            [0, 0, 7], [12, 0, 14.5], [0, 0, 0], 3, (-0.7, 1.3), 9)
        self.assertIsNotNone(solution)
        pitch = solution["aim"][1]
        # Independent ray geometry of the observed server's launch position.
        barrel_x = 3 * math.cos(pitch)
        target_z = 7 + (12 - barrel_x) * math.tan(pitch)
        self.assertAlmostEqual(target_z, solution["point"][2], places=5)

    def test_moving_shooter_aims_from_firing_frame_position(self):
        for cooldown, delay in ((0, 0.05), (0.09, 0.1)):
            with self.subTest(cooldown=cooldown):
                obs = observation(weapon("gun", cooldown=cooldown))
                obs["self"]["vel"] = [0, 20, 0]
                action = combat.Combat(CONFIG).plan(obs, enemy(30))
                self.assertAlmostEqual(action["aim"][0], math.atan2(-20 * delay, 30), places=6)

    def test_shooter_velocity_changes_launch_origin_not_bullet_velocity(self):
        obs = observation(weapon("gun"))
        obs["self"]["vel"] = [0, 20, 0]
        target = enemy(150)
        action = combat.Combat(CONFIG).plan(obs, target)
        # No additional sideways correction for the projectile's ~0.6 s flight.
        self.assertAlmostEqual(action["aim"][0], math.atan2(-1, 150), places=6)

    def test_horizontal_barrel_cannot_cross_cover_below_clear_aim(self):
        def clear(a, b):
            if min(a[0], b[0]) <= 1 <= max(a[0], b[0]) and a[0] != b[0]:
                return a[2] + (b[2] - a[2]) * (1 - a[0]) / (b[0] - a[0]) > 8
            return True
        obs = observation(weapon("gun"))
        obs["self"]["aim"] = [0, 0.9]
        target = enemy(6)
        target["pos"][2] = 10
        self.assertFalse(combat.Combat(CONFIG, clear).plan(obs, target)["fire"][0])

    def test_recovery_releases_laser_and_reloads_gun(self):
        obs = observation(weapon("gun", ammo=6), weapon("laser", charge=0.5))
        action = combat.Combat(CONFIG).plan(obs, enemy(), allow_fire=False)
        self.assertEqual(action["fire"], [False, False])
        self.assertTrue(action["reload"])

    def test_low_health_retreat_can_fire_gun_without_new_laser_charge(self):
        obs = observation(weapon("gun"), weapon("laser"))
        obs["self"]["hp"] = 500
        action = combat.Combat(CONFIG).plan(obs, enemy(70), allow_fire=True, emergency=True)
        self.assertTrue(action["fire"][0])
        self.assertFalse(action["fire"][1])

    def test_quiet_recovery_suppresses_even_a_wounded_target(self):
        obs = observation(weapon("gun"))
        obs["self"]["hp"] = 500
        target = enemy(70)
        target["hp"] = 400
        action = combat.Combat(CONFIG).plan(obs, target, allow_fire=False, emergency=True)
        self.assertEqual(action["fire"], [False, False])

    def test_laser_charges_then_releases_at_full(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("laser"))
        self.assertTrue(controller.plan(obs, enemy())["fire"][0])
        obs["self"]["weapons"][0]["charge"] = 0.5
        self.assertTrue(controller.plan(obs, enemy())["fire"][0])
        obs["self"]["weapons"][0]["charge"] = 0.75
        self.assertFalse(controller.plan(obs, enemy())["fire"][0])

    def test_partial_laser_releases_when_lethal_to_npc(self):
        obs = observation(weapon("laser", charge=0.4))
        target = enemy()
        target.update(kind="npc", hp=200)
        self.assertFalse(combat.Combat(CONFIG).plan(obs, target)["fire"][0])

    def test_partial_laser_respects_unknown_enemy_armor(self):
        obs = observation(weapon("laser", charge=0.4))
        target = enemy()
        target["hp"] = 200
        self.assertTrue(combat.Combat(CONFIG).plan(obs, target)["fire"][0])
        target["armor"] = 0
        self.assertFalse(combat.Combat(CONFIG).plan(obs, target)["fire"][0])

    def test_early_laser_damage_applies_cube_scaling_once(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("laser", charge=0.4))
        obs["self"]["cubes"] = 10
        target = enemy()
        target["hp"] = 220
        bound = controller.laser_damage_bound(obs["self"], CONFIG["weapons"]["laser"], target, 0.4)
        self.assertAlmostEqual(bound, 315 * (0.35 + 0.65 * 0.4 / 0.75) * 1.4 * 0.76)
        self.assertFalse(controller.plan(obs, target)["fire"][0])

    def test_lethal_release_waits_for_clear_aligned_aim(self):
        obs = observation(weapon("laser", charge=0.4))
        target = enemy()
        target.update(kind="npc", hp=100)
        self.assertTrue(combat.Combat(CONFIG, lambda a, b: False).plan(obs, target)["fire"][0])
        obs["self"]["aim"] = [math.pi, 0]
        self.assertTrue(combat.Combat(CONFIG).plan(obs, target)["fire"][0])

    def test_lethal_laser_owns_shared_aim_before_full_charge(self):
        obs = observation(weapon("gun"), weapon("laser", charge=0.4))
        target = enemy(100, 0, [0, 15, 0])
        target.update(kind="npc", hp=200)
        action = combat.Combat(CONFIG).plan(obs, target)
        self.assertLess(action["aim"][0], 0.01)
        self.assertFalse(action["fire"][1])

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

    def test_lightning_cone_is_documented_deviation_from_aim(self):
        for degrees, expected in ((20, True), (29, True), (31, False)):
            with self.subTest(degrees=degrees):
                obs = observation(weapon("lightning"))
                obs["self"]["stats"]["turn_rate"] = 0
                obs["self"]["aim"][0] = math.radians(degrees)
                self.assertEqual(combat.Combat(CONFIG).plan(obs, enemy(30))["fire"][0], expected)

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

    def test_mortar_aim_commitment_survives_a_newly_ready_gun(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun", cooldown=0.2), weapon("mortar"))
        target = enemy(150)
        initial = controller.plan(obs, target)
        self.assertGreater(initial["aim"][1], 0.25)
        obs["t"] += 0.1
        obs["self"]["aim"] = initial["aim"]
        obs["self"]["weapons"][0]["cooldown"] = 0
        committed = controller.plan(obs, target)
        self.assertTrue(committed["fire"][1])
        self.assertFalse(committed["fire"][0])
        obs["t"] += 0.1
        obs["self"]["weapons"][1]["cooldown"] = 2.5
        after_shot = controller.plan(obs, target)
        self.assertLess(after_shot["aim"][1], 0)
        self.assertFalse(after_shot["fire"][1])

    def test_mortar_commitment_expires_and_yields_to_gun(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun", cooldown=0.2), weapon("mortar"))
        target = enemy(150)
        controller.plan(obs, target)
        obs["t"] += 0.31
        obs["self"]["weapons"][0]["cooldown"] = 0
        action = controller.plan(obs, target)
        self.assertLess(action["aim"][1], 0)
        self.assertFalse(action["fire"][1])

    def test_recovery_preempts_mortar_commitment(self):
        for kwargs in ({"emergency": True}, {"allow_fire": False}):
            controller = combat.Combat(CONFIG)
            obs = observation(weapon("gun", cooldown=0.2), weapon("mortar"))
            target = enemy(150)
            controller.plan(obs, target)
            obs["t"] += 0.1
            obs["self"]["weapons"][0]["cooldown"] = 0
            action = controller.plan(obs, target, **kwargs)
            self.assertFalse(action["fire"][1])
            self.assertIsNone(controller._mortar_slot)

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

