"""Resource behavior checks on official schemas, without a simulated match engine."""
import copy
import time
import unittest
from unittest.mock import patch

import test_strategy as fixtures


class EconomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def candidate(self, deadline=None):
        self.bot.update(self.obs)
        threats = self.bot.threats(self.obs, self.bot.stats(self.obs["self"]))
        return self.bot.resource_goal(self.obs, threats, deadline=deadline)

    def drop(self, x=0, **values):
        item = {"id": 20000, "pos": [x, 0, 0], "radius": 8,
                "lands_in": 0, "capture_s": 4, "progress": 0, "holder": None}
        item.update(values)
        return item

    def test_recovery_keeps_escape_goal_over_optional_cube(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(50)]
        self.obs["cubes"] = [{"id": 5001, "pos": [-15, 0, 0]}]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertIsNone(self.bot.resource_key)
        self.assertLess(action["move"][0], -0.5)

    def test_recovery_rejects_cube_toward_close_attacker(self):
        self.obs["self"]["hp"] = 500
        self.obs["mechs"] = [self.enemy(50)]
        self.obs["cubes"] = [{"id": 5001, "pos": [15, 0, 0]}]
        self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertIsNone(self.bot.resource_key)

    def test_quiet_recovery_does_not_start_crate_farming(self):
        self.obs["self"]["hp"] = 500
        self.obs["crates"] = [{"id": 1001, "pos": [20, 0, 0], "hp": 300}]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertIsNone(self.bot.resource_key)
        self.assertEqual(action["fire"], [False, False])

    def test_safe_opening_crate_remains_available(self):
        self.obs["crates"] = [{"id": 1001, "pos": [43, 0, 0], "hp": 300}]
        self.bot.act(self.obs)
        self.assertEqual(self.bot.resource_key, ("crates", 1001))
        self.assertEqual(self.bot.telemetry["target"], 1001)

    def test_finish_damaged_crate_before_nearby_fresh_crate(self):
        self.obs["crates"] = [
            {"id": 1001, "pos": [30, 0, 0], "hp": 300},
            {"id": 1002, "pos": [35, 0, 0], "hp": 30},
        ]
        self.assertEqual(self.candidate()[3], ("crates", 1002))

    def test_colocated_cube_pile_outweighs_nearer_single_cube(self):
        self.obs["cubes"] = [
            {"id": 5001, "pos": [-20, 0, 0]},
            {"id": 5002, "pos": [30, 0, 0]},
            {"id": 5003, "pos": [30, 0, 0]},
        ]
        self.assertIn(self.candidate()[3], [("cubes", 5002), ("cubes", 5003)])

    def test_rooftop_cubes_do_not_inflate_ground_pile_value(self):
        self.obs["cubes"] = [
            {"id": 5000, "pos": [-10, 0, 0]},
            {"id": 5001, "pos": [20, 0, 0]},
            {"id": 5002, "pos": [20, 0, 12]},
            {"id": 5003, "pos": [20, 0, 12]},
        ]
        self.assertEqual(self.candidate()[3], ("cubes", 5000))

    def test_recovery_does_not_detour_to_announced_drop(self):
        self.obs["self"]["hp"] = 500
        self.obs["drops"] = [self.drop(100, lands_in=10)]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.recover)
        self.assertIsNone(self.bot.resource_key)
        self.assertEqual(self.bot.mode, 'recover')
        self.assertEqual(action['move'], [0., 0.])

    def test_drop_does_not_cause_long_early_wait(self):
        self.obs["drops"] = [self.drop(100, lands_in=25)]
        self.assertIsNone(self.candidate())

    def test_capture_credits_only_our_existing_progress(self):
        self.obs["drops"] = [self.drop(holder=self.bot.slot, progress=3.5)]
        self.obs["mechs"] = [self.enemy(100)]
        self.assertEqual(self.candidate()[3], ("drop", 20000),
                         "Our nearly completed capture finishes before the opponent arrives")
        self.obs["drops"][0]["holder"] = 5 if self.bot.slot != 5 else 6
        self.assertIsNone(self.candidate(),
                          "Another holder's progress cannot shorten our capture")

    def test_low_hp_drop_rejected_under_distant_laser_fire(self):
        self.obs["self"]["hp"] = 200
        self.bot.recover = True
        self.obs["drops"] = [self.drop()]
        self.obs["mechs"] = [self.enemy(200, weapons=["laser"], charging=True)]
        self.assertIsNone(self.candidate(),
                          "Being unable to contest the ring does not prevent a lethal beam")

    def test_drop_damage_estimate_includes_mortar_splash(self):
        self.obs["self"]["hp"] = 700
        self.bot.recover = True
        self.obs["drops"] = [self.drop()]
        self.obs["mechs"] = [self.enemy(150, weapons=["mortar"])]
        self.assertIsNone(self.candidate(),
                          "Two direct/splash impacts exceed the capture damage budget")

    def test_protected_drop_remains_available_during_recovery(self):
        self.obs["self"]["hp"] = 200
        self.bot.recover = True
        self.obs["drops"] = [self.drop()]
        self.obs["mechs"] = [self.enemy(200, weapons=["laser"], charging=True)]
        with patch.object(self.bot.map, "line_of_fire", return_value=False):
            self.assertEqual(self.candidate()[3], ("drop", 20000))

    def test_low_hp_drop_rejected_inside_npc_aggro_range(self):
        self.obs["self"]["hp"] = 50
        self.bot.recover = True
        self.obs["drops"] = [self.drop()]
        self.obs["mechs"] = [self.enemy(40, id=100, kind="npc", hp=350,
                                        max_hp=350, weapons=["gun"])]
        self.assertIsNone(self.candidate(),
                          "An NPC can kill the capturer even though it cannot contest the ring")

    def test_expired_economy_budget_does_not_scan_npc_farm(self):
        self.obs["mechs"] = [self.enemy(30, id=100, kind="npc", hp=350,
                                        max_hp=350, weapons=["gun"])]
        self.assertIsNone(self.candidate(deadline=time.perf_counter() - 1))

    def test_resource_evaluation_preserves_observation(self):
        self.obs["cubes"] = [{"id": 5001, "pos": [-15, 0, 0]}]
        self.obs["drops"] = [self.drop(100, lands_in=10)]
        before = copy.deepcopy(self.obs)
        self.candidate()
        self.assertEqual(self.obs, before)


if __name__ == "__main__":
    unittest.main()
