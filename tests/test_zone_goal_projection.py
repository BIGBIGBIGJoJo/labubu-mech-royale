"""Validate new zone endpoints without claiming route connectivity or game wins."""
import base64
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

import test_strategy as fixtures
from arena_map import ArenaMap


class ZoneGoalProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon

    def project(self, candidates=(), outside=(200, 0, 0), center=(0, 0), radius=100, deadline=1):
        self.bot.recover = True
        with patch('bot.time.perf_counter', return_value=0):
            return self.bot.project_zone_goal(self.obs, [], self.bot.stats(self.obs['self']),
                                             outside, candidates, center, radius, deadline)

    def test_valid_original_projection_preserves_coordinate_and_terrain_height(self):
        with patch.object(self.bot.map, 'ground_height', return_value=7.25):
            self.assertEqual(self.project(), [82.5, 0, 7.25])

    def test_active_failed_goal_applies_after_projection(self):
        self.bot.failed_goals = [([82.5, 0, 0], 32)]
        result = self.project()
        self.assertLess(result[0], 82.5)
        self.assertGreaterEqual(math.dist(result[:2], [82.5, 0]), 8)

    def test_existing_valid_cover_is_retained_and_ranked_with_existing_cost(self):
        with patch.object(self.bot.map, 'point_clear', side_effect=lambda p, *args: p[0] != 82.5), \
                patch.object(self.bot, 'position_cost', side_effect=lambda p, *args: 0 if p == [0, 30, 0] else 1000):
            result = self.project(candidates=[[0, 30, 0], [0, 101, 0]])
        self.assertEqual(result, [0, 30, 0])

    def test_existing_cover_outside_future_circle_is_not_a_fallback(self):
        with patch.object(self.bot.map, 'point_clear', return_value=False):
            self.assertEqual(self.project(candidates=[[150, 0, 0]]), self.obs['self']['pos'])

    def test_no_clear_endpoint_returns_explicit_current_position_hold(self):
        self.obs['self']['pos'] = [125, 4, 6]
        before = copy.deepcopy(self.bot.failed_goals)
        with patch.object(self.bot.map, 'point_clear', return_value=False):
            result = self.project()
        self.assertEqual(result, [125, 4, 6])
        self.assertEqual(self.bot.failed_goals, before)

    def test_inward_search_has_exact_eight_additional_probe_cap(self):
        with patch.object(self.bot.map, 'point_clear', return_value=False) as clear:
            self.project()
        self.assertEqual(clear.call_count, 9)

    def test_center_is_not_retested_when_inward_radius_clamps_to_zero(self):
        with patch.object(self.bot.map, 'point_clear', return_value=False) as clear:
            self.project(radius=20)
        self.assertEqual(clear.call_count, 2)

    def test_exhausted_deadline_does_not_invent_or_validate_an_endpoint(self):
        with patch.object(self.bot.map, 'ground_height', side_effect=AssertionError('expired')), \
                patch.object(self.bot.map, 'point_clear', side_effect=AssertionError('expired')):
            self.assertEqual(self.project(deadline=0), self.obs['self']['pos'])

    def test_deadline_after_validation_keeps_validated_cover_incumbent(self):
        clock = [0]
        def clear(point, radius, height):
            if point == [20, 0, 0]:
                clock[0] = 2
                return True
            return False
        with patch('bot.time.perf_counter', side_effect=lambda: clock[0]), \
                patch.object(self.bot.map, 'point_clear', side_effect=clear), \
                patch.object(self.bot, 'position_cost', side_effect=AssertionError('expired scoring')):
            result = self.bot.project_zone_goal(self.obs, [], self.bot.stats(self.obs['self']),
                                               [200, 0, 0], [[20, 0, 0]], [0, 0], 100, 1)
        self.assertEqual(result, [20, 0, 0])

    def test_small_endpoint_budget_keeps_clear_incumbent_without_expensive_rays(self):
        with patch.object(self.bot.map, 'point_clear', side_effect=lambda p, *args: p == [20, 0, 0]), \
                patch.object(self.bot, 'position_cost', side_effect=AssertionError('insufficient scoring reserve')):
            self.assertEqual(self.project(candidates=[[20, 0, 0]], deadline=.0015), [20, 0, 0])

    def test_large_body_dimensions_and_diameter_spacing_are_preserved(self):
        self.obs['self']['cubes'] = 40  # radius 7.5, height 27
        seen = []
        def clear(point, radius, height):
            seen.append((point[0], radius, height))
            return point[0] <= 62.5 and radius <= 7.5 and height <= 27
        with patch.object(self.bot.map, 'point_clear', side_effect=clear):
            result = self.project()
        self.assertTrue(all(radius == 7.5 and height == 27 for _, radius, height in seen))
        self.assertEqual(seen[0][0] - seen[1][0], 15)
        self.assertLessEqual(result[0], 62.5)
        self.assertLessEqual(math.hypot(*result[:2]) + 7.5, 100)

    def test_scoring_reserves_endpoint_work_within_original_deadline(self):
        self.bot.recover = True
        self.obs['self']['pos'] = [200, 0, 0]
        self.obs['zone'].update(center=[0, 0], radius=100, next_center=[0, 0], next_radius=100)
        clock = [.9984]
        def cost(*args):
            clock[0] = .999
            return 0
        with patch('bot.time.perf_counter', side_effect=lambda: clock[0]), \
                patch.object(self.bot.map, 'cover_candidates', return_value=[[80, 0, 0]]), \
                patch.object(self.bot, 'position_cost', side_effect=cost) as score:
            result = self.bot.safe_goal(self.obs, [], self.bot.stats(self.obs['self']), 1)
        self.assertEqual(score.call_count, 1)
        self.assertEqual(result, [82.5, 0, 0])

    def test_ordinary_inside_circle_selection_keeps_recovery_path(self):
        self.bot.recover = True
        with patch.object(self.bot, 'project_zone_goal', side_effect=AssertionError('unneeded projection')), \
                patch.object(self.bot, 'recovery_escape_goal', return_value=[11, 12, 0]) as recovery:
            with patch('bot.time.perf_counter', return_value=0):
                result = self.bot.safe_goal(self.obs, [], self.bot.stats(self.obs['self']), 1)
        self.assertEqual(result, [11, 12, 0])
        recovery.assert_called_once()

    def test_actual_bot_no_endpoint_keeps_urgent_rotation_without_forced_movement(self):
        self.obs['self'].update(pos=[200, 0, 0], hp=500, in_zone=False)
        self.obs['zone'].update(center=[0, 0], radius=100, next_center=[0, 0], next_radius=100)
        with patch.object(self.bot.map, 'cover_candidates', return_value=[]), \
                patch.object(self.bot.map, 'point_clear', return_value=False):
            action = self.bot.act(self.obs)
        self.assertEqual(self.bot.mode, 'rotate')
        self.assertEqual(self.bot.telemetry['goal'], self.obs['self']['pos'])
        self.assertEqual(action['move'], [0, 0])
        self.assertFalse(action['jump'])
        self.assertFalse(action['boost'])
        self.assertFalse(self.bot.blacklist)


class RecordedZoneGoalProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()
        root = Path(__file__).resolve().parent
        cls.fixture = json.loads((root / 'zone_goal_projection_fixture.json').read_text())
        cls.directory = tempfile.TemporaryDirectory(prefix='mechfight-zone-goal-')
        folder = Path(cls.directory.name) / 'v2'
        folder.mkdir()
        (folder / 'world.json').write_text(json.dumps(cls.fixture['world']))
        (folder / 'terrain.i16').write_bytes(zlib.decompress(base64.b64decode(cls.fixture['terrain_zlib_base64'])))
        cls.arena = ArenaMap(cls.directory.name, cls.hello['config'])
        if not cls.arena.available:
            raise RuntimeError(cls.arena.error)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def case(self, t):
        case = copy.deepcopy(next(c for c in self.fixture['cases'] if c['obs']['t'] == t))
        with patch.object(fixtures.policy, 'ArenaMap', return_value=self.arena):
            bot = fixtures.policy.Bot(copy.deepcopy(self.hello))
        bot.recover, bot.mode = True, 'rotate'
        bot.failed_goals = copy.deepcopy(case['failed_goals'])
        return bot, case

    def assert_valid(self, bot, case, point):
        stats = bot.stats(case['obs']['self'])
        center, radius = bot.zone_future(case['obs'], 22)
        self.assertTrue(bot.map.point_clear(point, stats['radius'], stats['height']))
        self.assertLessEqual(math.dist(point[:2], center) + stats['radius'], radius + 1e-6)
        self.assertTrue(all(math.dist(point[:2], old[:2]) >= 8 for old, _ in bot.failed_goals))

    def test_recorded_90_invalid_projection_is_not_returned_by_safe_goal(self):
        bot, case = self.case(90)
        stats = bot.stats(case['obs']['self'])
        self.assertFalse(bot.map.point_clear(case['old_goal'], stats['radius'], stats['height']))
        # Force the original origin-first winner while retaining exact geometry.
        with patch('bot.time.perf_counter', return_value=0), \
                patch.object(bot.map, 'cover_candidates', return_value=[]):
            point = bot.safe_goal(case['obs'], [], stats, 1)
        self.assertNotEqual(point, case['old_goal'])
        self.assert_valid(bot, case, point)

    def test_recorded_retirement_does_not_reselect_failed_projection(self):
        for t in (96.3, 96.5):
            with self.subTest(t=t):
                bot, case = self.case(t)
                self.assertTrue(any(math.dist(case['old_goal'][:2], p[:2]) < 8 for p, _ in bot.failed_goals))
                with patch('bot.time.perf_counter', return_value=0), \
                        patch.object(bot.map, 'cover_candidates', return_value=case['cover']):
                    point = bot.safe_goal(case['obs'], [], bot.stats(case['obs']['self']), 1)
                self.assert_valid(bot, case, point)

    def test_actual_arena_inset_is_checked_for_projected_destination(self):
        bot, case = self.case(90)
        # Isolate the real map's boundary rule away from every solid footprint.
        with patch.object(bot.map, 'bounds', {'minX': -100, 'maxX': 100, 'minY': -100, 'maxY': 100}), \
                patch.object(bot.map, '_candidates', return_value=set()), \
                patch('bot.time.perf_counter', return_value=0):
            bot.failed_goals = []
            point = bot.project_zone_goal(case['obs'], [], bot.stats(case['obs']['self']),
                                          [200, 0, 0], [], [0, 0], 100, 1)
            self.assertTrue(bot.map.point_clear(point, 2.875, 10.35))
            self.assertLessEqual(abs(point[0]), 100 - bot.map.arena_margin)


if __name__ == '__main__':
    unittest.main()
