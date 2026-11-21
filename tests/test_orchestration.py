"""Actual Bot integration for proactive combat, economy and escape priorities.

Uses official observations/configuration and a flat arena to isolate decisions.
No combat outcome is simulated; real-map geometry/timing has separate checks.
"""
import copy
import math
import unittest
from unittest.mock import patch

import test_strategy as fixtures
from engagement import AggressiveEngagement


class OrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def attacked(self, actor_id, weapon="gun", amount=45):
        self.obs["events"] = [{"type": "damaged", "by": actor_id,
                               "weapon": weapon, "amount": amount, "bearing": 0}]

    def advance_frame(self, seconds):
        self.obs["t"] += seconds
        self.obs["tick"] = round(self.obs["t"] * 20)
        self.obs["beams"] = []
        self.obs["events"] = []

    def assert_no_trigger(self, action):
        self.assertFalse(self.bot.telemetry["allow_fire"])
        self.assertEqual(action["fire"], [False, False])

    def test_bot_explicitly_uses_aggressive_selector(self):
        self.assertIsInstance(self.bot.engagement, AggressiveEngagement)

    def test_first_attack_needs_no_damage_or_fight_evidence(self):
        self.obs["mechs"] = [self.enemy(100, hp=40)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "ATTACK")
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])
        self.assertEqual(self.bot.telemetry["engagement"]["authorized_ids"], [5])

    def test_healthy_target_is_usable_without_short_kill_estimate(self):
        self.obs["mechs"] = [self.enemy(100)]
        action = self.bot.act(self.obs)
        self.assertIsNone(self.bot.telemetry["engagement"]["finish_eta"])
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])

    def test_distant_current_enemy_is_approached_and_attacked(self):
        self.obs["mechs"] = [self.enemy(220)]
        action = self.bot.act(self.obs)
        self.assertGreater(self.bot.telemetry["goal"][0], 0)
        self.assertGreater(action["move"][0], 0)
        self.assertTrue(self.bot.telemetry["allow_fire"])

    def test_beyond_weapon_range_enemy_guides_pursuit_without_shot(self):
        self.obs["mechs"] = [self.enemy(300)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "PURSUE")
        self.assertIsNone(self.bot.telemetry["target"])
        self.assert_no_trigger(action)
        self.assertGreater(self.bot.telemetry["goal"][0], 0)

    def test_pursuit_does_not_bypass_failed_traversal(self):
        self.obs["mechs"] = [self.enemy(220)]
        with patch.object(self.bot.map, "navigate", return_value=(0, 0)), \
             patch.object(self.bot.map, "move_clear", return_value=False):
            action = self.bot.act(self.obs)
        self.assertEqual(action["move"], [0.0, 0.0])
        self.assertFalse(action["boost"])

    def test_productive_attack_does_not_expire_without_new_evidence(self):
        self.obs["mechs"] = [self.enemy(100)]
        first = self.bot.act(self.obs)
        self.advance_frame(10)
        later = self.bot.act(self.obs)
        self.assertTrue(first["fire"][0])
        self.assertTrue(later["fire"][0])
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertIsNone(self.bot.telemetry["engagement"]["finish_deadline"])

    def test_current_target_disappearance_does_not_fire_at_memory(self):
        self.obs["mechs"] = [self.enemy(100)]
        self.bot.act(self.obs)
        self.advance_frame(.1)
        self.obs["mechs"] = []
        action = self.bot.act(self.obs)
        self.assert_no_trigger(action)
        self.assertIsNone(self.bot.telemetry["target"])

    def test_missing_attacker_does_not_become_target(self):
        self.attacked(6)
        action = self.bot.act(self.obs)
        self.assert_no_trigger(action)
        self.assertIsNone(self.bot.telemetry["target"])

    def test_unrelated_weak_current_enemy_can_beat_recent_attacker(self):
        self.obs["mechs"] = [self.enemy(100, id=5, hp=20),
                              self.enemy(100, 30, id=6, hp=1400)]
        self.attacked(6)
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])

    def test_weaker_occluded_enemy_does_not_starve_usable_target(self):
        self.obs["mechs"] = [self.enemy(0, 100, id=5, hp=10), self.enemy(100, id=6)]
        with patch.object(self.bot.map, "line_of_fire", side_effect=lambda a, b: b[1] < 50):
            action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["target"], 6)
        self.assertTrue(action["fire"][0])

    def test_gun_selects_intervening_enemy_instead_of_shooting_through_it(self):
        self.obs["mechs"] = [self.enemy(100, id=6, hp=20), self.enemy(50, id=5)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])

    def test_lightning_selects_nearest_reachable_enemy(self):
        self.obs["self"]["weapons"] = [self.weapon("lightning"), None]
        self.obs["mechs"] = [self.enemy(40, id=6, hp=20), self.enemy(30, id=5)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])

    def test_lightning_can_chain_into_other_current_hostiles(self):
        self.obs["self"]["weapons"] = [self.weapon("gun"), self.weapon("lightning")]
        self.obs["mechs"] = [self.enemy(30, id=5, hp=500),
                              self.enemy(40, id=6, hp=1000), self.enemy(50, id=7, hp=1000)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.telemetry["engagement"]["authorized_ids"], [5, 6, 7])
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][1])

    def test_threatened_partial_magazine_remains_available(self):
        self.obs["self"]["weapons"][0]["ammo"] = 9
        self.obs["mechs"] = [self.enemy(100)]
        action = self.bot.act(self.obs)
        self.assertTrue(action["fire"][0])
        self.assertFalse(action["reload"])

    def test_quiet_without_enemy_tops_up_partial_magazine(self):
        self.obs["self"]["weapons"][0]["ammo"] = 9
        action = self.bot.act(self.obs)
        self.assert_no_trigger(action)
        self.assertTrue(action["reload"])

    def test_quiet_occluded_enemy_allows_partial_reload(self):
        self.obs["self"]["weapons"][0]["ammo"] = 9
        self.obs["mechs"] = [self.enemy(100)]
        with patch.object(self.bot.map, "line_of_fire", return_value=False):
            action = self.bot.act(self.obs)
        self.assert_no_trigger(action)
        self.assertTrue(action["reload"])

    def test_empty_magazine_reloads_during_exposure(self):
        self.obs["self"]["weapons"][0]["ammo"] = 0
        self.obs["mechs"] = [self.enemy(100)]
        action = self.bot.act(self.obs)
        self.assertTrue(action["reload"])
        self.assertFalse(action["fire"][0])

    def test_quiet_recovery_preserves_rounds_for_renewed_pressure(self):
        self.obs["self"]["hp"] = 500
        self.obs["self"]["weapons"][0]["ammo"] = 9
        self.obs["mechs"] = [self.enemy(100)]
        quiet = self.bot.act(self.obs)
        self.assert_no_trigger(quiet)
        self.assertFalse(quiet["reload"])
        self.advance_frame(.1)
        self.attacked(5)
        active = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "recover")
        self.assertTrue(active["fire"][0])
        self.assertFalse(active["reload"])

    def test_recovery_quiet_healing_suppresses_long_trade(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(100)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "RECOVER")
        self.assertEqual(self.bot.mode, "recover")
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assert_no_trigger(action)

    def test_recovery_allows_verified_short_kill_without_attribution(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(100, hp=20)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "recover")
        self.assertEqual(self.bot.telemetry["fire_reason"], "recovery_short_kill")
        self.assertTrue(action["fire"][0])

    def recovery_laser_setup(self):
        self.obs["self"]["hp"] = 500
        self.obs["self"]["weapons"] = [self.weapon("gun", ammo=0, reload=2.4),
                                          self.weapon("laser")]
        self.obs["mechs"] = [self.enemy(100, hp=150)]

    def test_grounded_recovery_starts_laser_supporting_verified_short_kill(self):
        self.recovery_laser_setup()
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "RECOVER")
        self.assertEqual(self.bot.mode, "recover", "Charge permission must not switch to pursuit")
        self.assertEqual(self.bot.telemetry["engagement"]["finish_weapon"], "laser")
        self.assertLessEqual(self.bot.telemetry["engagement"]["finish_eta"], 1.25)
        self.assertTrue(self.bot.telemetry["permit_short_charge"])
        self.assertTrue(action["fire"][1])
        self.assertFalse(action["fire"][0], "The empty reloading gun is not the modeled finisher")

    def test_urgent_recovery_vetoes_even_verified_short_laser_charge(self):
        self.recovery_laser_setup()
        self.obs["self"]["in_zone"] = False
        self.obs["zone"].update(center=[100, 0], radius=60,
                                next_center=[100, 0], next_radius=50)
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "ROTATE")
        self.assertTrue(self.bot.recover)
        self.assertEqual(self.bot.telemetry["engagement"]["finish_weapon"], "laser")
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertFalse(self.bot.telemetry["permit_short_charge"])
        self.assertFalse(action["fire"][1])

    def test_airborne_recovery_vetoes_verified_short_laser_charge(self):
        self.recovery_laser_setup()
        self.obs["self"].update(grounded=False, pos=[0, 0, 3], vel=[0, 0, -2])
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "RECOVER")
        self.assertEqual(self.bot.telemetry["engagement"]["finish_weapon"], "laser")
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertFalse(self.bot.telemetry["permit_short_charge"])
        self.assertFalse(action["fire"][1])

    def test_gun_only_short_kill_does_not_enable_nonlethal_ready_laser(self):
        # Six legitimate upgrades at 21 cubes make the gun burst stronger than
        # one unupgraded beam. A generic short ETA must not license that beam.
        gun, laser = self.weapon("gun"), self.weapon("laser")
        upgrade_ids = ["gun_damage"] * 3 + ["gun_rate"] * 3
        for upgrade_id in upgrade_ids:
            upgrade = next(u for u in self.hello["config"]["upgrades"] if u["id"] == upgrade_id)
            for effect in upgrade["effects"]:
                gun["stats"][effect["path"].split(".")[-1]] *= effect["mul"]
        me = self.obs["self"]
        me.update(hp=500, max_hp=1960, cubes=21, upgrades=upgrade_ids, weapons=[gun, laser])
        size = 1 + self.hello["config"]["cubes"]["size_per_cube"] * 21
        for key in ("muzzle_height", "eye_height"):
            me["stats"][key] = self.hello["config"]["mech"][key] * size
        me["aim"] = [0, math.atan2(4.5 - me["stats"]["muzzle_height"], 40)]
        self.obs["mechs"] = [self.enemy(40, hp=350)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "RECOVER")
        self.assertEqual(self.bot.telemetry["engagement"]["finish_weapon"], "gun")
        self.assertLessEqual(self.bot.telemetry["engagement"]["finish_eta"], 1.25)
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertFalse(self.bot.telemetry["permit_short_charge"])
        self.assertTrue(action["fire"][0])
        self.assertFalse(action["fire"][1])

    def test_critical_hp_does_not_take_discretionary_short_kill(self):
        self.obs["self"]["hp"] = 180
        self.obs["mechs"] = [self.enemy(100, hp=20)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "RECOVER")
        self.assert_no_trigger(action)

    def test_declined_critical_hp_kill_does_not_suppress_healing_cube(self):
        self.obs["self"]["hp"] = 180
        self.obs["mechs"] = [self.enemy(100, hp=20)]
        self.obs["cubes"] = [{"id": 5001, "pos": [-10, 0, 0]}]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "RECOVER")
        self.assert_no_trigger(action)
        self.assertLess(self.bot.telemetry["engagement"]["finish_eta"], 1.25)
        self.assertEqual(self.bot.resource_key, ("cubes", 5001))
        self.assertEqual(self.bot.mode, "loot")
        self.assertEqual(self.bot.telemetry["goal"], [-10, 0, 0])

    def test_recovery_immediate_threat_allows_fire_without_prior_hit(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(25)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, "recover")
        self.assertTrue(action["fire"][0])

    def test_recovery_pressure_expires_back_to_quiet_healing(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(100)]
        self.attacked(5)
        self.assertTrue(self.bot.act(self.obs)["fire"][0])
        self.advance_frame(3.1)
        self.assert_no_trigger(self.bot.act(self.obs))

    def test_quiet_recovery_release_preserves_existing_laser_aim(self):
        self.obs["self"].update(hp=500, aim=[.2, .1])
        self.obs["self"]["weapons"] = [self.weapon("gun"), self.weapon("laser", charge=.75)]
        self.obs["mechs"] = [self.enemy(100), self.enemy(0, 100, id=6)]
        action = self.bot.act(self.obs)
        self.assert_no_trigger(action)
        # False trigger releases a held charge; it does not cancel emission.
        self.assertEqual(action["aim"], self.obs["self"]["aim"])

    def test_target_loss_release_preserves_existing_laser_aim(self):
        self.obs["self"]["aim"] = [.2, .1]
        self.obs["self"]["weapons"] = [self.weapon("gun"), self.weapon("laser", charge=.75)]
        self.obs["sounds"] = [{"kind": "gun", "bearing": 1.5, "dist": "near", "age": .1}]
        action = self.bot.act(self.obs)
        self.assert_no_trigger(action)
        self.assertEqual(action["aim"], self.obs["self"]["aim"])

    def test_rotation_moves_to_zone_while_firing_at_enemy_opposite_it(self):
        self.obs["self"]["in_zone"] = False
        self.obs["self"]["aim"] = [math.pi, 0]
        self.obs["zone"].update(center=[100, 0], radius=60,
                                next_center=[100, 0], next_radius=50)
        self.obs["mechs"] = [self.enemy(-100)]
        self.obs["cubes"] = [{"id": 5001, "pos": [-10, 0, 0]}]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "ROTATE")
        self.assertEqual(self.bot.mode, "rotate")
        self.assertGreater(self.bot.telemetry["goal"][0], 0)
        self.assertIsNone(self.bot.resource_key)
        self.assertTrue(action["fire"][0])

    def test_urgent_rotation_does_not_start_laser_slowdown(self):
        self.obs["self"]["in_zone"] = False
        self.obs["self"]["weapons"] = [self.weapon("gun"), self.weapon("laser")]
        self.obs["zone"].update(center=[100, 0], radius=60,
                                next_center=[100, 0], next_radius=50)
        self.obs["mechs"] = [self.enemy(100)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "ROTATE")
        self.assertFalse(action["fire"][1])

    def test_safe_crate_farming_still_works(self):
        self.obs["crates"] = [{"id": 1001, "pos": [35, 0, 0], "hp": 300}]
        self.obs["self"]["aim"] = [0, math.atan2(1.2 - 7, 35)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "FARM")
        self.assertEqual(self.bot.resource_key, ("crates", 1001))
        self.assertEqual(self.bot.telemetry["target"], 1001)
        self.assertEqual(self.bot.telemetry["fire_reason"], "safe_farming")
        self.assertTrue(action["fire"][0])

    def test_safe_npc_farming_still_works(self):
        self.obs["mechs"] = [self.enemy(40, id=102, kind="npc", hp=350,
                                        max_hp=350, weapons=[])]
        self.obs["self"]["aim"] = [0, math.atan2(1.75 - 7, 40)]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.resource_key, ("npc", 102))
        self.assertEqual(self.bot.telemetry["target"], 102)
        self.assertTrue(action["fire"][0])

    def test_close_mech_combat_preempts_crate_farming(self):
        self.obs["crates"] = [{"id": 1001, "pos": [35, 20, 0], "hp": 300}]
        self.obs["mechs"] = [self.enemy(50)]
        action = self.bot.act(self.obs)
        self.assertIsNone(self.bot.resource_key)
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])

    def test_distant_mech_does_not_starve_safe_crate_farming(self):
        self.obs["crates"] = [{"id": 1001, "pos": [20, 20, 0], "hp": 300}]
        self.obs["mechs"] = [self.enemy(220)]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.resource_key, ("crates", 1001))
        self.assertEqual(self.bot.telemetry["target"], 1001)
        self.assertEqual(self.bot.state, "FARM")
        self.assertTrue(self.bot.telemetry["allow_fire"])

    def test_loose_cube_detour_coexists_with_distant_target_fire(self):
        self.obs["mechs"] = [self.enemy(180)]
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 10, 0]}]
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.resource_key, ("cubes", 5001))
        self.assertEqual(self.bot.mode, "loot")
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertGreater(self.bot.telemetry["goal"][1], 0)
        self.assertTrue(action["fire"][0])

    def test_short_kill_preempts_loose_cube_detour(self):
        self.obs["mechs"] = [self.enemy(100, hp=20)]
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 10, 0]}]
        action = self.bot.act(self.obs)
        self.assertIsNone(self.bot.resource_key)
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])

    def test_npc_defense_remains_available_during_recovery(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(40, id=102, kind="npc", hp=350,
                                        max_hp=350, weapons=[])]
        self.obs["self"]["aim"] = [0, math.atan2(1.75 - 7, 40)]
        self.attacked(102, weapon="npc", amount=25)
        action = self.bot.act(self.obs)
        self.assertEqual(self.bot.state, "RECOVER")
        self.assertEqual(self.bot.telemetry["target"], 102)
        self.assertTrue(action["fire"][0])

    def test_quiet_npc_does_not_interrupt_recovery_to_farm(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(20, id=102, kind="npc", hp=350,
                                        max_hp=350, weapons=[])]
        self.assert_no_trigger(self.bot.act(self.obs))

    def test_low_energy_approach_does_not_boost(self):
        self.obs["self"]["energy"] = 30
        self.obs["mechs"] = [self.enemy(220)]
        action = self.bot.act(self.obs)
        self.assertGreater(self.bot.telemetry["goal"][0], 0)
        self.assertFalse(action["boost"])

    def test_low_energy_lightning_retains_weapon_reserve(self):
        self.obs["self"]["energy"] = 10
        self.obs["self"]["weapons"] = [self.weapon("gun"), self.weapon("lightning")]
        self.obs["mechs"] = [self.enemy(30)]
        action = self.bot.act(self.obs)
        self.assertFalse(action["fire"][1])
        self.assertFalse(action["boost"])

    def test_orchestration_does_not_mutate_observation(self):
        self.obs["mechs"] = [self.enemy(100, hp=40), self.enemy(100, 20, id=6)]
        self.obs["cubes"] = [{"id": 5001, "pos": [0, 10, 0]}]
        before = copy.deepcopy(self.obs)
        action = self.bot.act(self.obs)
        self.assertEqual(self.obs, before)
        self.assertEqual(action["tick"], before["tick"])


if __name__ == "__main__":
    unittest.main()
