"""Pursuit firing/proximity contract against official recorded weapon stats."""
import copy
import math
import unittest
from unittest.mock import patch

from test_combat import CONFIG, combat, enemy, observation, weapon


class PursuitCombatTests(unittest.TestCase):
    def test_unknown_visibility_range_envelope_rejects_clearly_distant_actor(self):
        obs = observation(weapon("gun", ammo=0, reload=2.0))
        controller = combat.Combat(CONFIG)
        self.assertTrue(controller.range_envelope_possible(obs, enemy(100)))
        self.assertFalse(controller.range_envelope_possible(obs, enemy(240)))
        obs["self"]["weapons"][0]["stats"]["range"] = 300
        self.assertTrue(controller.range_envelope_possible(obs, enemy(240)))

    def test_range_envelope_keeps_body_edge_and_cube_allowance_conservative(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"))
        self.assertTrue(controller.range_envelope_possible(obs, enemy(235)))
        self.assertFalse(controller.geometrically_usable(obs, enemy(235), line_clear=True))
        target = enemy(237)
        self.assertFalse(controller.range_envelope_possible(obs, target))
        target["cubes"] = 20
        self.assertTrue(controller.range_envelope_possible(obs, target))

    def test_range_envelope_does_not_query_world_or_solve_mortar(self):
        controller = combat.Combat(CONFIG, line_of_fire=lambda *_: self.fail("No world work in range envelope"))
        controller._mortar_solution = lambda *_: self.fail("No mortar solve in range envelope")
        obs = observation(weapon("mortar", cooldown=2))
        before = copy.deepcopy(obs)
        self.assertTrue(controller.range_envelope_possible(obs, enemy(1000)))
        self.assertEqual(obs, before)

    def test_range_envelope_ignores_energy_and_pitch_for_unknown_visibility(self):
        obs = observation(weapon("lightning", cooldown=.2))
        obs["self"].update(energy=0, aim=[math.pi, 1.0])
        self.assertTrue(combat.Combat(CONFIG).range_envelope_possible(obs, {**enemy(30), "pos": [30, 0, 100]}))

    def test_range_envelope_without_target_or_weapon_is_false(self):
        controller = combat.Combat(CONFIG)
        self.assertFalse(controller.range_envelope_possible(observation(), enemy()))
        self.assertFalse(controller.range_envelope_possible(observation(weapon("gun")), None))

    def test_near_policy_preserves_partial_magazine_without_target(self):
        obs = observation(weapon("gun", ammo=6))
        action = combat.Combat(CONFIG).plan(obs, None, allow_partial_reload=False)
        self.assertFalse(action["reload"])
        self.assertEqual(action["fire"], [False, False])

    def test_near_policy_preserves_partial_magazine_when_fire_suppressed(self):
        obs = observation(weapon("gun", ammo=6))
        action = combat.Combat(CONFIG).plan(obs, enemy(), allow_fire=False, allow_partial_reload=False)
        self.assertFalse(action["reload"])

    def test_invalid_solution_cannot_trigger_partial_reload_near_enemy(self):
        for ammo in (1, 2, 3):
            with self.subTest(ammo=ammo):
                obs = observation(weapon("gun", ammo=ammo))
                controller = combat.Combat(CONFIG, line_of_fire=lambda *_: False)
                action = controller.plan(obs, enemy(), allow_partial_reload=False)
                self.assertFalse(action["reload"])
                self.assertFalse(any(action["fire"]))

    def test_empty_magazine_reloads_even_when_partial_reload_prohibited(self):
        for target, allowed in ((None, True), (enemy(), False), (enemy(), True)):
            with self.subTest(target=target, allowed=allowed):
                action = combat.Combat(CONFIG).plan(observation(weapon("gun", ammo=0)),
                    target, allow_fire=allowed, allow_partial_reload=False)
                self.assertTrue(action["reload"])
                self.assertFalse(action["fire"][0])

    def test_existing_reload_is_not_restarted(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun", ammo=0, reload=1.4)),
                                             None, allow_partial_reload=False)
        self.assertFalse(action["reload"])

    def test_default_preserves_idle_and_invalid_solution_topups(self):
        self.assertTrue(combat.Combat(CONFIG).plan(observation(weapon("gun", ammo=6)), None)["reload"])
        controller = combat.Combat(CONFIG, line_of_fire=lambda *_: False)
        self.assertTrue(controller.plan(observation(weapon("gun", ammo=3)), enemy())["reload"])

    def test_near_ignores_empty_reload_cooldown_energy_and_current_yaw(self):
        controller = combat.Combat(CONFIG)
        for held in (weapon("gun", ammo=0, reload=2.0), weapon("laser", cooldown=1.6),
                     weapon("lightning", cooldown=.2)):
            with self.subTest(kind=held["kind"]):
                obs = observation(held)
                obs["self"]["aim"] = [math.pi, 1.0]
                obs["self"]["energy"] = 0
                self.assertTrue(controller.geometrically_usable(obs, enemy(30)))

    def test_near_uses_live_weapon_range(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"))
        self.assertFalse(controller.geometrically_usable(obs, enemy(250)))
        obs["self"]["weapons"][0]["stats"]["range"] = 300
        self.assertTrue(controller.geometrically_usable(obs, enemy(250)))

    def test_near_respects_world_los_without_caller_proof(self):
        controller = combat.Combat(CONFIG, line_of_fire=lambda *_: False)
        obs = observation(weapon("gun"), weapon("laser"))
        self.assertFalse(controller.geometrically_usable(obs, enemy()))
        self.assertFalse(controller.geometrically_usable(obs, enemy(), line_clear=False))

    def test_known_actor_los_is_conservative_near_but_never_fire_permission(self):
        calls = []
        def blocked(*args):
            calls.append(args)
            return False
        controller = combat.Combat(CONFIG, line_of_fire=blocked)
        obs = observation(weapon("gun"))
        self.assertTrue(controller.geometrically_usable(obs, enemy(), line_clear=True))
        self.assertFalse(calls)
        action = controller.plan(obs, enemy(), allow_partial_reload=False)
        self.assertTrue(calls)
        self.assertFalse(any(action["fire"]))

    def test_large_self_small_npc_pitch_remains_unusable(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"))
        obs["self"]["cubes"] = 20
        obs["self"]["stats"].update(muzzle_height=14, eye_height=16)
        npc = {**enemy(2), "kind": "npc"}
        self.assertFalse(controller.geometrically_usable(obs, npc, line_clear=True))
        npc["pos"][0] = 35
        self.assertTrue(controller.geometrically_usable(obs, npc, line_clear=True))

    def test_lightning_near_does_not_require_pitch_to_low_npc(self):
        obs = observation(weapon("lightning"))
        obs["self"]["cubes"] = 20
        obs["self"]["stats"]["muzzle_height"] = 14
        self.assertTrue(combat.Combat(CONFIG).geometrically_usable(obs, {**enemy(5), "kind": "npc"}))

    def test_mortar_near_checks_arc_and_self_blast_even_with_actor_los(self):
        obs = observation(weapon("mortar"))
        controller = combat.Combat(CONFIG)
        self.assertTrue(controller.geometrically_usable(obs, enemy(100)))
        self.assertFalse(controller.geometrically_usable(obs, enemy(5)))
        blocked = combat.Combat(CONFIG, line_of_fire=lambda *_: False)
        self.assertFalse(blocked.geometrically_usable(obs, enemy(100), line_clear=True))

    def test_direct_weapon_shortcircuits_mortar_arc(self):
        controller = combat.Combat(CONFIG)
        def forbidden(*args):
            self.fail("Usable direct weapon should avoid mortar arc work")
        controller._mortar_solution = forbidden
        self.assertTrue(controller.geometrically_usable(
            observation(weapon("mortar"), weapon("gun")), enemy(100), line_clear=True))

    def test_expired_near_query_is_unknown_not_false_quiet(self):
        controller = combat.Combat(CONFIG)
        with patch.object(combat.time, "perf_counter", return_value=2):
            self.assertIsNone(controller.geometrically_usable(
                observation(weapon("gun")), enemy(100), line_clear=True, deadline=1))

    def test_mortar_arc_query_stops_at_shared_deadline(self):
        rays = []
        controller = combat.Combat(CONFIG, line_of_fire=lambda *args: rays.append(args) or True)
        # Initial query, before arc, first arc sample, second sample, return.
        with patch.object(combat.time, "perf_counter", side_effect=[0, 0, 0, 2, 2]):
            result = controller.geometrically_usable(
                observation(weapon("mortar")), enemy(100), line_clear=True, deadline=1)
        self.assertIsNone(result)
        self.assertEqual(len(rays), 1)

    def test_geometric_query_preserves_observation_and_combat_latches(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon("gun"), weapon("mortar"))
        target = enemy(100)
        original = copy.deepcopy((obs, target))
        controller._mortar_slot, controller._mortar_target, controller._mortar_until = 1, 7, 5.3
        controller._full_since = {0: 4.0}
        before = copy.deepcopy(controller.__dict__)
        controller.geometrically_usable(obs, target)
        self.assertEqual((obs, target), original)
        self.assertEqual(controller.__dict__, before)

    def test_both_gun_and_laser_available_during_pursuit(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun"), weapon("laser")),
                                             enemy(100), allow_partial_reload=False)
        self.assertEqual(action["fire"], [True, True])
        self.assertFalse(action["reload"])

    def test_both_gun_and_lightning_fire_with_compatible_aim(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun"), weapon("lightning")),
                                             enemy(30), allow_partial_reload=False)
        self.assertEqual(action["fire"], [True, True])

    def test_documented_lightning_yaw_deviation_not_halved(self):
        for degrees, expected in ((20, True), (29, True), (31, False)):
            with self.subTest(degrees=degrees):
                obs = observation(weapon("lightning"))
                # Its first eligible tick slews .2rad toward the command.
                obs["self"]["aim"] = [-math.radians(degrees) - .2, 0]
                action = combat.Combat(CONFIG).plan(obs, enemy(30))
                self.assertEqual(action["fire"][0], expected)

    def test_lightning_wider_cone_still_requires_energy_and_clear_path(self):
        obs = observation(weapon("lightning"))
        obs["self"]["aim"] = [-math.radians(20) - .2, 0]
        obs["self"]["energy"] = 10
        self.assertFalse(combat.Combat(CONFIG).plan(obs, enemy(30))["fire"][0])
        obs["self"]["energy"] = 100
        self.assertFalse(combat.Combat(CONFIG, line_of_fire=lambda *_: False).plan(obs, enemy(30))["fire"][0])

    def test_urgent_escape_does_not_start_new_charge(self):
        action = combat.Combat(CONFIG).plan(observation(weapon("gun"), weapon("laser")),
            enemy(100), emergency=True, allow_partial_reload=False)
        self.assertEqual(action["fire"], [True, False])


if __name__ == "__main__":
    unittest.main()
