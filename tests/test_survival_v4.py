"""Regressions for observed resource traps and costly close-range commitments."""
import copy
import unittest

import test_strategy as fixtures


class SurvivalV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def holding_drop(self, target, remaining, **values):
        drop = {"id": 20000, "pos": list(target["pos"]), "radius": 8,
                "lands_in": 0, "capture_s": 4, "progress": 4 - remaining,
                "holder": target["id"]}
        drop.update(values)
        self.obs["drops"] = [drop]
        return drop

    def remember_recorded_drop_occupant(self):
        # The actor was still reported at t=77.0, then absent at t=77.5.
        # Positions and HP are taken from the V3 feedback trace.
        self.obs.update(t=77.0, tick=1540)
        self.obs["self"].update(pos=[166.24, -169.55, 7.31], hp=595.22,
                                max_hp=1568, cubes=3)
        self.obs["mechs"] = [self.enemy(
            id=2, pos=[228.09, -140.70, 5.04], hp=1345.2,
            max_hp=1848, cubes=8, weapons=["gun", "mortar"])]
        self.bot.update(self.obs)
        self.obs.update(t=77.5, tick=1550)
        self.obs["self"].update(pos=[169.67, -169.74, 6.49], hp=617.72)
        self.obs["mechs"] = []
        self.obs["drops"] = [{"id": 20001, "pos": [226.03, -141.70, 5.08],
                              "radius": 8, "lands_in": 5, "capture_s": 4,
                              "progress": 0, "holder": None}]
        self.bot.recover = True
        self.bot.update(self.obs)

    def resource(self):
        threats = self.bot.threats(self.obs, self.bot.stats(self.obs["self"]))
        return self.bot.resource_goal(self.obs, threats)

    def test_recently_disappeared_occupant_keeps_drop_unsafe(self):
        self.remember_recorded_drop_occupant()
        self.assertIsNone(self.resource())
        self.bot.actor_memory.clear()
        candidate = self.resource()
        self.assertIsNotNone(candidate,
                             "This fixture must isolate remembered occupancy as the veto")
        self.assertEqual(candidate[3], ("drop", 20001))

    def test_expired_actor_memory_does_not_block_drop_forever(self):
        self.remember_recorded_drop_occupant()
        self.obs.update(t=85.1, tick=1702)
        self.obs["drops"][0]["lands_in"] = 0
        self.bot.update(self.obs)
        self.assertNotIn(2, self.bot.actor_memory)
        self.assertEqual(self.resource()[3], ("drop", 20001))

    def test_confirmed_kill_immediately_clears_resource_hazard(self):
        self.remember_recorded_drop_occupant()
        self.obs["events"] = [{"type": "kill", "target": 2}]
        self.bot.update(self.obs)
        self.assertNotIn(2, self.bot.actor_memory)
        self.assertEqual(self.resource()[3], ("drop", 20001))

    def test_resource_memory_never_creates_ghost_firing_target(self):
        self.remember_recorded_drop_occupant()
        action = self.bot.act(self.obs)
        self.assertIn(2, self.bot.actor_memory)
        self.assertEqual(self.bot.threats(self.obs, self.bot.stats(self.obs["self"])), [])
        self.assertIsNone(self.bot.telemetry["target"])
        self.assertEqual(action["fire"], [False, False])

    def test_memory_snapshot_is_not_mutated_by_later_observations(self):
        actor = self.enemy(50)
        self.obs["mechs"] = [actor]
        self.bot.update(self.obs)
        actor["pos"][0] = 200
        actor["weapons"].append("laser")
        remembered = self.bot.actor_memory[actor["id"]][0]
        self.assertEqual(remembered["pos"][0], 50)
        self.assertEqual(remembered["weapons"], ["gun"])

    def test_recorded_healthy_lightning_rush_refuses_mortar_counter(self):
        self.obs["self"].update(hp=1523, max_hp=1568, cubes=3, energy=97)
        self.obs["self"]["weapons"] = [self.weapon("gun", ammo=16, reload=.87),
                                         self.weapon("lightning")]
        target = self.enemy(51.8, id=2, hp=1162.4, max_hp=1400,
                            weapons=["gun", "mortar"])
        self.assertFalse(self.bot.lightning_commit(self.obs, target, 1))

    def test_energy_loss_revokes_previously_valid_commitment(self):
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        target = self.enemy(50, hp=900)
        self.assertTrue(self.bot.lightning_commit(self.obs, target, 1))
        self.obs["self"]["energy"] = 52.29
        self.assertFalse(self.bot.lightning_commit(self.obs, target, 1))

    def test_energy_gate_changes_defensive_spacing_without_authorizing_pursuit(self):
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        self.obs["mechs"] = [self.enemy(70, hp=900)]
        self.obs["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "by": 5}]
        self.bot.act(self.obs)
        self.assertLessEqual(self.bot.telemetry["goal"][0], 0)
        self.obs.update(t=20.1, tick=402)
        self.obs["self"]["energy"] = 52.29
        self.bot.act(self.obs)
        self.assertLess(self.bot.telemetry["goal"][0], 0)

    def test_multiple_visible_mechs_prevent_close_commitment(self):
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        self.assertFalse(self.bot.lightning_commit(self.obs, self.enemy(40, hp=500), 2))

    def test_laser_short_advantage_does_not_apply_to_distant_laser(self):
        self.obs["self"].update(hp=1200, max_hp=1400)
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        target = self.enemy(40, hp=1400, weapons=["gun", "laser"])
        self.assertTrue(self.bot.lightning_commit(self.obs, target, 1))
        target["pos"][0] = 100
        self.assertFalse(self.bot.lightning_commit(self.obs, target, 1))

    def test_known_own_armor_changes_effective_health_comparison(self):
        self.obs["self"]["hp"] = 1100
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        target = self.enemy(50, hp=1400)
        self.assertFalse(self.bot.lightning_commit(self.obs, target, 1))
        self.obs["self"]["stats"]["armor"] = .24
        self.assertTrue(self.bot.lightning_commit(self.obs, target, 1))

    def test_recorded_repair_projects_before_finish(self):
        self.obs["self"].update(cubes=3, hp=1158.77, max_hp=1568, energy=31.29)
        self.obs["self"]["weapons"] = [self.weapon("gun", ammo=3, cooldown=.13),
                                         self.weapon("lightning", cooldown=.2)]
        target = self.enemy(43.9, id=2, hp=367.2, max_hp=1680, cubes=5)
        self.holding_drop(target, .35)
        self.assertTrue(self.bot.repair_before_projected_finish(self.obs, target))

    def test_projected_repair_does_not_suppress_viable_lightning(self):
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        target = self.enemy(40, hp=1000)
        self.obs["mechs"] = [target]
        self.obs["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "by": 5}]
        self.holding_drop(target, .35)
        action = self.bot.act(self.obs)
        self.assertTrue(action["fire"][1],
                        "The repair estimate may affect movement, not veto a viable arc")

    def test_partial_magazine_then_reload_counts_available_damage(self):
        self.obs["self"]["weapons"] = [self.weapon("gun", ammo=1), None]
        target = self.enemy(10, hp=200)
        self.holding_drop(target, 3)
        self.assertFalse(self.bot.repair_before_projected_finish(self.obs, target),
                         "A partial magazine can be followed by another before capture")

    def test_reload_in_progress_uses_future_full_magazine(self):
        self.obs["self"]["weapons"] = [self.weapon("gun", ammo=0, reload=.15), None]
        target = self.enemy(10, hp=120)
        self.holding_drop(target, .65)
        self.assertFalse(self.bot.repair_before_projected_finish(self.obs, target))

    def test_lightning_cooldown_and_approach_time_overlap(self):
        self.obs["self"]["weapons"] = [None, self.weapon("lightning", cooldown=.5)]
        target = self.enemy(55, hp=50)
        self.holding_drop(target, .8)
        self.assertFalse(self.bot.repair_before_projected_finish(self.obs, target),
                         "The cooldown elapses while moving into arc range")

    def test_gun_estimate_allows_near_body_arrival(self):
        self.obs["self"]["weapons"] = [self.weapon("gun"), None]
        target = self.enemy(40, hp=45)
        self.holding_drop(target, .2)
        self.assertFalse(self.bot.repair_before_projected_finish(self.obs, target),
                         "The movement estimate should allow a plausible near-side hit")

    def test_unmodeled_laser_does_not_trigger_repair_projection(self):
        self.obs["self"]["weapons"][1] = self.weapon("laser", charge=.75)
        target = self.enemy(40, hp=200)
        self.holding_drop(target, .35)
        self.assertFalse(self.bot.repair_before_projected_finish(self.obs, target))

    def test_other_holder_does_not_project_repair_for_target(self):
        target = self.enemy(40, hp=1000)
        self.holding_drop(target, .2, holder=8)
        self.assertFalse(self.bot.repair_before_projected_finish(self.obs, target))

    def test_our_presence_freezes_opponent_capture_projection(self):
        target = self.enemy(40, hp=1000)
        self.holding_drop(target, .2)
        self.assertTrue(self.bot.repair_before_projected_finish(self.obs, target))
        self.obs["self"]["pos"] = [34, 0, 0]
        self.assertFalse(self.bot.repair_before_projected_finish(self.obs, target),
                         "Our mech inside the ring freezes the existing capture clock")

    def test_other_mech_presence_freezes_opponent_capture_projection(self):
        target = self.enemy(40, hp=1000)
        self.holding_drop(target, .2)
        self.assertTrue(self.bot.repair_before_projected_finish(self.obs, target))
        self.obs["mechs"] = [target, self.enemy(44, id=8)]
        self.assertFalse(self.bot.repair_before_projected_finish(self.obs, target),
                         "Any second mech in the ring freezes its holder's progress")

    def test_survival_evaluation_preserves_observation(self):
        self.obs["self"]["weapons"][1] = self.weapon("lightning")
        target = self.enemy(40, hp=1000)
        self.holding_drop(target, .2)
        before = copy.deepcopy(self.obs)
        self.bot.repair_before_projected_finish(self.obs, target)
        self.bot.lightning_commit(self.obs, target, 1)
        self.assertEqual(self.obs, before)


if __name__ == "__main__":
    unittest.main()
