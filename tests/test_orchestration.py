"""Integration checks for user-authorized farming, defense, and safe finishes.

Real Engagement evidence and Bot.act are used. A controlled safety assessment
isolates per-target authorization; geometry/safety has a separate test suite.
"""
import copy
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_strategy as fixtures


class OrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def assessment(self, allowed=(), budget=2.0):
        ids = set(allowed)
        return SimpleNamespace(
            allows=lambda actor: actor.get("kind") == "mech" and actor["id"] in ids,
            budget_s=budget if ids else 0.0,
            reasons=() if ids else ("test_safety_veto",))

    def act_with_safety(self, allowed=()):
        with patch.object(self.bot.finish_safety, "evaluate",
                          return_value=self.assessment(allowed)):
            return self.bot.act(self.obs)

    def attacked(self, actor_id, weapon="gun", amount=45):
        self.obs["events"] = [{"type": "damaged", "by": actor_id,
                               "weapon": weapon, "amount": amount, "bearing": 0}]

    def existing_fight(self):
        self.obs["mechs"] = [self.enemy(100, id=5, hp=40),
                              self.enemy(100, 20, id=6, hp=70)]
        # An attributed beam can be visible even when its shooter is not.
        self.obs["beams"] = [
            {"by": 9, "kind": "lightning", "age": .1,
             "path": [[130, 40, 7], [100, 0, 4.5]]},
            {"by": 9, "kind": "lightning", "age": .1,
             "path": [[130, 40, 7], [100, 20, 4.5]]},
        ]

    def assert_no_enemy_fire(self, action):
        self.assertFalse(self.bot.telemetry["allow_fire"])
        self.assertEqual(action["fire"], [False, False])
        self.assertIsNone(self.bot.telemetry["target"])

    def test_quiet_close_weak_mech_never_receives_first_shot(self):
        self.obs["mechs"] = [self.enemy(8, hp=20)]
        action = self.act_with_safety([5])
        self.assertEqual(self.bot.state, "OBSERVE")
        self.assert_no_enemy_fire(action)
        self.assertLessEqual(self.bot.telemetry["goal"][0], 0,
                             "Proximity cannot authorize an attack or approach")

    def test_quiet_distant_mech_is_not_chased(self):
        self.obs["mechs"] = [self.enemy(220, hp=30)]
        action = self.act_with_safety([5])
        self.assert_no_enemy_fire(action)
        self.assertLessEqual(self.bot.telemetry["goal"][0], 1e-8)

    def test_withdrawn_permission_releases_laser_without_retargeting_quiet_mech(self):
        # Releasing a held laser emits a beam; false triggers alone are not a
        # no-shot guarantee. Idle scanning must preserve the observed barrel.
        self.obs["self"]["weapons"] = [self.weapon("gun"),
                                          self.weapon("laser", charge=.75)]
        self.obs["self"]["aim"] = [0, -.05]
        self.obs["mechs"] = [self.enemy(80 * math.cos(.15),
                                        80 * math.sin(.15))]
        action = self.act_with_safety()
        self.assert_no_enemy_fire(action)
        self.assertEqual(action["aim"], self.obs["self"]["aim"])

    def test_first_shrink_does_not_unlock_arbitrary_offense(self):
        self.obs.update(t=120, tick=2400)
        self.obs["zone"].update(radius=200, next_radius=120,
                                shrink_start=150, shrink_end=190)
        self.obs["mechs"] = [self.enemy(80, hp=20)]
        self.assert_no_enemy_fire(self.act_with_safety([5]))

    def test_safe_opening_crate_farming_has_separate_permission(self):
        self.obs["crates"] = [{"id": 1001, "pos": [35, 0, 0], "hp": 300}]
        self.obs["self"]["aim"] = [0, math.atan2(1.2 - 7, 35)]
        action = self.act_with_safety()
        self.assertEqual(self.bot.state, "OBSERVE")
        self.assertEqual(self.bot.resource_key, ("crates", 1001))
        self.assertEqual(self.bot.telemetry["target"], 1001)
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertEqual(self.bot.telemetry["fire_reason"], "safe_farming")
        self.assertTrue(action["fire"][0])

    def test_safe_opening_npc_farming_is_allowed(self):
        self.obs["mechs"] = [self.enemy(40, id=102, kind="npc", hp=350,
                                        max_hp=350, weapons=[])]
        self.obs["self"]["aim"] = [0, math.atan2(1.75 - 7, 40)]
        action = self.act_with_safety()
        self.assertEqual(self.bot.resource_key, ("npc", 102))
        self.assertEqual(self.bot.telemetry["target"], 102)
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertEqual(self.bot.telemetry["fire_reason"], "safe_farming")
        self.assertTrue(action["fire"][0])

    def test_unsafe_farming_does_not_start_mech_combat(self):
        self.obs["crates"] = [{"id": 1001, "pos": [35, 0, 0], "hp": 300}]
        self.obs["mechs"] = [self.enemy(50)]
        self.assert_no_enemy_fire(self.act_with_safety())
        self.assertIsNone(self.bot.resource_key)

    def test_attributed_mech_defense_continues_during_recovery(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(100)]
        self.attacked(5)
        action = self.act_with_safety()
        self.assertEqual(self.bot.state, "RECOVER")
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertTrue(action["fire"][0])

    def test_attributed_defense_continues_during_zone_rotation(self):
        self.obs["self"]["in_zone"] = False
        self.obs["zone"].update(center=[100, 0], radius=60,
                                next_center=[100, 0], next_radius=50)
        self.obs["mechs"] = [self.enemy(80)]
        self.attacked(5)
        with patch.object(self.bot.finish_safety, "evaluate",
                          return_value=self.assessment()) as evaluate:
            action = self.bot.act(self.obs)
        self.assertTrue(evaluate.call_args.kwargs["urgent"])
        self.assertEqual(self.bot.state, "ROTATE")
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])

    def test_weaker_unrelated_mech_does_not_inherit_defense(self):
        self.obs["mechs"] = [self.enemy(0, 50, id=5, hp=10),
                              self.enemy(100, id=6, hp=1000)]
        self.attacked(6)
        action = self.act_with_safety([5, 6])
        self.assertEqual(self.bot.state, "DEFEND")
        self.assertEqual(self.bot.telemetry["target"], 6)
        self.assertTrue(action["fire"][0])

    def test_defensive_gun_does_not_fire_through_quiet_mech(self):
        self.obs["mechs"] = [self.enemy(100, id=6),
                              self.enemy(50, id=5)]
        self.attacked(6)
        action = self.act_with_safety()
        self.assertIn(self.bot.state, ("DEFEND", "OBSERVE"))
        self.assertIn(self.bot.telemetry["target"], (None, 6))
        if self.bot.telemetry["target"] is None:
            self.assertFalse(self.bot.telemetry["allow_fire"])
            self.assertEqual(action["fire"], [False, False])
        self.assertFalse(action["fire"][0],
                         "Target permission cannot authorize an intervening mech")

    def test_defensive_lightning_does_not_select_nearer_quiet_mech(self):
        self.obs["self"]["weapons"] = [self.weapon("gun"),
                                          self.weapon("lightning")]
        self.obs["mechs"] = [self.enemy(40, id=6),
                              self.enemy(30, 3, id=5)]
        self.attacked(6)
        action = self.act_with_safety()
        self.assertIn(self.bot.state, ("DEFEND", "OBSERVE"))
        self.assertIn(self.bot.telemetry["target"], (None, 6))
        if self.bot.telemetry["target"] is None:
            self.assertFalse(self.bot.telemetry["allow_fire"])
            self.assertEqual(action["fire"], [False, False])
        self.assertFalse(action["fire"][1],
                         "Lightning selects the nearest cone actor, not target_id")

    def test_defensive_lightning_does_not_chain_into_quiet_mech(self):
        self.obs["self"]["weapons"] = [self.weapon("gun"),
                                          self.weapon("lightning")]
        self.obs["mechs"] = [self.enemy(30, id=6),
                              self.enemy(40, id=5)]
        self.attacked(6)
        action = self.act_with_safety()
        self.assertEqual(self.bot.state, "DEFEND")
        self.assertEqual(self.bot.telemetry["target"], 6)
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertFalse(action["fire"][1],
                         "An authorized first hit cannot authorize a quiet chain victim")

    def test_missing_attacker_does_not_authorize_visible_quiet_mech(self):
        self.obs["mechs"] = [self.enemy(50, hp=10)]
        self.attacked(6)
        self.assert_no_enemy_fire(self.act_with_safety([5]))

    def test_zone_damage_does_not_authorize_an_enemy(self):
        self.obs["mechs"] = [self.enemy(40, hp=10)]
        self.obs["events"] = [{"type": "damaged", "by": None,
                               "weapon": "zone", "amount": 2, "bearing": None}]
        self.assert_no_enemy_fire(self.act_with_safety([5]))

    def test_npc_defense_is_allowed_during_recovery(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(40, id=102, kind="npc", hp=350,
                                        max_hp=350, weapons=[])]
        self.obs["self"]["aim"] = [0, math.atan2(1.75 - 7, 40)]
        self.attacked(102, weapon="npc", amount=25)
        action = self.act_with_safety()
        self.assertEqual(self.bot.state, "RECOVER")
        self.assertEqual(self.bot.telemetry["target"], 102)
        self.assertEqual(self.bot.telemetry["fire_reason"], "attributed_npc_attack")
        self.assertTrue(action["fire"][0])

    def test_npc_damage_does_not_authorize_unrelated_mech(self):
        self.obs["mechs"] = [self.enemy(40, hp=10)]
        self.attacked(102, weapon="npc", amount=25)
        self.assert_no_enemy_fire(self.act_with_safety([5]))

    def test_quiet_close_npc_does_not_bypass_recovery_farming_ban(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(20, id=102, kind="npc", hp=350,
                                        max_hp=350, weapons=[])]
        self.assert_no_enemy_fire(self.act_with_safety())

    def test_anonymous_projectile_and_sound_allow_evasion_only(self):
        self.obs["mechs"] = [self.enemy(100, hp=10)]
        self.obs["projectiles"] = [{"id": 123, "kind": "gun",
                                     "pos": [50, 0, 4], "vel": [-252, 0, 0]}]
        self.obs["sounds"] = [{"kind": "gun", "bearing": 0,
                                "dist": "near", "age": .1}]
        self.assert_no_enemy_fire(self.act_with_safety([5]))

    def test_our_hit_does_not_manufacture_an_external_fight(self):
        self.obs["mechs"] = [self.enemy(100, hp=30)]
        self.obs["events"] = [{"type": "hit", "target": 5,
                               "weapon": "gun", "amount": 45}]
        self.assert_no_enemy_fire(self.act_with_safety([5]))

    def test_attributed_beam_crossing_our_body_authorizes_defense(self):
        self.obs["mechs"] = [self.enemy(100)]
        self.obs["beams"] = [{"by": 5, "kind": "laser", "age": .1,
                               "path": [[100, 0, 7], [0, 0, 4.5]]}]
        action = self.act_with_safety()
        self.assertEqual(self.bot.state, "DEFEND")
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(action["fire"][0])

    def test_safe_finish_selects_lowest_hp_with_hidden_beam_shooter(self):
        self.existing_fight()
        action = self.act_with_safety([5, 6])
        self.assertNotIn(9, [actor["id"] for actor in self.obs["mechs"]])
        self.assertEqual(self.bot.state, "FINISH")
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertEqual(self.bot.telemetry["target_hp"], 40)
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertTrue(action["fire"][0])

    def test_unsafe_lowest_hp_cannot_borrow_other_target_safety(self):
        self.existing_fight()
        self.act_with_safety([6])
        self.assertEqual(self.bot.state, "FINISH")
        self.assertEqual(self.bot.telemetry["target"], 6)
        self.assertEqual(self.bot.telemetry["target_hp"], 70)

    def test_elective_finish_preserves_energy_from_lightning_and_boost(self):
        lightning = self.weapon("lightning")
        lightning["stats"]["range"] = 70
        self.obs["self"].update(energy=36,
                                  weapons=[self.weapon("gun"), lightning])
        self.obs["mechs"] = [self.enemy(65, id=5, hp=20)]
        self.obs["beams"] = [{"by": 9, "kind": "lightning", "age": .1,
                               "path": [[90, 10, 7], [65, 0, 4.5]]}]
        # Force a requested boost so this exercises orchestration's final
        # spending guard, independently of tactical boost selection.
        with patch.object(self.bot, "movement", return_value=((1, 0), True)):
            action = self.act_with_safety([5])
        self.assertEqual(self.bot.state, "FINISH")
        self.assertEqual(self.bot.telemetry["target"], 5)
        self.assertTrue(self.bot.telemetry["allow_fire"])
        self.assertTrue(action["fire"][0], "The affordable gun finish remains available")
        self.assertFalse(action["fire"][1], "Lightning cannot spend the escape reserve")
        self.assertFalse(action["boost"], "Boost cannot spend the escape reserve")

    def test_existing_fight_without_safety_permission_is_observed(self):
        self.existing_fight()
        self.assert_no_enemy_fire(self.act_with_safety())
        self.assertEqual(self.bot.state, "OBSERVE")

    def test_recovery_preempts_external_finish_even_with_safe_geometry(self):
        self.existing_fight()
        self.obs["self"]["hp"] = 500
        self.assert_no_enemy_fire(self.act_with_safety([5, 6]))
        self.assertEqual(self.bot.state, "RECOVER")

    def test_expired_fight_evidence_returns_to_observation(self):
        self.existing_fight()
        self.act_with_safety([5, 6])
        self.assertEqual(self.bot.state, "FINISH")
        self.obs.update(t=30, tick=600)
        self.obs["beams"] = []
        self.assert_no_enemy_fire(self.act_with_safety([5, 6]))
        self.assertEqual(self.bot.state, "OBSERVE")

    def test_orchestration_does_not_mutate_observation(self):
        self.existing_fight()
        before = copy.deepcopy(self.obs)
        self.act_with_safety([5, 6])
        self.assertEqual(self.obs, before)


if __name__ == "__main__":
    unittest.main()
