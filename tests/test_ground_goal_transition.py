"""A provisional airborne objective must not stay trusted after returning down."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_strategy as fixtures
from ground_reachability import YES, NO, UNKNOWN


class GroundGoalTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    weapon = fixtures.StrategyTests.weapon

    def setUp(self):
        fixtures.StrategyTests.setUp(self)
        self.bot.map.step_up = 1.2
        self.context = SimpleNamespace(classify=Mock(return_value=NO))
        self.routes = SimpleNamespace(index=object(), begin=Mock(return_value=self.context))
        self.bot.ground_routes = self.routes
        self.bot.goal = [35., 0., 0.]
        self.bot.goal_kind = 'position'
        self.bot.goal_until = self.obs['t'] + 5
        self.replacement = [15., 20., 0.]

    def step(self):
        with patch.object(self.bot, 'safe_goal', return_value=self.replacement) as select:
            self.bot.act(self.obs)
            return select.call_count

    def test_off_ground_marks_provisional_without_rejecting_it(self):
        self.obs['self'].update(pos=[0., 0., 5.], grounded=False)
        self.assertEqual(self.step(), 0)
        self.assertTrue(self.bot.ground_goal_pending)
        self.routes.begin.assert_not_called()
        self.assertEqual(self.bot.goal, [35., 0., 0.])

    def test_return_to_ground_replaces_newly_unreachable_held_goal(self):
        self.obs['self'].update(pos=[0., 0., 5.], grounded=False)
        self.step()
        self.obs['self'].update(pos=[0., 0., 0.], grounded=True)
        self.obs.update(t=20.1, tick=402)
        self.assertEqual(self.step(), 1)
        self.context.classify.assert_called_once_with([35., 0., 0.])
        self.assertEqual(self.bot.goal, self.replacement)
        self.assertTrue(self.bot.ground_goal_pending)

    def test_replacement_stays_provisional_until_explicitly_verified(self):
        self.bot.ground_goal_pending = True
        self.assertEqual(self.step(), 1)
        self.context.classify.return_value = UNKNOWN
        self.obs.update(t=20.1, tick=402)
        self.assertEqual(self.step(), 0)
        self.assertTrue(self.bot.ground_goal_pending)
        self.context.classify.return_value = YES
        self.obs.update(t=20.2, tick=404)
        self.assertEqual(self.step(), 0)
        self.assertFalse(self.bot.ground_goal_pending)
        self.assertEqual(self.routes.begin.call_count, 3)

    def test_expired_provisional_goal_refreshes_before_any_revalidation(self):
        self.bot.ground_goal_pending = True
        self.bot.goal_until = 19.
        self.assertEqual(self.step(), 1)
        self.routes.begin.assert_not_called()
        self.assertTrue(self.bot.ground_goal_pending)
        self.context.classify.return_value = YES
        self.obs.update(t=20.1, tick=402)
        self.assertEqual(self.step(), 0)
        self.assertFalse(self.bot.ground_goal_pending)

    def test_verified_held_goal_is_kept_and_not_checked_every_frame(self):
        self.bot.ground_goal_pending = True
        self.context.classify.return_value = YES
        self.assertEqual(self.step(), 0)
        self.assertFalse(self.bot.ground_goal_pending)
        self.obs.update(t=20.1, tick=402)
        self.assertEqual(self.step(), 0)
        self.assertEqual(self.routes.begin.call_count, 1)

    def test_unknown_keeps_objective_and_retries_on_next_observation(self):
        self.bot.ground_goal_pending = True
        self.context.classify.return_value = UNKNOWN
        self.assertEqual(self.step(), 0)
        self.assertTrue(self.bot.ground_goal_pending)
        self.context.classify.return_value = NO
        self.obs.update(t=20.1, tick=402)
        self.assertEqual(self.step(), 1)
        self.assertEqual(self.routes.begin.call_count, 2)

    def test_resource_objective_does_not_enter_safe_goal_revalidation(self):
        self.bot.ground_goal_pending = True
        item = {'id': 5001, 'pos': [20., 0., 0.]}
        resource = (10., item['pos'], 'cubes', ('cubes', 5001), item)
        with patch.object(self.bot, 'resource_goal', return_value=resource):
            self.assertEqual(self.step(), 0)
        self.routes.begin.assert_not_called()
        self.assertEqual(self.bot.goal_kind, 'loot')

    def test_missing_graph_does_not_add_a_validation_requirement(self):
        self.routes.index = None
        self.bot.ground_goal_pending = True
        self.assertEqual(self.step(), 0)
        self.routes.begin.assert_not_called()


if __name__ == '__main__':
    unittest.main()
