"""Captured ground-route witnesses and explicit height/cancellation regressions."""
import copy
from array import array
import json
from pathlib import Path
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

from arena_map import ArenaMap
from bot import Bot
from zone_resource import ZoneResourcePlanner


ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'tests/fixtures/integrated-resource-boundary.json').read_text())


class GroundLeaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arena = ArenaMap(ROOT / 'arena', DATA['config'])
        assert cls.arena.available and len(cls.arena.prisms) == 259

    def setUp(self):
        self.obs = copy.deepcopy(DATA['observations']['119.7'])
        with patch('bot.ArenaMap', return_value=self.arena):
            self.bot = Bot({'config': DATA['config'], 'map': {'dir': str(ROOT / 'arena')}, 'slot': 0})
        self.stats = self.bot.stats(self.obs['self'])
        self.planner = self.bot.zone_resources
        # Geometry/transition tests do not depend on the test host's speed.
        # The unmodified six-ms budget is checked by chronological Linux replay.
        self.planner.BUDGET_S = 1.

    def candidate(self):
        item = next(c for c in self.obs['cubes'] if c['id'] == 5064)
        return (1., item['pos'], 'cubes', ('cubes', 5064), item)

    def start(self):
        plan = self.planner.start_lease(self.obs, self.candidate(), self.stats)
        self.assertIsNotNone(plan, self.planner.last_report)
        return plan

    def test_captured_1197_terrain_route_has_same_fixed_exit_and_growth(self):
        plan = self.start()
        self.assertEqual(plan['modeled_cubes'], 1)
        self.assertAlmostEqual(plan['radius'], 2.75)
        self.assertAlmostEqual(plan['escape'][0], -102.69773836796288)
        self.assertAlmostEqual(plan['escape'][1], -41.965258625414755)
        self.assertAlmostEqual(plan['pickup'][2], self.arena.ground_height(*plan['pickup'][:2]))
        for a, b in zip([self.obs['self']['pos'], plan['pickup']], [plan['pickup'], plan['escape']]):
            self.assertTrue(self.planner._ground_segment(a, b, plan['radius'], time.perf_counter()+1))
            self.assertTrue(self.arena.move_clear(a, b, plan['radius'], plan['height']))

    def test_item_elevation_is_not_used_as_second_leg_feet_height(self):
        item = self.candidate()[4]
        item['pos'][2] += 2.
        plan = self.start()
        self.assertGreater(item['pos'][2]-plan['pickup'][2], 2.)
        self.assertAlmostEqual(plan['pickup'][2], self.arena.ground_height(*item['pos'][:2]))

    def test_actual_bridge_roof_start_does_not_certify_terrain_route(self):
        roof = [-114.84, -29.77, 8.59]
        under = [*roof[:2], self.arena.ground_height(*roof[:2])]
        self.assertTrue(self.arena.move_clear(roof, under, 2.5, 9.))
        self.obs['self'].update(pos=roof, grounded=True)
        self.assertIsNone(self.planner.plan(self.obs, self.candidate(), self.stats))
        self.assertEqual(self.planner.last_report['reason'], 'start_not_on_terrain')

    def test_existing_lease_is_cancelled_when_start_moves_to_roof(self):
        self.start()
        self.obs['t'] += .1
        self.obs['self']['pos'] = [-114.84, -29.77, 8.59]
        self.assertIsNone(self.planner.continue_lease(self.obs, self.stats, eligible=True))
        self.assertEqual(self.planner.last_report['reason'], 'start_not_on_terrain')
        self.assertIsNone(self.planner.lease_key)

    def test_terrain_endpoints_cannot_hide_intermediate_roof_support(self):
        # Both endpoints match terrain. Between them the terrain drops under a
        # bridge, while move_clear retains the roof and ignores requested end Z.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'v2'
            path.mkdir()
            world = {'bounds': {'minX': 0, 'minY': 0, 'maxX': 40, 'maxY': 40},
                     'terrain': {'file': 'terrain.i16', 'minX': 0, 'minY': 0, 'step': 1,
                                 'nx': 41, 'ny': 41, 'scale': .01},
                     'prisms': [{'kind': 'bridge', 'base': 12, 'top': 14,
                                 'ring': [18, 6, 24, 6, 24, 14, 18, 14], 'holes': []}]}
            (path / 'world.json').write_text(json.dumps(world))
            samples = array('h', [1400 if x <= 19 else 0 for y in range(41) for x in range(41)])
            if sys.byteorder != 'little':
                samples.byteswap()
            (path / 'terrain.i16').write_bytes(samples.tobytes())
            arena = ArenaMap(root, {'mech': DATA['config']['mech']}, use_navigation_cache=False)
            start, end = (19., 10., 14.), (22., 10., 0.)
            planner = ZoneResourcePlanner(DATA['config'], arena)
            self.assertTrue(planner._ground_scope(start))
            self.assertTrue(planner._ground_scope(end))
            self.assertTrue(arena.point_clear(start, 1., 9.))
            self.assertTrue(arena.point_clear(end, 1., 9.))
            self.assertTrue(arena.move_clear(start, end, 1., 9.))
            self.assertFalse(planner._ground_segment(start, end, 1., time.perf_counter()+1))

    def test_current_item_height_is_rechecked_during_collect(self):
        self.start()
        self.candidate()[4]['pos'][2] += 4.
        self.assertIsNone(self.planner.continue_lease(self.obs, self.stats, eligible=True))
        self.assertEqual(self.planner.last_report['reason'], 'resource_moved')

    def test_fixed_exit_continues_until_recorded_phase_reserve_no_longer_fits(self):
        plan = self.start()
        for label in ('119.8', '120.3'):
            obs = copy.deepcopy(DATA['observations'][label])
            continued = self.planner.continue_lease(obs, self.bot.stats(obs['self']), eligible=True)
            self.assertIsNotNone(continued, self.planner.last_report)
            self.assertEqual(continued['escape'], plan['escape'])
        obs = copy.deepcopy(DATA['observations']['120.4'])
        self.assertIsNone(self.planner.continue_lease(obs, self.bot.stats(obs['self']), eligible=True))
        self.assertEqual(self.planner.last_report['reason'], 'route_or_zone_unsafe')

    def test_recorded_airborne_state_cannot_start_ground_lease(self):
        self.obs = copy.deepcopy(DATA['observations']['123.1'])
        self.assertIsNone(self.planner.plan(self.obs, self.candidate(), self.bot.stats(self.obs['self'])))
        self.assertEqual(self.planner.last_report['reason'], 'not_grounded_inside_zone')

    def test_expired_geometry_budget_fails_closed(self):
        plan = self.start()
        self.assertFalse(self.planner._ground_segment(self.obs['self']['pos'], plan['pickup'],
                                                     plan['radius'], time.perf_counter()-1))

    def test_cancelled_exit_with_future_ttl_refreshes_ordinary_rotation_goal(self):
        plan = self.start()
        self.planner._lease['phase'] = 'exit'
        self.planner.rotating = True
        self.bot.goal = list(plan['escape'])
        self.bot.goal_kind = 'rotate'
        self.bot.goal_until = self.obs['t']+1
        self.bot.ground_goal_pending = False
        fallback = list(self.obs['self']['pos'])

        def reject(*args, **kwargs):
            self.planner.cancel('route_or_zone_unsafe', self.obs['t'])
            return None

        with patch.object(self.planner, 'continue_lease', side_effect=reject), \
                patch.object(self.bot, 'safe_goal', return_value=fallback) as select, \
                patch.object(self.bot, 'movement', return_value=((0., 0.), False)):
            self.bot.act(self.obs)
        self.assertEqual(select.call_count, 1)
        self.assertEqual(self.bot.telemetry['goal'], fallback)
        self.assertIsNone(self.planner.lease_key)
        self.assertFalse(self.bot.telemetry['zone_resource']['active'])


if __name__ == '__main__':
    unittest.main()
