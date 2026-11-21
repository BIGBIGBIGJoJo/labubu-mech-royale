"""Actual Bot arbitration for the user-approved nearest-hostile policy."""
import copy
import math
import unittest
from unittest.mock import patch

import test_strategy as fixtures


class PursuitOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def npc(self, x=100, y=0, **values):
        actor = self.enemy(x, y, kind="npc", id=102, hp=350, max_hp=350, weapons=[])
        actor.update(values)
        return actor

    def test_nearest_npc_beats_farther_mech_without_damage_history(self):
        self.obs["mechs"] = [self.npc(100), self.enemy(140, hp=20)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["pursuit_target"], 102)
        self.assertTrue(self.bot.telemetry["nearby_enemy"])

    def test_nearest_mech_beats_farther_wounded_npc(self):
        self.obs["mechs"] = [self.npc(100, hp=1), self.enemy(90)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["pursuit_target"], 5)

    def test_far_npc_is_pursued_beyond_old_discovery_and_gun_range(self):
        self.obs["mechs"] = [self.npc(300)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["pursuit_target"], 102)
        self.assertEqual(self.bot.mode, "pursue")
        self.assertFalse(self.bot.telemetry["nearby_enemy"])
        self.assertIsNone(self.bot.telemetry["fire_target"])
        self.assertGreater(action["move"][0], 0)

    def test_exact_tie_preserves_incumbent_then_actor_id(self):
        self.obs["mechs"] = [self.npc(100, id=102), self.enemy(100, id=6), self.enemy(100, id=5)]
        self.bot.target_id = 6
        self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, 6)
        self.bot.target_id = None
        self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, 5)

    def test_even_small_distance_advantage_beats_continuity(self):
        self.bot.target_id = 6
        self.obs["mechs"] = [self.enemy(100, id=6), self.npc(99.9)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, 102)

    def test_missing_optional_hp_remains_eligible_and_near(self):
        actor = self.enemy(90)
        actor.pop("hp")
        self.obs["mechs"] = [actor, self.npc(100)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, actor["id"])
        self.assertTrue(self.bot.telemetry["nearby_enemy"])

    def test_explicit_dead_and_our_observed_id_are_excluded(self):
        self.obs["self"]["id"] = 12
        self.obs["mechs"] = [self.enemy(10, id=12), self.enemy(20, id=5, hp=0), self.npc(100)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, 102)

    def test_disappeared_target_is_not_chased_from_memory(self):
        self.obs["mechs"] = [self.enemy(300)]
        self.bot.act(self.obs)
        self.obs.update(t=20.1, tick=402, mechs=[])
        self.bot.act(self.obs)
        self.assertIsNone(self.bot.telemetry["pursuit_target"])
        self.assertIsNone(self.bot.target_id)

    def test_confirmed_kill_overrides_current_and_later_retained_mech_listing(self):
        dead_listing = self.enemy(30, id=5)
        dead_listing.pop("hp")
        self.obs["mechs"] = [dead_listing, self.enemy(300, id=6)]
        self.obs["events"] = [{"type": "kill", "target": 5}]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, 6)
        self.assertFalse(self.bot.telemetry["nearby_enemy"])
        self.obs.update(t=20.1, tick=402, events=[])
        self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, 6)
        self.assertEqual(self.bot.eliminated_mechs, {5})

    def test_new_bot_match_does_not_inherit_eliminated_mechs(self):
        self.obs["mechs"] = [self.enemy(30, id=5)]
        self.obs["events"] = [{"type": "kill", "target": 5}]
        self.bot.act(self.obs)
        self.assertIsNone(self.bot.target_id)
        with patch.object(fixtures.policy, "ArenaMap", fixtures.FlatArena):
            other = fixtures.policy.Bot(copy.deepcopy(self.hello))
        self.obs["events"] = []
        other.act(self.obs)
        self.assertEqual(other.target_id, 5)

    def test_unconfirmed_npc_disappearance_does_not_mark_it_eliminated(self):
        self.obs["mechs"] = [self.npc(60)]
        self.bot.act(self.obs)
        self.obs.update(t=20.1, tick=402, mechs=[])
        self.bot.act(self.obs)
        self.obs.update(t=20.2, tick=404, mechs=[self.npc(60)])
        self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, 102)
        self.assertEqual(self.bot.eliminated_mechs, set())

    def test_low_hp_near_enemy_fights_without_prior_hit(self):
        self.obs["self"]["hp"] = 400
        self.obs["mechs"] = [self.enemy(100)]
        action = self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
        self.assertTrue(self.bot.recovery_needed)
        self.assertTrue(action["fire"][0])

    def test_low_hp_near_enemy_can_start_fresh_laser(self):
        self.obs["self"]["hp"] = 400
        self.obs["self"]["weapons"] = [self.weapon("gun"), self.weapon("laser")]
        self.obs["mechs"] = [self.enemy(100)]
        action = self.bot.act(self.obs)
        self.assertTrue(action["fire"][1])
        self.assertFalse(self.bot.recover)

    def test_low_hp_far_enemy_recovers_before_pursuit(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(300)]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(self.bot.mode, "recover")
        self.assertEqual(action["fire"], [False, False])
        self.assertIsNone(self.bot.resource_key)

    def test_healing_hysteresis_survives_nearby_combat_interruption(self):
        self.obs["self"]["hp"] = 500
        self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.obs.update(t=20.1, tick=402, mechs=[self.enemy(100)])
        self.obs["self"]["hp"] = 900
        self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
        self.assertTrue(self.bot.recovery_needed)
        self.obs.update(t=20.2, tick=404, mechs=[])
        self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.obs["self"]["hp"] = 1302
        self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
        self.assertFalse(self.bot.recovery_needed)

    def test_two_near_enemies_do_not_trigger_old_eighty_two_percent_healing(self):
        self.obs["self"]["hp"] = 1000
        self.obs["mechs"] = [self.enemy(90, id=5), self.enemy(100, id=6)]
        self.bot.act(self.obs)
        self.assertFalse(self.bot.recover)
        self.assertFalse(self.bot.recovery_needed)

    def test_low_hp_occluded_enemy_allows_quiet_healing(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(100)]
        with patch.object(self.bot.map, "line_of_fire", return_value=False):
            action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertFalse(self.bot.telemetry["nearby_enemy"])
        self.assertEqual(action["fire"], [False, False])

    def test_near_uses_live_weapon_range_instead_of_fixed_distance(self):
        self.obs["mechs"] = [self.enemy(120)]
        self.obs["self"]["weapons"][0]["stats"]["range"] = 100
        self.bot.act(self.obs)
        self.assertFalse(self.bot.telemetry["nearby_enemy"])
        self.obs["self"]["weapons"][1] = self.weapon("laser", cooldown=1.5)
        self.bot.act(self.obs)
        self.assertTrue(self.bot.telemetry["nearby_enemy"])

    def test_empty_reloading_gun_does_not_erase_near_enemy(self):
        self.obs["self"]["hp"] = 400
        self.obs["self"]["weapons"][0].update(ammo=0, reload=1.8, cooldown=.2)
        self.obs["mechs"] = [self.enemy(100)]
        self.bot.act(self.obs)
        self.assertTrue(self.bot.telemetry["nearby_enemy"])
        self.assertFalse(self.bot.recover)

    def test_near_enemy_blocks_partial_reload_in_unaligned_low_ammo_path(self):
        self.obs["self"]["weapons"][0]["ammo"] = 2
        self.obs["mechs"] = [self.enemy(50, id=5), self.enemy(80, id=6)]
        clear = lambda a, b: b[0] > 65
        with patch.object(self.bot.map, "line_of_fire", side_effect=clear), \
                patch.object(self.bot.combat, "line_of_fire", side_effect=clear):
            action = self.bot.act(self.obs)
        self.assertEqual(self.bot.target_id, 5)
        self.assertTrue(self.bot.telemetry["nearby_enemy"])
        self.assertFalse(action["reload"])
        self.assertEqual(action["fire"], [False, False])

    def test_no_near_enemy_allows_topup_during_far_pursuit(self):
        self.obs["self"]["weapons"][0]["ammo"] = 6
        self.obs["mechs"] = [self.enemy(300)]
        action = self.bot.act(self.obs)
        self.assertTrue(action["reload"])
        self.assertEqual(self.bot.telemetry["pursuit_target"], 5)
        self.assertIsNone(self.bot.telemetry["fire_target"])

    def test_no_near_enemy_allows_topup_when_occluded(self):
        self.obs["self"]["weapons"][0]["ammo"] = 6
        self.obs["mechs"] = [self.enemy(100)]
        with patch.object(self.bot.map, "line_of_fire", return_value=False):
            action = self.bot.act(self.obs)
        self.assertTrue(action["reload"])

    def test_occluded_close_target_is_approached_not_held_at_gun_band(self):
        self.obs["mechs"] = [self.enemy(50)]
        with patch.object(self.bot.map, "line_of_fire", return_value=False), \
                patch.object(self.bot.map, "navigate", wraps=self.bot.map.navigate) as navigate:
            self.bot.act(self.obs)
        self.assertGreater(navigate.call_args.args[1][0], 0)
        self.assertFalse(self.bot.telemetry["pursuit_los"])

    def test_empty_magazine_still_reloads_with_enemy_near(self):
        self.obs["self"]["weapons"][0]["ammo"] = 0
        self.obs["mechs"] = [self.enemy(100)]
        action = self.bot.act(self.obs)
        self.assertTrue(action["reload"])
        self.assertFalse(self.bot.telemetry["allow_partial_reload"])

    def test_resource_scoring_cannot_override_existing_pursuit(self):
        self.obs["mechs"] = [self.enemy(300)]
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 20, 0]}]
        with patch.object(self.bot, "resource_goal", side_effect=AssertionError("pursuit must win")):
            action = self.bot.act(self.obs)
        self.assertGreater(action["move"][0], 0)
        self.assertIsNone(self.bot.resource_key)

    def test_reachable_weapon_take_does_not_change_pursuit_goal(self):
        self.obs["mechs"] = [self.enemy(300)]
        self.obs["pickups"] = [{"id": 8001, "kind": "laser", "pos": [1, 0, 0]}]
        action = self.bot.act(self.obs)
        self.assertEqual(action["take"], 8001)
        self.assertGreater(action["move"][0], 0)
        self.assertEqual(self.bot.telemetry["pursuit_target"], 5)

    def test_urgent_zone_overrides_pursuit_but_near_fire_remains_allowed(self):
        self.obs["self"].update(pos=[90, 0, 0], hp=400, in_zone=False)
        self.obs["zone"].update(radius=100, next_radius=100)
        self.obs["mechs"] = [self.enemy(180)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "rotate")
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertTrue(action["fire"][0])
        self.assertFalse(self.bot.pursuit_boost)

    def test_held_laser_recovery_release_preserves_actual_aim(self):
        self.obs["self"].update(hp=500, aim=[1.2, .2])
        self.obs["self"]["weapons"] = [self.weapon("gun"), self.weapon("laser", charge=.4)]
        self.obs["mechs"] = [self.enemy(400)]
        self.obs["events"] = [{"type": "damaged", "amount": 10, "weapon": "gun", "by": 5, "bearing": -1.7}]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertEqual(action["fire"], [False, False])
        self.assertEqual(action["aim"], [1.2, .2])

    def test_far_pursuit_faces_target_instead_of_idle_scan(self):
        self.obs["self"]["aim"] = [0, 0]
        self.obs["mechs"] = [self.enemy(0, 300, id=5), self.enemy(-400, 0, id=6, charging=True)]
        action = self.bot.act(self.obs)
        self.assertAlmostEqual(action["aim"][0], math.pi / 2)

    def test_unverified_near_assessment_does_not_authorize_quiet_heal_or_topup(self):
        self.obs["self"]["hp"] = 500
        self.obs["self"]["weapons"][0]["ammo"] = 6
        self.obs["mechs"] = [self.enemy(100)]
        with patch.object(self.bot.combat, "geometrically_usable", return_value=None):
            action = self.bot.act(self.obs)
        self.assertTrue(self.bot.telemetry["nearby_enemy"])
        self.assertFalse(self.bot.telemetry["near_assessment_complete"])
        self.assertFalse(self.bot.recover)
        self.assertFalse(action["reload"])

    def test_twenty_seventh_actor_can_prevent_false_quiet_assessment(self):
        ids = [i for i in range(16) if i != self.obs["self"]["id"]]
        self.obs["mechs"] = [self.enemy(100 + i, id=actor_id) for i, actor_id in enumerate(ids)]
        self.obs["mechs"] += [self.npc(115 + i, id=100 + i) for i in range(12)]
        self.obs["self"]["hp"] = 500
        with patch.object(self.bot.map, "line_of_fire", side_effect=lambda a, b: b[0] > 125.5):
            self.bot.act(self.obs)
        self.assertTrue(self.bot.telemetry["nearby_enemy"])
        self.assertEqual(self.bot.telemetry["near_target"], 111)
        self.assertFalse(self.bot.recover)

    def test_observation_stays_unchanged(self):
        self.obs["mechs"] = [self.npc(80), self.enemy(100)]
        before = copy.deepcopy(self.obs)
        self.bot.act(self.obs)
        self.assertEqual(self.obs, before)

    def test_visibility_deadline_is_checked_before_upper_ray_and_keeps_all_actors(self):
        ids = [i for i in range(16) if i != self.obs["self"]["id"]]
        self.obs["mechs"] = [self.enemy(100 + i, id=actor_id) for i, actor_id in enumerate(ids)]
        self.obs["mechs"] += [self.npc(115 + i, id=100 + i) for i in range(12)]
        now = [10.0]
        def slow_blocked(start, end):
            now[0] += .007
            return False
        with patch.object(fixtures.policy.time, "perf_counter", side_effect=lambda: now[0]), \
                patch.object(self.bot.map, "line_of_fire", side_effect=slow_blocked) as rays:
            threats = self.bot.threats(self.obs, self.bot.stats(self.obs["self"]), deadline=10.006)
        self.assertEqual(rays.call_count, 1, "No top ray may start after center ray consumed the budget")
        self.assertEqual(len(threats), 27)
        self.assertTrue(all(not q["los_known"] for q in threats))
        self.assertEqual(self.bot.choose_target(self.obs, threats)["id"], ids[0])
        self.assertEqual(self.bot.last_threat_report["unknown"], 27)
        self.assertAlmostEqual(self.bot.last_threat_report["max_ray_ms"], 7)
        self.assertAlmostEqual(self.bot.last_threat_report["ms"], 7)

    def test_completed_center_ray_remains_known_when_it_crosses_deadline(self):
        self.obs["mechs"] = [self.enemy(100, id=5), self.enemy(110, id=6)]
        now = [10.0]
        def slow_clear(start, end):
            now[0] += .007
            return True
        with patch.object(fixtures.policy.time, "perf_counter", side_effect=lambda: now[0]), \
                patch.object(self.bot.map, "line_of_fire", side_effect=slow_clear):
            threats = self.bot.threats(self.obs, self.bot.stats(self.obs["self"]), deadline=10.006)
        self.assertTrue(threats[0]["los_known"])
        self.assertTrue(threats[0]["los"])
        self.assertFalse(threats[1]["los_known"])
        self.assertFalse(threats[1]["los"])

    def test_default_standalone_threats_still_checks_center_and_top(self):
        self.obs["mechs"] = [self.enemy(100), self.npc(110)]
        with patch.object(self.bot.map, "line_of_fire", return_value=False) as rays:
            threats = self.bot.threats(self.obs, self.bot.stats(self.obs["self"]))
        self.assertEqual(rays.call_count, 4)
        self.assertTrue(all(q["los_known"] and not q["los"] for q in threats))

    def test_unknown_visibility_retains_intrinsic_position_risk_without_double_scaling(self):
        actor = self.enemy(100)
        clear = {"actor": actor, "d": 100, "los": True, "los_known": True, "risk": 1.0}
        unknown = {**clear, "los": False, "los_known": False}
        known_blocked = {**clear, "los": False, "risk": .18}
        costs = [self.bot.position_cost([0, 0, 0], [q], [0, 0], 500, 2.5, recovering=True)
                 for q in (clear, unknown, known_blocked)]
        self.assertAlmostEqual(costs[0], costs[1])
        self.assertAlmostEqual(costs[0], costs[2])

    def run_slow_visibility_action(self, distance):
        self.obs["self"]["hp"] = 500
        self.obs["self"]["weapons"][0]["ammo"] = 6
        self.obs["mechs"] = [self.enemy(distance)]
        now, first = [10.0], [True]
        def slow_blocked(start, end):
            if first[0]:
                now[0] += .007
                first[0] = False
            return False
        with patch.object(fixtures.policy.time, "perf_counter", side_effect=lambda: now[0]), \
                patch.object(self.bot.map, "line_of_fire", side_effect=slow_blocked), \
                patch.object(self.bot.combat, "line_of_fire", side_effect=slow_blocked):
            return self.bot.act(self.obs)

    def test_actual_bot_unknown_in_range_visibility_blocks_quiet_actions(self):
        action = self.run_slow_visibility_action(100)
        self.assertTrue(self.bot.telemetry["nearby_enemy"])
        self.assertFalse(self.bot.telemetry["near_assessment_complete"])
        self.assertEqual(self.bot.telemetry["near_reason"], "visibility_unverified")
        self.assertFalse(self.bot.recover)
        self.assertFalse(action["reload"])
        self.assertFalse(self.bot.telemetry["pursuit_los"])
        self.assertEqual(action["fire"], [False, False], "Unknown LOS is not firing authorization")

    def test_actual_bot_definitely_far_unknown_actor_does_not_prevent_quiet_actions(self):
        action = self.run_slow_visibility_action(400)
        self.assertFalse(self.bot.telemetry["nearby_enemy"])
        self.assertTrue(self.bot.telemetry["near_assessment_complete"])
        self.assertTrue(self.bot.recover)
        self.assertTrue(action["reload"])
        self.assertEqual(self.bot.telemetry["visibility"]["unknown"], 1)

    def test_verified_near_actor_resolves_boolean_despite_earlier_unknown(self):
        actors = [self.enemy(100, id=5), self.enemy(120, id=6)]
        self.obs["mechs"] = actors
        records = [{"actor": a, "d": a["pos"][0], "risk": 1,
                    "los": i == 1, "los_known": i == 1} for i, a in enumerate(actors)]
        with patch.object(self.bot, "threats", return_value=records):
            self.bot.act(self.obs)
        self.assertTrue(self.bot.telemetry["nearby_enemy"])
        self.assertTrue(self.bot.telemetry["near_assessment_complete"])
        self.assertEqual(self.bot.telemetry["near_target"], 6)


if __name__ == "__main__":
    unittest.main()
