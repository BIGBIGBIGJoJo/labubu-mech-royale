"""Bounded current-resource movement while nearest combat intent is retained."""
import copy
import time
import unittest
from unittest.mock import patch

import test_strategy as fixtures


class ResourcePursuitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def prepare(self, item=None):
        self.obs["mechs"] = [self.enemy(150)]
        self.obs["cubes"] = [item or {"id": 5001, "pos": [8, 4, 0]}]

    def evaluate(self, deadline=None, urgent=False, records=None):
        self.bot.update(self.obs)
        stats = self.bot.stats(self.obs["self"])
        threats = self.bot.threats(self.obs, stats) if records is None else records
        target = self.bot.choose_target(self.obs, threats)
        return self.bot.pursuit_resource(self.obs, threats, stats, target, [20, 0, 0], urgent,
                                         deadline if deadline is not None else time.perf_counter() + 1)

    def test_actual_bot_admits_near_cube_and_keeps_nearest_fire_target(self):
        self.prepare()
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "detour")
        self.assertEqual(self.bot.resource_key, ("cubes", 5001))
        self.assertEqual(self.bot.telemetry["pursuit_target"], 5)
        self.assertEqual(self.bot.telemetry["fire_target"], 5)
        self.assertTrue(action["fire"][0])
        self.assertFalse(self.bot.telemetry["allow_partial_reload"])
        self.assertLessEqual(self.bot.detour_report["trip_s"], 3)
        self.assertLessEqual(self.bot.detour_report["extra_s"], 2)

    def test_empty_second_slot_weapon_is_eligible(self):
        self.prepare()
        self.obs["cubes"] = []
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [8, 4, 0]}]
        self.assertIsNotNone(self.evaluate())
        self.assertEqual(self.bot.detour["key"], ("pickups", 8001))

    def test_duplicate_and_full_slot_weapon_do_not_create_detour(self):
        for kind, second in (("gun", None), ("laser", "lightning"), ("laser", "laser")):
            with self.subTest(kind=kind, second=second):
                self.setUp()
                self.prepare()
                self.obs["cubes"] = []
                self.obs["self"]["weapons"][1] = self.weapon(second) if second else None
                self.obs["pickups"] = [{"id": 8001, "kind": kind, "pos": [8, 4, 0]}]
                self.assertIsNone(self.evaluate())

    def test_two_same_kind_weapons_do_not_masquerade_as_an_empty_slot(self):
        self.prepare()
        self.obs["cubes"] = []
        self.obs["self"]["weapons"] = [self.weapon("gun"), self.weapon("gun")]
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [8, 4, 0]}]
        self.assertIsNone(self.evaluate())

    def test_unseen_memory_item_is_not_admitted(self):
        self.prepare()
        self.bot.loot[("cubes", 5002)] = ({"id": 5002, "pos": [10, 0, 0]}, 20)
        self.obs["cubes"] = []
        self.assertIsNone(self.evaluate())

    def test_in_reach_pickup_uses_existing_take_without_lease(self):
        self.prepare()
        self.obs["cubes"] = []
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [1, 0, 0]}]
        action = self.bot.act(self.obs)
        self.assertEqual(action["take"], 8001)
        self.assertIsNone(self.bot.detour)
        self.assertNotEqual(self.bot.mode, "detour")

    def test_observed_original_far_npc_drop_distance_is_not_claimed_brief(self):
        self.prepare({"id": 5001, "pos": [0, 64.02, 0]})
        with patch.object(self.bot.map, "move_clear") as sweep:
            self.assertIsNone(self.evaluate())
        sweep.assert_not_called()

    def test_held_unstarted_laser_uses_same_worst_case_speed_as_charge(self):
        self.prepare({"id": 5001, "pos": [0, 12, 0]})
        self.assertIsNotNone(self.evaluate())
        for charge in (0, .4):
            with self.subTest(charge=charge):
                self.setUp()
                self.prepare({"id": 5001, "pos": [0, 12, 0]})
                self.obs["self"]["weapons"][1] = self.weapon("laser", charge=charge)
                self.assertIsNone(self.evaluate())
                self.assertEqual(self.bot.detour_report["reason"], "route_eta_or_budget")

    def test_new_laser_return_penalty_begins_only_after_equip_distance(self):
        for excess in (-.1, .1):
            with self.subTest(excess=excess):
                self.setUp()
                self.prepare()
                self.obs["cubes"] = []
                stats = self.bot.stats(self.obs["self"])
                speed = stats["walk_speed"]
                equip = max(self.bot.config["loot"]["equip_s"], self.bot.config["weapons"]["laser"]["cooldown"])
                return_distance = speed * equip + excess
                endpoint_x = min(10, speed) - return_distance
                inset = max(0, self.bot.config["loot"]["pickup_radius"] - 2)
                self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [endpoint_x - inset, 0, 0]}]
                self.assertIsNotNone(self.evaluate())
                expected_return = min(return_distance / speed, equip) + max(0, excess) / (speed * stats["charge_move_mult"])
                self.assertAlmostEqual(self.bot.detour_report["trip_s"], abs(endpoint_x) / speed + expected_return)

    def test_current_unknown_exposure_rejects_detour(self):
        self.prepare()
        actor = self.obs["mechs"][0]
        record = {"actor": actor, "d": 150, "los": False, "los_known": False, "risk": 1}
        self.assertIsNone(self.evaluate(records=[record]))
        self.assertEqual(self.bot.detour_report["reason"], "unverified_exposure")

    def test_near_enemy_approach_uses_existing_exposure_rejection(self):
        self.prepare({"id": 5001, "pos": [15, 0, 0]})
        self.obs["mechs"] = [self.enemy(50)]
        self.assertIsNone(self.evaluate())

    def test_exposure_is_checked_at_pickup_endpoint_not_occluded_item_center(self):
        self.prepare()
        actor = self.enemy(55)
        actor["pos"][1] = 30
        actor["cubes"] = 20
        record = {"actor": actor, "d": fixtures.policy.distance([0, 0, 0], actor["pos"]),
                  "los": False, "los_known": True, "risk": 1}
        # The item centre has cover but the nearer point within pickup reach does not.
        with patch.object(self.bot.map, "line_of_fire", side_effect=lambda start, end: start[0] < 7):
            self.assertIsNone(self.evaluate(records=[record]))
        self.assertEqual(self.bot.detour_report["reason"], "no_eligible_item")

    def test_detour_does_not_newly_approach_inside_npc_aggro(self):
        self.prepare({"id": 5001, "pos": [20, 0, 0]})
        self.obs["mechs"] = [self.enemy(60, id=100, kind="npc", hp=350, max_hp=350)]
        self.assertIsNone(self.evaluate())

    def test_segment_interior_cannot_cross_npc_envelope_with_safe_endpoints(self):
        self.prepare({"id": 5001, "pos": [0, 15, 0]})
        actor = self.enemy(-47.5, id=100, kind="npc", hp=350, max_hp=350)
        actor["pos"][1] = 5
        self.obs["mechs"] = [actor]
        # Endpoints are outside even the grown 47.625m envelope, but the
        # collection segment enters it by .125m. The return moves away.
        self.assertIsNone(self.evaluate())

    def test_return_segment_cannot_cut_through_close_mech_envelope(self):
        self.prepare({"id": 5001, "pos": [0, 15, 0]})
        actor = self.enemy(44)
        actor["pos"][1] = 6
        record = {"actor": actor, "d": fixtures.policy.distance([0, 0, 0], actor["pos"]),
                  "los": False, "los_known": True, "risk": 1}
        # Hide endpoint exposure to isolate the cheap segment-distance guard.
        with patch.object(self.bot.map, "line_of_fire", return_value=False):
            self.assertIsNone(self.evaluate(records=[record]))

    def test_deadline_exhaustion_aborts_previous_valid_lease(self):
        self.prepare()
        self.assertIsNotNone(self.evaluate())
        self.obs.update(t=20.1, tick=402)
        with patch.object(self.bot.map, "move_clear") as sweep:
            self.assertIsNone(self.evaluate(deadline=time.perf_counter() - 1))
        self.assertIsNone(self.bot.detour)
        self.assertEqual(self.bot.detour_report["reason"], "budget")
        sweep.assert_not_called()

    def test_actual_bot_allocates_at_most_six_ms_to_optional_resource_work(self):
        self.prepare()
        with patch.object(fixtures.policy.time, "perf_counter", return_value=100.0):
            with patch.object(self.bot, "pursuit_resource", return_value=None) as resource:
                self.bot.act(self.obs)
        self.assertAlmostEqual(resource.call_args.args[-1], 100.006)

    def test_late_optional_entry_preserves_seventeen_ms_downstream_reserve(self):
        self.prepare()
        records = self.bot.threats(self.obs, self.bot.stats(self.obs["self"]))
        clock = [100.0]
        def delayed_threats(*args, **kwargs):
            clock[0] = 100.013
            return records
        with patch.object(fixtures.policy.time, "perf_counter", side_effect=lambda: clock[0]):
            with patch.object(self.bot, "threats", side_effect=delayed_threats):
                with patch.object(self.bot, "pursuit_resource", return_value=None) as resource:
                    self.bot.act(self.obs)
        cutoff = resource.call_args.args[-1]
        self.assertAlmostEqual(cutoff, 100.015)
        self.assertAlmostEqual(100.032 - cutoff, .017)

    def test_route_blockage_aborts_previous_valid_lease(self):
        self.prepare()
        self.assertIsNotNone(self.evaluate())
        self.obs.update(t=20.1, tick=402)
        with patch.object(self.bot.map, "move_clear", return_value=False):
            self.assertIsNone(self.evaluate())
        self.assertIsNone(self.bot.detour)
        self.assertEqual(self.bot.detour_report["status"], "aborted")

    def test_endpoint_blockage_and_vertical_inaccessibility_reject(self):
        self.prepare()
        with patch.object(self.bot.map, "point_clear", return_value=False):
            self.assertIsNone(self.evaluate())
        self.obs["cubes"][0]["pos"][2] = 5
        self.assertIsNone(self.evaluate())

    def test_fixed_expiry_does_not_extend_on_continuation(self):
        self.prepare()
        self.assertIsNotNone(self.evaluate())
        expiry = self.bot.detour["expires"]
        self.obs.update(t=20.2, tick=404)
        self.assertIsNotNone(self.evaluate())
        self.assertEqual(self.bot.detour["expires"], expiry)
        self.obs.update(t=23.1, tick=462)
        self.assertIsNone(self.evaluate())
        self.assertEqual(self.bot.detour_report["reason"], "expired")
        self.obs.update(t=23.2, tick=464)
        self.assertIsNone(self.evaluate())
        self.assertIsNone(self.bot.detour)

    def test_new_nearest_enemy_aborts_without_same_frame_reentry(self):
        self.prepare()
        self.assertIsNotNone(self.evaluate())
        self.obs.update(t=20.1, tick=402, mechs=[self.enemy(100, id=6), self.enemy(150, id=5)])
        self.assertIsNone(self.evaluate())
        self.assertEqual(self.bot.detour_report["reason"], "target_changed")
        self.assertIsNone(self.bot.detour)

    def test_actual_cube_acquisition_resumes_pursuit_and_prevents_chaining(self):
        self.prepare()
        self.bot.act(self.obs)
        self.assertIsNotNone(self.bot.detour)
        self.obs.update(t=20.1, tick=402)
        self.obs["self"]["cubes"] = 1
        self.obs["cubes"] = [{"id": 5002, "pos": [8, 4, 0]}]
        self.bot.act(self.obs)
        self.assertIsNone(self.bot.detour)
        self.assertEqual(self.bot.detour_report["status"], "completed")
        self.assertEqual(self.bot.mode, "engage")
        self.assertIsNone(self.bot.resource_key)
        self.obs.update(t=20.2, tick=404)
        self.bot.act(self.obs)
        self.assertIsNone(self.bot.detour)
        self.assertEqual(self.bot.detour_report["reason"], "pursuit_resume_window")

    def test_item_arrival_waits_within_fixed_lease_for_observed_pickup(self):
        self.prepare({"id": 5001, "pos": [10, 0, 0]})
        self.assertIsNotNone(self.evaluate())
        self.obs.update(t=20.5, tick=410)
        self.obs["self"]["pos"] = [7, 0, 0]
        self.assertIsNotNone(self.evaluate())
        self.assertEqual(self.bot.detour["expires"], 23)

    def test_weapon_acquisition_completes_lease(self):
        self.prepare()
        self.obs["cubes"] = []
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [8, 4, 0]}]
        self.assertIsNotNone(self.evaluate())
        self.obs.update(t=20.1, tick=402)
        self.obs["self"]["weapons"][1] = self.weapon("laser")
        self.assertIsNone(self.evaluate())
        self.assertEqual(self.bot.detour_report["status"], "completed")

    def test_missing_current_item_aborts_even_if_remembered(self):
        self.prepare()
        self.assertIsNotNone(self.evaluate())
        self.obs.update(t=20.1, tick=402, cubes=[])
        self.assertIsNone(self.evaluate())
        self.assertEqual(self.bot.detour_report["reason"], "item_absent_or_not_useful")

    def test_damage_low_hp_recovery_and_rotation_abort(self):
        for reason in ("damage", "lowhp", "recover", "urgent"):
            with self.subTest(reason=reason):
                self.setUp()
                self.prepare()
                self.assertIsNotNone(self.evaluate())
                self.obs.update(t=20.1, tick=402)
                if reason == "damage":
                    self.obs["events"] = [{"type": "damaged", "weapon": "gun", "amount": 45, "by": 5}]
                elif reason == "lowhp":
                    self.obs["self"]["hp"] = 700
                elif reason == "recover":
                    self.bot.recover = True
                self.assertIsNone(self.evaluate(urgent=reason == "urgent"))
                self.assertIsNone(self.bot.detour)

    def test_current_zone_completion_rejects_outside_resource(self):
        self.prepare({"id": 5001, "pos": [0, 20, 0]})
        self.obs["zone"].update(radius=25, next_radius=25)
        self.assertIsNone(self.evaluate())

    def test_future_zone_uses_laser_slowed_total_trip(self):
        self.prepare()
        self.obs["self"]["weapons"][1] = self.weapon("laser")
        # Uncharged centre ETA + margin is below five seconds; the conservative
        # full trip after a fresh laser charge crosses this shrink boundary.
        with patch.object(self.bot, "zone_future", side_effect=lambda obs, seconds: ([0, 0], 560 if seconds <= 5 else 12)) as future:
            self.assertIsNone(self.evaluate())
        self.assertTrue(any(call.args[1] > 5 for call in future.call_args_list))

    def test_future_zone_checks_return_anchor_even_when_endpoint_is_inside(self):
        self.prepare({"id": 5001, "pos": [-8, 0, 0]})
        with patch.object(self.bot, "zone_future", return_value=([-8, 0], 22)):
            self.assertIsNone(self.evaluate())

    def test_cluster_growth_requires_enlarged_endpoint_and_return_clearance(self):
        self.prepare()
        self.obs["cubes"] = [{"id": 5001, "pos": [8, 4, 0]}, {"id": 5002, "pos": [7.9, 4, 0]}]
        base = self.bot.stats(self.obs["self"])
        with patch.object(self.bot.map, "point_clear", side_effect=lambda p, radius, height: radius <= base["radius"] * 1.05):
            self.assertIsNone(self.evaluate())
        with patch.object(self.bot.map, "move_clear", return_value=True) as sweeps:
            self.assertIsNotNone(self.evaluate())
        self.assertEqual(sweeps.call_args_list[0].args[2:], (base["radius"], base["height"]))
        self.assertEqual(sweeps.call_args_list[1].args[2:], (base["radius"], base["height"]))
        self.assertAlmostEqual(sweeps.call_args_list[2].args[2], base["radius"] * 1.1)
        self.assertAlmostEqual(sweeps.call_args_list[2].args[3], base["height"] * 1.1)

    def test_weapon_cannot_bypass_growth_from_three_colocated_cubes(self):
        self.prepare()
        self.obs["cubes"] = [{"id": 5001 + i, "pos": [8, 4, 0]} for i in range(3)]
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [8, 4, 0]}]
        base = self.bot.stats(self.obs["self"])
        with patch.object(self.bot.map, "point_clear", side_effect=lambda p, r, h: r <= base["radius"] * 1.05) as points:
            self.assertIsNone(self.evaluate())
        self.assertEqual(points.call_count, 2)
        for call in points.call_args_list:
            self.assertAlmostEqual(call.args[1], base["radius"] * 1.15)

    def test_incidental_growth_uses_cube_radius_not_larger_weapon_take_radius(self):
        self.prepare()
        item = {"id": 8001, "kind": "laser", "pos": [8, 4, 0]}
        self.obs["pickups"] = [item]
        cube_reach = self.bot.config["cubes"]["pickup_radius"]
        take_reach = self.bot.config["loot"]["pickup_radius"]
        self.assertLess(cube_reach, take_reach)
        ux, uy = fixtures.policy.unit(-8, -4)
        endpoint = [8 + ux * (take_reach - 2), 4 + uy * (take_reach - 2), 0]
        between = (cube_reach + take_reach) / 2
        self.obs["cubes"] = [{"id": 5001, "pos": [endpoint[0], endpoint[1] + between, 0]}]
        base = self.bot.stats(self.obs["self"])
        with patch.object(self.bot.map, "point_clear", side_effect=lambda p, r, h: r <= base["radius"]):
            self.assertIsNotNone(self.evaluate())
        self.assertEqual(self.bot.detour["key"], ("pickups", 8001))

    def test_unavailable_map_and_airborne_self_do_not_admit(self):
        self.prepare()
        self.bot.map.available = False
        self.assertIsNone(self.evaluate())
        self.bot.map.available = True
        self.obs["self"]["grounded"] = False
        self.assertIsNone(self.evaluate())

    def test_capped_cube_requires_observable_upgrade_threshold(self):
        self.prepare()
        self.obs["self"]["cubes"] = 10
        self.assertIsNone(self.evaluate())
        self.obs["self"]["cubes"] = 14
        self.assertIsNotNone(self.evaluate())

    def test_at_most_two_candidates_get_optional_endpoint_checks(self):
        self.prepare()
        self.obs["cubes"] = [{"id": 5001 + i, "pos": [8 + i, 0, 0]} for i in range(3)]
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [9, 3, 0]}]
        with patch.object(self.bot.map, "point_clear", return_value=False) as points:
            self.assertIsNone(self.evaluate())
        self.assertEqual(points.call_count, 2)

    def test_cube_pile_cannot_hide_a_useful_second_weapon_from_shortlist(self):
        self.prepare()
        self.obs["cubes"] = [{"id": 5001 + i, "pos": [8, 0, 0]} for i in range(4)]
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [9, 3, 0]}]
        # Reject the cube endpoint but retain the weapon endpoint and anchor.
        with patch.object(self.bot.map, "point_clear", side_effect=lambda p, radius, height: p[1] > 0 or p[0] == 10):
            self.assertIsNotNone(self.evaluate())
        self.assertEqual(self.bot.detour["key"], ("pickups", 8001))

    def test_offset_pile_value_counts_only_cubes_collectible_at_endpoint(self):
        self.prepare({"id": 5001, "pos": [8, 0, 0]})
        self.obs["cubes"].extend({"id": 5002 + i, "pos": [11, 0, 0]} for i in range(4))
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [9, 3, 0]}]
        self.assertIsNotNone(self.evaluate())
        self.assertEqual(self.bot.detour["key"], ("pickups", 8001))

    def test_pickup_endpoint_accounts_for_existing_navigation_arrival_tolerance(self):
        self.prepare()
        candidate, endpoint = self.evaluate()
        self.assertLess(fixtures.policy.distance(endpoint, candidate[4]["pos"]) + 1.5,
                        self.bot.config["cubes"]["pickup_radius"])

    def test_dense_cube_cluster_work_is_linear_and_only_one_representative(self):
        self.prepare()
        self.obs["cubes"] = [{"id": 5001 + i, "pos": [8, 4, 0]} for i in range(256)]
        with patch.object(fixtures.policy, "distance", wraps=fixtures.policy.distance) as distances:
            with patch.object(self.bot.map, "point_clear", return_value=False) as points:
                self.assertIsNone(self.evaluate())
        self.assertLess(distances.call_count, 4 * 256 + 100)
        self.assertEqual(points.call_count, 1)

    def test_deadline_expiring_during_dense_scan_does_not_retain_old_lease(self):
        self.prepare()
        self.assertIsNotNone(self.evaluate())
        self.obs.update(t=20.1, tick=402)
        self.obs["cubes"].extend({"id": 5002 + i, "pos": [8, 4, 0]} for i in range(256))
        self.bot.update(self.obs)
        stats = self.bot.stats(self.obs["self"])
        threats = self.bot.threats(self.obs, stats)
        target = self.bot.choose_target(self.obs, threats)
        clock = iter([0.0] * 12 + [1.0] * 1000)
        with patch.object(fixtures.policy.time, "perf_counter", side_effect=lambda: next(clock)):
            self.assertIsNone(self.bot.pursuit_resource(self.obs, threats, stats, target, [20, 0, 0], False, .5))
        self.assertIsNone(self.bot.detour)
        self.assertEqual(self.bot.detour_report["reason"], "budget")

    def test_normal_no_target_healing_loot_is_not_delayed_by_detour_cooldown(self):
        self.obs["self"]["hp"] = 500
        self.obs["cubes"] = [{"id": 5001, "pos": [10, 0, 0]}]
        self.bot.detour_resume_until = 100
        self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(self.bot.resource_key, ("cubes", 5001))

    def test_observation_is_immutable(self):
        self.prepare()
        before = copy.deepcopy(self.obs)
        self.bot.act(self.obs)
        self.assertEqual(self.obs, before)


if __name__ == "__main__":
    unittest.main()
