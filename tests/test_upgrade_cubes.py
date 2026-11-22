"""Behavioral tradeoffs for the single post-cap flat-utility removal.

Official schemas/configuration, with an unobstructed controlled map. Captured
scalar cases check valuation only; no alternate gameplay or geometry claim.
"""
import copy
import json
from pathlib import Path
import unittest

import test_strategy as fixtures


class UpgradeCubeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon

    def pile(self, owned, count, travel, held=False):
        self.obs["self"]["cubes"] = owned
        self.obs["self"]["max_hp"] = 1400 * (1 + .04 * min(owned, 10))
        self.obs["self"]["hp"] = self.obs["self"]["max_hp"]
        self.obs["cubes"] = [{"id": 5000 + i, "pos": [travel, 0, 0]}
                             for i in range(count)]
        self.bot.loot = {}
        self.bot.resource_key = ("cubes", 5000) if held else None

    def candidate(self):
        self.bot.update(self.obs)
        return self.bot.resource_goal(self.obs, [], deadline=None)

    def test_recorded_scalar_tradeoffs(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/postcap-utility.json").read_text())
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                self.pile(case["cubes"], case["count"], case["travel"], case["held"])
                result = self.candidate()
                if case["candidate_score"] is None:
                    self.assertIsNone(result)
                else:
                    self.assertIsNotNone(result)
                    self.assertEqual(result[3], ("cubes", 5000))
                    self.assertAlmostEqual(result[0], case["candidate_score"], places=9)

    def test_pre_cap_cube_and_recovery_healing_preserved(self):
        self.pile(0, 1, 20)
        ordinary = self.candidate()
        self.assertEqual(ordinary[3], ("cubes", 5000))
        self.assertAlmostEqual(ordinary[0], 46.6)
        self.obs["self"]["hp"] = 500
        self.bot.recover = True
        recovery = self.candidate()
        self.assertEqual(recovery[3], ordinary[3])
        self.assertAlmostEqual(recovery[0] - ordinary[0], 16.8)

    def test_cross_cap_bundle_keeps_last_useful_cube_and_threshold(self):
        self.pile(9, 2, 20)
        before = copy.deepcopy(self.obs)
        ordinary = self.candidate()
        self.assertAlmostEqual(ordinary[0], 46.6)
        self.assertEqual(self.obs, before, "Valuation must not simulate automatic pickup")
        self.obs["self"]["hp"] = 500
        self.bot.recover = True
        self.assertAlmostEqual(self.candidate()[0] - ordinary[0], 16.8,
                               msg="Only the last useful cube contributes pickup healing")

    def test_post_cap_threshold_has_no_phantom_healing(self):
        self.pile(12, 5, 20)
        ordinary = self.candidate()
        self.obs["self"]["hp"] = 500
        self.bot.recover = True
        recovery = self.candidate()
        self.assertEqual(recovery, ordinary)

    def test_multiple_thresholds_still_receive_one_bonus(self):
        self.pile(20, 1, 20)  # Crosses21.
        one_threshold = self.candidate()[0]
        self.pile(20, 13, 20)  # Crosses21 and28.
        two_thresholds = self.candidate()[0]
        self.assertAlmostEqual(one_threshold, 14.6)
        self.assertEqual(one_threshold, two_thresholds)

    def test_existing_offer_does_not_create_future_cube_value(self):
        self.pile(32, 3, 4)
        self.obs["offer"] = {"id": 7, "expires": 25,
                             "choices": [{"id": "laser_damage"}, {"id": "armor"}]}
        self.assertIsNone(self.candidate(), "Known group reaches35, below next threshold36")
        self.assertEqual(self.bot.choose_upgrade(self.obs), 1,
                         "Existing offer selection remains independent and unchanged")
        self.obs["cubes"].append({"id": 5003, "pos": [4, 0, 0]})
        self.assertIsNotNone(self.candidate(), "A newly observed fourth cube now crosses36")

    def test_close_existing_objective_retains_continuity(self):
        self.pile(32, 3, 5)
        self.assertIsNone(self.candidate())
        self.bot.resource_key = ("cubes", 5000)
        result = self.candidate()
        self.assertEqual(result[3], ("cubes", 5000))
        self.assertAlmostEqual(result[0], 7.4)

    def test_post_cap_no_threshold_cube_does_not_displace_weapon(self):
        self.pile(32, 3, 4)
        self.obs["pickups"] = [{"id": 8000, "kind": "laser", "pos": [40, 0, 0]}]
        result = self.candidate()
        self.assertEqual(result[3], ("pickups", 8000))
        self.assertAlmostEqual(result[0], 87.2)


if __name__ == "__main__":
    unittest.main()
