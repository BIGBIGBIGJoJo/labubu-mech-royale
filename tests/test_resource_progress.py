"""Only attribute a resource blacklist to movement attempted for that resource."""
import copy
from collections import deque
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_strategy as fixtures


class ResourceProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon

    def history(self, key, intent=1., moving=False):
        self.bot.resource_history = deque((18+i*.1, (i*.3 if moving else 0., 0., 0.), intent, key)
                                         for i in range(20))

    def test_new_resource_is_not_charged_for_positioning_stall(self):
        self.history(None)
        self.bot.history = deque(x[:3] for x in self.bot.resource_history)
        self.bot.last_move = (1., 0.)
        self.obs['cubes'] = [{'id':5001, 'pos':[20, 0, 0]}]
        action = self.bot.act(self.obs)
        self.assertTrue(self.bot.telemetry['stuck'])
        self.assertTrue(action['jump'])  # Global unsticking behavior is unchanged.
        self.assertEqual(self.bot.resource_key, ('cubes',5001))
        self.assertNotIn(('cubes',5001), self.bot.blacklist)
        # The inherited stuck flag persists; one previous matching key is not enough.
        for i in range(1, 11):
            self.obs.update(t=20+i*.1, tick=400+i*2)
            self.bot.act(self.obs)
            self.assertTrue(self.bot.telemetry['stuck'])
            self.assertNotIn(('cubes',5001), self.bot.blacklist)

    def test_genuine_continuous_resource_failure_still_blacklists(self):
        key=('cubes',5001)
        self.history(key)
        self.bot.history = deque(x[:3] for x in self.bot.resource_history)
        self.bot.resource_key=key
        self.bot.last_move=(1.,0.)
        self.obs['cubes']=[{'id':5001,'pos':[20,0,0]}]
        action=self.bot.act(self.obs)
        self.assertEqual(self.bot.blacklist[key], 32.)
        self.assertTrue(action['jump'])

    def test_resource_switch_or_preemption_resets_attribution(self):
        key=('cubes',5001)
        self.history(key)
        self.assertFalse(self.bot.resource_progress_failed(('cubes',5002)))
        entries=list(self.bot.resource_history)
        entries[10]=(*entries[10][:3], None)
        self.bot.resource_history=deque(entries)
        self.assertFalse(self.bot.resource_progress_failed(key))

    def test_progress_or_no_movement_intent_does_not_count_as_failure(self):
        key=('cubes',5001)
        self.history(key,moving=True)
        self.assertFalse(self.bot.resource_progress_failed(key))
        self.history(key,intent=0)
        self.assertFalse(self.bot.resource_progress_failed(key))

    def test_update_attributes_observation_to_preceding_action(self):
        key=('cubes',5001)
        self.bot.resource_key=key
        self.bot.last_move=(.8,.6)
        self.bot.update(self.obs)
        self.bot.resource_key=('cubes',5002)
        self.assertEqual(self.bot.resource_history[-1][3],key)
        self.assertEqual(self.bot.resource_history[-1][2],1.)
        self.obs.update(t=23.,tick=460)
        self.bot.update(self.obs)
        self.assertEqual(len(self.bot.resource_history),1)


class CapturedResourceProgressTests(unittest.TestCase):
    def test_navcache_new_cube_and_followup_do_not_inherit_old_stall(self):
        data=json.loads((Path(__file__).parent/'fixtures/navcache_resource_66_6.json').read_text())
        hello=copy.deepcopy(data['hello'])
        hello['map']['dir']=str(fixtures.ROOT/'arena')
        bot=fixtures.policy.Bot(hello)
        if not bot.map.available:
            self.skipTest('real arena not mounted')
        bot.history=deque((t,tuple(pos),intent) for t,pos,intent,key in data['history'])
        bot.resource_history=deque((t,tuple(pos),intent,tuple(key) if key else None)
                                   for t,pos,intent,key in data['history'])
        bot.last_move=tuple(data['last_move'])
        first=data['observations'][0]
        goal=next(c['pos'] for c in first['cubes'] if c['id']==5040)
        stats=bot.stats(first['self'])
        self.assertTrue(bot.map.point_clear(goal,stats['radius'],stats['height']))
        self.assertTrue(bot.map.move_clear(first['self']['pos'],goal,stats['radius'],stats['height']))
        # Isolate blacklist attribution from optional scoring budget; full-budget
        # prefix replay is a separate Linux validation artifact.
        original=bot.resource_goal
        with patch.object(bot,'resource_goal',side_effect=lambda obs, threats, deadline=None:
                          original(obs,threats,deadline=None)):
            for i,obs in enumerate(data['observations']):
                bot.act(copy.deepcopy(obs))
                if i==0:
                    self.assertTrue(bot.telemetry['stuck'])
                self.assertEqual(bot.resource_key,('cubes',5040))
                self.assertNotIn(('cubes',5040),bot.blacklist)


if __name__=='__main__':unittest.main()
