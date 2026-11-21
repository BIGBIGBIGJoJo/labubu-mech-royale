"""Supply-drop contest memory, isolated from target/fire admission."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_strategy import FlatArena, official_fixture
import bot as policy


class DropMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = official_fixture()

    def setUp(self):
        self.obs = copy.deepcopy(self.recorded)
        self.obs.update(t=20.0, tick=400, offer=None)
        for key in ('mechs', 'events', 'cubes', 'crates', 'pickups', 'sounds', 'beams', 'projectiles'):
            self.obs[key] = []
        self.obs['self'].update(pos=[0, 0, 0], vel=[0, 0, 0], hp=500,
                                max_hp=1400, energy=100, cubes=0, grounded=True,
                                in_zone=True, stats=copy.deepcopy(self.hello['config']['mech']))
        self.obs['zone'] = dict(center=[0, 0], radius=560, next_center=[0, 0],
                                next_radius=380, shrink_start=60, shrink_end=110, dps=20)
        self.obs['drops'] = [dict(id=20001, pos=[50, 0, 0], radius=8,
                                  lands_in=0, capture_s=4, progress=0, holder=None)]
        with patch.object(policy, 'ArenaMap', FlatArena):
            self.bot = policy.Bot(copy.deepcopy(self.hello))
        self.bot.recover = True
        self.enemy_id = next(i for i in range(16) if i != self.obs['self']['id'])

    def actor(self, **kw):
        return dict(dict(id=self.enemy_id, kind='mech', pos=[50, 0, 0], vel=[0, 0, 0],
                         hp=500, max_hp=1400, cubes=0, weapons=['gun'], aim=[0, 0], charging=False), **kw)

    def remember(self, actor=None):
        self.obs['mechs'] = [actor or self.actor()]
        self.bot.update(self.obs)
        self.obs.update(t=20.1, tick=402)
        self.obs['mechs'] = []

    def goal(self, threats=None):
        return self.bot.resource_goal(self.obs, threats or [])

    def assert_drop(self, goal):
        self.assertIsNotNone(goal)
        self.assertEqual(goal[2], 'drop')

    def test_recent_missing_contestant_blocks_only_drop(self):
        self.remember()
        self.assertIsNone(self.goal())
        self.assertIsNone(self.bot.choose_target(self.obs, []))
        self.obs['cubes'] = [dict(id=5000, pos=[5, 0, 0])]
        self.bot.update(self.obs)
        self.assertEqual(self.goal()[2], 'cubes')

    def test_expiry_is_exactly_two_seconds(self):
        self.remember()
        self.obs['t'] = 21.999
        self.bot.update(self.obs)
        self.assertIsNone(self.goal())
        self.obs['t'] = 22.0
        self.bot.update(self.obs)
        self.assertEqual(self.bot.drop_mechs, {})
        self.assert_drop(self.goal())

    def test_current_actor_position_wins(self):
        self.remember()
        current = self.actor(pos=[500, 0, 0])
        self.obs['mechs'] = [current]
        # Even before update, a cached near position must not replace the list.
        self.assert_drop(self.goal([dict(actor=current, d=500, los=False, risk=.18)]))
        self.bot.update(self.obs)
        self.assertEqual(self.bot.drop_mechs[self.enemy_id][1]['pos'], (500, 0, 0))

    def test_current_listing_excluded_by_existing_filter_not_reintroduced(self):
        self.remember()
        self.obs['mechs'] = [self.actor()]
        self.assert_drop(self.goal([]))

    def test_kill_evicts_missing_record(self):
        self.remember()
        self.obs['events'] = [dict(type='kill', target=self.enemy_id)]
        self.bot.update(self.obs)
        self.assertNotIn(self.enemy_id, self.bot.drop_mechs)
        self.assert_drop(self.goal())

    def test_same_tick_kill_overrides_positive_hp_listing(self):
        self.remember()
        current = self.actor(pos=[100, 100, 0])
        self.obs['mechs'] = [current]
        self.obs['events'] = [dict(type='kill', target=self.enemy_id)]
        self.bot.update(self.obs)
        self.assertNotIn(self.enemy_id, self.bot.drop_mechs)
        with patch.object(self.bot.map, 'line_of_fire', return_value=False):
            self.assert_drop(self.goal([dict(actor=current, d=141, los=False, risk=.18)]))

    def test_dead_actor_purges_record_and_does_not_contest(self):
        self.remember()
        current = self.actor(hp=0, pos=[100, 100, 0])
        self.obs['mechs'] = [current]
        self.bot.update(self.obs)
        self.assertNotIn(self.enemy_id, self.bot.drop_mechs)
        with patch.object(self.bot.map, 'line_of_fire', return_value=False):
            self.assert_drop(self.goal([dict(actor=current, d=141, los=False, risk=.18)]))

    def test_optional_hp_is_not_invented_death(self):
        unknown = self.actor()
        unknown.pop('hp')
        self.remember(unknown)
        self.assertIn(self.enemy_id, self.bot.drop_mechs)
        self.assertIsNone(self.goal())
        self.obs['mechs'] = [unknown]
        self.assertIsNone(self.goal([dict(actor=unknown, d=50, los=True, risk=1)]))

    def test_npc_self_and_non_mech_id_not_cached(self):
        self.obs['mechs'] = [self.actor(id=100, kind='npc'),
                             self.actor(id=self.obs['self']['id']), self.actor(id=16)]
        self.bot.update(self.obs)
        self.assertEqual(self.bot.drop_mechs, {})

    def test_storage_is_bounded_by_documented_mech_ids(self):
        self.obs['mechs'] = [self.actor(id=i) for i in range(100)]
        self.bot.update(self.obs)
        self.assertLessEqual(len(self.bot.drop_mechs), 16)
        self.assertEqual(set(self.bot.drop_mechs), set(range(16)) - {self.obs['self']['id']})

    def test_observation_immutable_and_cached_position_detached(self):
        self.obs['mechs'] = [self.actor()]
        before = copy.deepcopy(self.obs)
        self.bot.update(self.obs)
        self.goal([dict(actor=self.obs['mechs'][0], d=50, los=True, risk=1)])
        self.assertEqual(self.obs, before)
        self.obs['mechs'][0]['pos'][0] = 999
        self.assertEqual(self.bot.drop_mechs[self.enemy_id][1]['pos'], (50, 0, 0))

    def test_new_instance_and_backward_time_do_not_reuse_old_record(self):
        self.remember()
        with patch.object(policy, 'ArenaMap', FlatArena):
            fresh = policy.Bot(copy.deepcopy(self.hello))
        self.assertEqual(fresh.drop_mechs, {})
        self.obs['t'] = 0
        self.bot.update(self.obs)
        self.assertEqual(self.bot.drop_mechs, {})


class RecordedDropMemoryTests(unittest.TestCase):
    def test_frozen_private_snapshot_disappearances_and_confirmed_kill(self):
        hello, _ = official_fixture()
        cases = json.loads((ROOT / 'tests/fixtures/drop_memory_cases.json').read_text())
        for case in cases:
            with self.subTest(case=case['name']):
                before, current = copy.deepcopy(case['previous']), copy.deepcopy(case['current'])
                original = copy.deepcopy((before, current))
                controller = policy.Bot(copy.deepcopy(hello))
                controller.recover = True
                controller.update(before)
                controller.update(current)
                threats = controller.threats(current, controller.stats(current['self']))
                actual = controller.resource_goal(current, threats)
                control = policy.Bot(copy.deepcopy(hello))
                control.recover = True
                control.update(current)
                without_prior = control.resource_goal(current, threats)
                self.assertIsNotNone(without_prior)
                self.assertEqual(without_prior[2], 'drop')
                if case['name'] == 'confirmed_kill':
                    self.assertIsNotNone(actual)
                    self.assertEqual(actual[2], 'drop')
                    self.assertNotIn(11, controller.drop_mechs)
                else:
                    self.assertIsNone(actual)
                self.assertEqual((before, current), original)


if __name__ == '__main__':
    unittest.main()
