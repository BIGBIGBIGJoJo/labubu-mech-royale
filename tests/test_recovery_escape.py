"""Recovery escapes preserve cover/zone priority and use measured body geometry."""
import base64
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena_map import ArenaMap
from bot import Bot, distance


class FlatArena:
    available = True

    def __init__(self):
        self.sweeps = []

    def ground_height(self, x, y):
        return 0.0

    def line_of_fire(self, start, end):
        return True

    def move_clear(self, start, end, radius, height):
        self.sweeps.append((list(start), list(end), radius, height))
        return True


class RecoveryEscapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT / 'check/stream.jsonl.gz', 'rt', encoding='utf-8') as stream:
            cls.config = json.loads(next(stream))['config']

    def setUp(self):
        self.bot = Bot.__new__(Bot)
        self.bot.config = self.config
        self.bot.map = FlatArena()
        self.bot.mode = 'recover'
        self.bot.recover = True
        self.bot.last_hurt = 10.0
        self.bot.failed_goals = []
        self.stats = dict(self.config['mech'])
        self.obs = {'t':10.0, 'self':{'pos':[0,0,0], 'grounded':True},
                    'zone':{'center':[0,0], 'radius':400, 'next_center':[0,0],
                            'next_radius':300, 'shrink_start':60, 'shrink_end':90}}
        self.baseline = [0,0,0]
        actor = {'id':1, 'kind':'mech', 'pos':[-70,0,0], 'weapons':['gun'], 'cubes':0}
        self.threats = [{'actor':actor, 'd':70, 'risk':1, 'los':True}]
        self.cost = self.bot.position_cost(self.baseline, self.threats, [0,0], 400,
                                          self.stats['radius'], True, self.stats['muzzle_height'])

    def choose(self, deadline=1, cost=None):
        with patch('bot.time.perf_counter', return_value=0):
            return self.bot.recovery_escape_goal(self.obs, self.threats, self.stats,
                                                 self.baseline, self.cost if cost is None else cost, deadline)

    def test_recently_damaged_exposed_hold_can_escape(self):
        goal = self.choose()
        self.assertGreaterEqual(distance(goal, self.baseline), 8)
        self.assertLessEqual(distance(goal, self.baseline), 24.25)
        self.assertGreater(distance(goal, self.threats[0]['actor']['pos']), 85)
        self.assertTrue(any(distance(end, goal) < .001 for _, end, _, _ in self.bot.map.sweeps))

    def test_quiet_repair_does_not_restart_movement(self):
        self.bot.last_hurt = self.obs['t'] - self.stats['regen_delay'] - .01
        self.assertIs(self.choose(), self.baseline)
        self.assertEqual(self.bot.map.sweeps, [])

    def test_effective_cover_is_preserved(self):
        self.assertIs(self.choose(cost=0), self.baseline)
        self.assertEqual(self.bot.map.sweeps, [])

    def test_zone_penalty_alone_does_not_label_cover_exposed(self):
        self.obs['zone'].update(center=[0,0], radius=100)
        self.obs['self']['pos'] = self.baseline = [97,0,0]
        zone_cost = max(0, 97 + self.stats['radius'] + 4 - 100) * 9
        self.assertIs(self.choose(cost=zone_cost), self.baseline)
        self.assertEqual(self.bot.map.sweeps, [])

    def test_rotation_and_other_modes_are_unchanged(self):
        for mode in ('rotate', 'engage', 'position', 'loot'):
            with self.subTest(mode=mode):
                self.bot.mode = mode
                self.assertIs(self.choose(), self.baseline)
        self.assertEqual(self.bot.map.sweeps, [])

    def test_not_recovering_preserves_goal(self):
        self.bot.recover = False
        self.assertIs(self.choose(), self.baseline)

    def test_existing_route_beyond_eight_metres_is_preserved(self):
        self.baseline = [9,0,0]
        self.assertIs(self.choose(), self.baseline)
        self.assertEqual(self.bot.map.sweeps, [])

    def test_no_visible_threat_preserves_goal(self):
        self.threats[0]['los'] = False
        self.assertIs(self.choose(), self.baseline)

    def test_airborne_or_unavailable_geometry_cannot_authorize_ground_escape(self):
        self.obs['self']['grounded'] = False
        self.assertIs(self.choose(), self.baseline)
        self.obs['self']['grounded'] = True
        self.bot.map.available = False
        self.assertIs(self.choose(), self.baseline)
        self.assertEqual(self.bot.map.sweeps, [])

    def test_unscored_baseline_is_preserved(self):
        with patch('bot.time.perf_counter', return_value=0):
            goal = self.bot.recovery_escape_goal(self.obs, self.threats, self.stats,
                                                 self.baseline, None, 1)
        self.assertIs(goal, self.baseline)

    def test_insufficient_deadline_does_no_geometry_work(self):
        self.assertIs(self.choose(deadline=.0029), self.baseline)
        self.assertIs(self.choose(deadline=-1), self.baseline)
        self.assertEqual(self.bot.map.sweeps, [])

    def test_blocked_segments_never_receive_a_safety_score(self):
        with patch.object(self.bot.map, 'move_clear', return_value=False), \
                patch.object(self.bot, 'position_cost') as score:
            self.assertIs(self.choose(), self.baseline)
        score.assert_not_called()

    def test_no_better_safe_candidate_preserves_goal(self):
        with patch.object(self.bot, 'position_cost', return_value=self.cost - .5):
            self.assertIs(self.choose(), self.baseline)
        self.assertGreater(len(self.bot.map.sweeps), 0)

    def test_failed_goal_neighbourhoods_are_excluded(self):
        self.bot.failed_goals = [([24*math.cos(a), 24*math.sin(a), 0], 20)
                                 for a in (.6,-.6,1.2,-1.2,math.pi/2,-math.pi/2,0,math.pi)]
        self.assertIs(self.choose(), self.baseline)
        self.assertEqual(self.bot.map.sweeps, [])

    def test_search_uses_at_most_eight_full_sized_body_sweeps(self):
        self.stats.update(radius=3.5, height=12.6)
        self.choose()
        self.assertLessEqual(len(self.bot.map.sweeps), 8)
        self.assertTrue(all(radius == 3.5 and height == 12.6
                            for _, _, radius, height in self.bot.map.sweeps))

    def test_geometry_using_remaining_time_cannot_start_extra_scoring(self):
        clock = [0.0]
        def slow_sweep(*args):
            clock[0] = .003
            return True
        with patch('bot.time.perf_counter', side_effect=lambda:clock[0]), \
                patch.object(self.bot.map, 'move_clear', side_effect=slow_sweep), \
                patch.object(self.bot, 'position_cost') as score:
            goal = self.bot.recovery_escape_goal(self.obs, self.threats, self.stats,
                                                 self.baseline, self.cost, 1)
        self.assertIs(goal, self.baseline)
        score.assert_not_called()


class RecordedRecoveryEscapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT / 'check/stream.jsonl.gz', 'rt', encoding='utf-8') as stream:
            cls.config = json.loads(next(stream))['config']
        cls.fixture = json.loads((ROOT / 'tests/recovery_escape_fixture.json').read_text(encoding='utf-8'))
        cls.directory = tempfile.TemporaryDirectory(prefix='mechfight-recovery-')
        root = Path(cls.directory.name) / 'v2'
        root.mkdir()
        (root / 'world.json').write_text(json.dumps(cls.fixture['world']), encoding='utf-8')
        (root / 'terrain.i16').write_bytes(zlib.decompress(base64.b64decode(cls.fixture['terrain_zlib_base64'])))
        cls.arena = ArenaMap(cls.directory.name, cls.config)
        if not cls.arena.available:
            raise RuntimeError(cls.arena.error)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_case(self, timestamp):
        case = copy.deepcopy(next(c for c in self.fixture['cases'] if c['obs']['t'] == timestamp))
        bot = Bot.__new__(Bot)
        bot.config, bot.map = self.config, self.arena
        bot.mode, bot.recover, bot.last_hurt = case['mode'], True, case['last_hurt']
        bot.failed_goals = []
        obs = case['obs']; stats = bot.stats(obs['self']); threats = bot.threats(obs, stats)
        with patch('bot.time.perf_counter', return_value=0), \
                patch.object(self.arena, 'cover_candidates', return_value=case['cover']):
            with patch.object(bot, 'recovery_escape_goal', side_effect=lambda *args:args[3]):
                baseline = bot.safe_goal(obs, threats, stats, 1)
            goal = bot.safe_goal(obs, threats, stats, 1)
        self.assertLess(distance(baseline, case['baseline']), .001)
        return bot, obs, stats, threats, baseline, goal

    def test_captured_1177_escapes_exposed_hold_inside_same_future_circle(self):
        self.assert_recorded_escape(117.7, (140.106464,140.721269))

    def test_captured_1184_escapes_exposed_hold_inside_same_future_circle(self):
        self.assert_recorded_escape(118.4, (140.094673,141.199397))

    def assert_recorded_escape(self, timestamp, expected):
        bot, obs, stats, threats, baseline, goal = self.run_case(timestamp)
        center, radius = bot.zone_future(obs, 22)
        self.assertLess(distance(goal, expected), .01)
        self.assertGreater(distance(goal, baseline), 15)
        self.assertTrue(bot.map.move_clear(obs['self']['pos'], goal, stats['radius'], stats['height']))
        self.assertGreaterEqual(radius - distance(goal, center) - stats['radius'], 8 - 1e-8)
        args = (threats, center, radius, stats['radius'], True, stats['muzzle_height'])
        self.assertLess(bot.position_cost(goal, *args), bot.position_cost(baseline, *args) - 1)

    def test_captured_1215_does_not_force_a_worse_local_escape(self):
        _, _, _, _, baseline, goal = self.run_case(121.5)
        self.assertEqual(goal, baseline)


if __name__ == '__main__':
    unittest.main()
