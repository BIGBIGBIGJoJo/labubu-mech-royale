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

    def test_weapon_launch_origins_move_at_the_first_eligible_tick(self):
        for kind in ("gun", "laser", "lightning", "mortar"):
            for cooldown, delay in ((0, 0.05), (0.09, 0.1)):
                with self.subTest(kind=kind, cooldown=cooldown):
                    controller = combat.Combat(CONFIG)
                    obs = observation(weapon(kind, cooldown=cooldown))
                    obs["self"]["vel"] = [10, -8, 6]
                    captured = {}
                    if kind == "mortar":
                        original = controller._mortar_solution
                        def solve(*args):
                            captured.update(origin=args[1], velocity=args[3])
                            return original(*args)
                        controller._mortar_solution = solve
                    else:
                        original = controller._direct_solution
                        def solve(*args):
                            captured.update(origin=args[2], velocity=args[4])
                            return original(*args)
                        controller._direct_solution = solve
                    controller.plan(obs, enemy(120, 0, [0, 12, 0]))
                    self.assertAlmostEqual(captured["origin"][0], 10 * delay)
                    self.assertAlmostEqual(captured["origin"][1], -8 * delay)
                    self.assertAlmostEqual(captured["origin"][2], 9.5 if kind == "mortar" else 7.0)
                    # Projectiles do not inherit shooter velocity.
                    self.assertEqual(captured["velocity"], [0, 12, 0])

    def test_charged_laser_release_uses_next_tick_origin(self):
        obs = observation(weapon("laser", charge=0.75, cooldown=0.09))
        obs["self"]["vel"] = [0, 10, 0]
        action = combat.Combat(CONFIG).plan(obs, enemy(100))
        self.assertAlmostEqual(action["aim"][0], math.atan2(-0.5, 100), places=7)
        self.assertFalse(action["fire"][0])

    def test_actual_ray_starts_at_predicted_launch_position(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun", cooldown=0.09))
        obs["self"]["vel"] = [0, 10, 0]
        captured = []
        original = controller._actual_ray_clear
        def actual_ray(*args):
            captured.append(list(args[0]))
            return original(*args)
        controller._actual_ray_clear = actual_ray
        self.assertTrue(controller.plan(obs, enemy(100))["fire"][0])
        self.assertEqual(captured, [[0, 1, 7]])

    def test_launch_motion_does_not_extrapolate_through_blocked_segment(self):
        def clear(a, b):
            return not (a == [0, 0, 7] and b == [0, 1, 7])
        controller = combat.Combat(CONFIG, clear)
        obs = observation(weapon("gun", cooldown=0.09))
        obs["self"]["vel"] = [0, 10, 0]
        action = controller.plan(obs, enemy())
        self.assertAlmostEqual(action["aim"][0], 0)
        self.assertTrue(action["fire"][0])

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
        def clear(a, b):
            if min(a[0], b[0]) <= 50 <= max(a[0], b[0]) and a[0] != b[0]:
                return a[2] + (b[2] - a[2]) * (50 - a[0]) / (b[0] - a[0]) > 7.4
            return True
        controller = combat.Combat(CONFIG, clear)
        obs = observation(weapon("gun"))
        action = controller.plan(obs, enemy())
        self.assertGreater(action["aim"][1], 0.0)
        self.assertTrue(action["fire"][0])

    def test_laser_holds_until_actual_ray_clears_low_wall(self):
        def clear(a, b):
            if min(a[0], b[0]) <= 5 <= max(a[0], b[0]) and a[0] != b[0]:
                return a[2] + (b[2] - a[2]) * (5 - a[0]) / (b[0] - a[0]) > 7.4
            return True
        controller = combat.Combat(CONFIG, clear)
        obs = observation(weapon("laser", charge=0.75))
        obs["self"]["aim"] = [0, math.atan2(4.5 - 7, 10)]
        initial = controller.plan(obs, enemy(10))
        self.assertTrue(initial["fire"][0])
        obs["self"]["aim"] = controller._slewed(obs["self"]["aim"], initial["aim"], obs["self"]["stats"], 0.1)
        obs["t"] += 0.1
        self.assertFalse(controller.plan(obs, enemy(10))["fire"][0])

    def test_gun_does_not_fire_actual_ray_into_low_wall(self):
        def clear(a, b):
            if min(a[0], b[0]) <= 5 <= max(a[0], b[0]) and a[0] != b[0]:
                return a[2] + (b[2] - a[2]) * (5 - a[0]) / (b[0] - a[0]) > 7.4
            return True
        obs = observation(weapon("gun"))
        obs["self"]["aim"] = [0, math.atan2(4.5 - 7, 10)]
        self.assertFalse(combat.Combat(CONFIG, clear).plan(obs, enemy(10))["fire"][0])

    def test_actual_ray_stops_at_target_before_wall_behind_it(self):
        controller = combat.Combat(CONFIG, lambda a, b: max(a[0], b[0]) < 101)
        self.assertTrue(controller.plan(observation(weapon("gun")), enemy(100))["fire"][0])
        self.assertFalse(controller.plan(observation(weapon("laser", charge=0.75)), enemy(100))["fire"][0])

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

    def test_lightning_cone_is_deviation_from_aim_not_full_width(self):
        for degrees, expected in ((20, True), (29, True), (31, False)):
            with self.subTest(degrees=degrees):
                obs = observation(weapon("lightning"))
                # Freeze yaw to test the cone boundary independently of slew.
                obs["self"]["stats"]["turn_rate"] = 0
                obs["self"]["aim"][0] = math.radians(degrees)
                action = combat.Combat(CONFIG).plan(obs, enemy(30))
                self.assertEqual(action["fire"][0], expected)

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

    def test_mortar_barrel_offset_intercept_matches_physical_trajectory(self):
        for cubes in (0, 8, 23):
            for distance, altitude, velocity in ((80, -5, [0, 0, 0]),
                                                 (150, 20, [0, 10, 2]),
                                                 (220, 0, [-3, 0, 0])):
                with self.subTest(cubes=cubes, distance=distance, altitude=altitude):
                    controller = combat.Combat(CONFIG)
                    me = observation(weapon("mortar"))["self"]
                    me["cubes"] = cubes
                    own = controller._self_stats(me)
                    base = [0, 0, own["height"] + 0.5]
                    center = [distance, 0, altitude + 4.5]
                    stats = CONFIG["weapons"]["mortar"]
                    sol = controller._mortar_solution(stats, base, center, velocity, me, own, [-0.7, 1.3])
                    self.assertIsNotNone(sol)
                    t = sol["flight"]
                    vec = combat.direction(sol["aim"])
                    endpoint = [sol["origin"][i] + stats["speed"] * vec[i] * t for i in range(3)]
                    endpoint[2] -= 0.5 * stats["gravity"] * t * t
                    expected = [center[i] + velocity[i] * t for i in range(3)]
                    self.assertLess(math.dist(endpoint, expected), 0.00001)
                    self.assertAlmostEqual(math.dist(sol["origin"], base), own["radius"] + 0.5)

    def test_mortar_grazing_maximum_range_root_is_not_missed(self):
        controller = combat.Combat(CONFIG)
        me = observation(weapon("mortar"))["self"]
        own = controller._self_stats(me)
        stats = CONFIG["weapons"]["mortar"]
        speed, gravity, offset = stats["speed"], stats["gravity"], own["radius"] + 0.5
        # At equal altitude, maximize (speed*t+offset)^2-(g*t^2/2)^2.
        # Its derivative vanishes at the double root of the intercept quartic.
        lo, hi = 0.0, stats["ttl"]
        for _ in range(70):
            t = (lo + hi) * 0.5
            if gravity * gravity * t ** 3 - 2 * speed * speed * t - 2 * speed * offset > 0:
                hi = t
            else:
                lo = t
        grazing_t = (lo + hi) * 0.5
        maximum = math.sqrt((speed * grazing_t + offset) ** 2 - (0.5 * gravity * grazing_t ** 2) ** 2)
        base = [0, 0, own["height"] + 0.5]
        sol = controller._mortar_solution(stats, base, [maximum, 0, base[2]], [0, 0, 0], me, own, [-0.7, 1.3])
        self.assertIsNotNone(sol)
        self.assertAlmostEqual(sol["flight"], grazing_t, places=5)
        near = controller._mortar_solution(stats, base, [maximum - 0.01, 0, base[2]], [0, 0, 0], me, own, [-0.7, 1.3])
        self.assertLess(near["flight"], grazing_t)
        self.assertIsNone(controller._mortar_solution(stats, base, [maximum + 0.01, 0, base[2]], [0, 0, 0], me, own, [-0.7, 1.3]))

    def test_mortar_checks_tube_to_barrel_segment(self):
        def clear(a, b):
            return not (a == [0, 0, 9.5] and 0 < math.dist(a, b) < 3.01)
        controller = combat.Combat(CONFIG, clear)
        self.assertFalse(controller.plan(observation(weapon("mortar")), enemy(150))["fire"][0])

    def test_mortar_checks_actual_slewing_arc_against_ceiling(self):
        target = enemy(150)
        initial = combat.Combat(CONFIG).plan(observation(weapon("mortar")), target)
        desired = initial["aim"]
        # A thin overhang at x=80 clears the intended arc by 25 cm, but the
        # still-slewing first-tick barrel points 0.011 rad higher and hits it.
        speed, gravity, offset = 72, 22, 3
        vec = combat.direction(desired)
        t = (80 - offset * vec[0]) / (speed * vec[0])
        ceiling = 9.5 + offset * vec[2] + speed * vec[2] * t - 0.5 * gravity * t * t + 0.25
        def clear(a, b):
            if min(a[0], b[0]) <= 80 <= max(a[0], b[0]) and a[0] != b[0]:
                return a[2] + (b[2] - a[2]) * (80 - a[0]) / (b[0] - a[0]) < ceiling
            return True
        aligned = observation(weapon("mortar"))
        aligned["self"]["aim"] = list(desired)
        self.assertTrue(combat.Combat(CONFIG, clear).plan(aligned, target)["fire"][0])
        slewing = copy.deepcopy(aligned)
        slewing["self"]["aim"][1] += CONFIG["mech"]["pitch_rate"] * 0.05 + 0.011
        self.assertFalse(combat.Combat(CONFIG, clear).plan(slewing, target)["fire"][0])

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

    def test_partial_magazine_can_be_retained_while_watching_a_threat(self):
        for target, allow_fire in ((None, True), (enemy(), False)):
            with self.subTest(target=target):
                obs = observation(weapon("gun", ammo=10))
                action = combat.Combat(CONFIG).plan(obs, target, allow_fire=allow_fire, quiet_reload=False)
                self.assertFalse(action["reload"])
                self.assertEqual(action["fire"], [False, False])

    def test_empty_gun_reloads_even_when_quiet_reload_is_suppressed(self):
        obs = observation(weapon("gun", ammo=0))
        self.assertTrue(combat.Combat(CONFIG).plan(obs, None, quiet_reload=False)["reload"])

    def test_optional_protected_mech_blocks_gun_interception(self):
        target = enemy(100)
        quiet = {**enemy(50), "id": 6}
        obs = observation(weapon("gun"))
        obs["mechs"] = [target, quiet]
        controller = combat.Combat(CONFIG)
        self.assertTrue(controller.plan(obs, target)["fire"][0])
        self.assertFalse(controller.plan(obs, target, protected_ids={6})["fire"][0])
        obs["mechs"][1]["pos"][1] = 15
        self.assertTrue(controller.plan(obs, target, protected_ids={6})["fire"][0])

    def test_gun_protection_includes_spread_corridor_and_motion(self):
        target = enemy(100)
        obs = observation(weapon("gun"))
        obs["mechs"] = [target, {**enemy(50, 4), "id": 6}]
        controller = combat.Combat(CONFIG)
        self.assertFalse(controller.plan(obs, target, protected_ids={6})["fire"][0])
        obs["mechs"][1].update(pos=[50, 8, 0], vel=[0, -25, 0])
        self.assertFalse(controller.plan(obs, target, protected_ids={6})["fire"][0])

    def test_protection_does_not_include_unobserved_mechs(self):
        target = enemy(100)
        obs = observation(weapon("gun"))
        obs["mechs"] = [target]
        self.assertTrue(combat.Combat(CONFIG).plan(obs, target, protected_ids={6})["fire"][0])

    def test_fresh_laser_charge_is_blocked_by_protected_interceptor(self):
        target = enemy(100)
        obs = observation(weapon("laser"))
        obs["mechs"] = [target, {**enemy(50), "id": 6}]
        self.assertFalse(combat.Combat(CONFIG).plan(obs, target, protected_ids={6})["fire"][0])

    def test_piercing_laser_protects_mech_behind_selected_target(self):
        target = enemy(50)
        obs = observation(weapon("laser"))
        obs["mechs"] = [target, {**enemy(100), "id": 6}]
        controller = combat.Combat(CONFIG)
        self.assertTrue(controller.plan(obs, target, protected_ids={6})["fire"][0])
        obs["self"]["weapons"][0]["stats"]["pierce"] = 1
        self.assertFalse(controller.plan(obs, target, protected_ids={6})["fire"][0])

    def test_existing_laser_charge_has_bounded_unavoidable_release(self):
        target = enemy(100)
        obs = observation(weapon("laser", charge=0.75))
        obs["mechs"] = [target, {**enemy(50), "id": 6}]
        controller = combat.Combat(CONFIG)
        self.assertTrue(controller.plan(obs, target, protected_ids={6})["fire"][0])
        obs["t"] += 0.4
        self.assertFalse(controller.plan(obs, target, protected_ids={6})["fire"][0])

    def test_lightning_blocks_quiet_primary_and_quiet_chain(self):
        for target_x, quiet_x, quiet_y in ((40, 30, 3), (30, 40, 0)):
            with self.subTest(target_x=target_x):
                target = enemy(target_x)
                obs = observation(weapon("lightning"))
                obs["mechs"] = [target, {**enemy(quiet_x, quiet_y), "id": 6}]
                self.assertFalse(combat.Combat(CONFIG).plan(obs, target, protected_ids={6})["fire"][0])

    def test_lightning_detects_observed_second_chain_through_npc(self):
        target = enemy(30)
        obs = observation(weapon("lightning"))
        obs["mechs"] = [target, {**enemy(55), "id": 6},
                        {**enemy(42), "id": 101, "kind": "npc"}]
        self.assertFalse(combat.Combat(CONFIG).plan(obs, target, protected_ids={6})["fire"][0])
        obs["mechs"].pop()
        self.assertTrue(combat.Combat(CONFIG).plan(obs, target, protected_ids={6})["fire"][0])

    def test_lightning_guard_does_not_suppress_safe_gun_slot(self):
        target = enemy(30)
        obs = observation(weapon("gun"), weapon("lightning"))
        obs["mechs"] = [target, {**enemy(40, 8), "id": 6}]
        action = combat.Combat(CONFIG).plan(obs, target, protected_ids={6})
        self.assertTrue(action["fire"][0])
        self.assertFalse(action["fire"][1])

    def test_mortar_protects_nearby_mech_from_splash(self):
        target = enemy(150)
        obs = observation(weapon("mortar"))
        controller = combat.Combat(CONFIG)
        obs["self"]["aim"] = controller.plan(obs, target)["aim"]
        obs["mechs"] = [target, {**enemy(150, 9), "id": 6}]
        self.assertFalse(controller.plan(obs, target, protected_ids={6})["fire"][0])
        obs["mechs"][1]["pos"][1] = 30
        self.assertTrue(controller.plan(obs, target, protected_ids={6})["fire"][0])


if __name__ == "__main__":
    unittest.main()

