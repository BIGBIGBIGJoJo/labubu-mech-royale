"""Recent observed approach can disambiguate a return from a real stall."""
import copy
from collections import deque
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_strategy as fixtures


class RecentResourceProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon

    def returning(self, key, end=20., x=0., intent=1.):
        # A two-second out-and-back path has little endpoint displacement,
        # but its final 0.4 seconds approach the current goal by 2 metres.
        self.bot.resource_history = deque(
            (end-2+i*.1, (x-(i*.5 if i<=10 else (20-i)*.5),0.,0.),intent,key)
            for i in range(21))

    def test_continuing_approach_has_grace_and_renews_after_net_progress(self):
        key=('cubes',5001);goal=(20.,0.,0.)
        for t,x in ((20.,0.),(20.1,.5),(20.2,1.),(20.4,2.),(20.5,2.5)):
            self.returning(key,t,x)
            self.assertFalse(self.bot.resource_progress_failed(key,goal),t)
        self.assertAlmostEqual(self.bot.resource_progress_veto[1][0],2.5)

    def test_periodic_out_and_back_cannot_renew_without_new_progress(self):
        key=('cubes',5001);goal=(20.,0.,0.)
        self.returning(key)
        self.assertFalse(self.bot.resource_progress_failed(key,goal))
        self.returning(key,22.)
        self.assertTrue(self.bot.resource_progress_failed(key,goal))

    def test_a_stopped_bot_cannot_keep_grace_from_movement_intent(self):
        key=('cubes',5001);goal=(20.,0.,0.)
        self.returning(key)
        self.assertFalse(self.bot.resource_progress_failed(key,goal))
        self.bot.resource_history=deque((18.1+i*.1,(0.,0.,0.),1.,key) for i in range(21))
        self.assertTrue(self.bot.resource_progress_failed(key,goal))
        self.returning(key,intent=0.)
        self.assertFalse(self.bot.resource_progress_failed(key,goal))

    def test_preemption_clears_veto_and_new_identity_has_its_own_grace(self):
        key=('cubes',5001);goal=(20.,0.,0.)
        self.returning(key)
        self.assertFalse(self.bot.resource_progress_failed(key,goal))
        self.bot.resource_key=None
        self.bot.update(self.obs)
        self.assertIsNone(self.bot.resource_progress_veto)
        other=('cubes',5002)
        self.returning(other,22.)
        self.assertFalse(self.bot.resource_progress_failed(other,goal))
        self.assertEqual(self.bot.resource_progress_veto[0],other)

    def test_current_goal_is_used_for_all_observed_positions(self):
        key=('npc',101)
        self.returning(key)
        self.assertTrue(self.bot.resource_progress_failed(key,(-20.,0.,0.)))
        self.assertFalse(self.bot.resource_progress_failed(key,(20.,0.,0.)))


class CapturedRecentResourceProgressTests(unittest.TestCase):
    def fixture(self,name):
        data=json.loads((Path(__file__).parent/'fixtures'/name).read_text())
        hello=copy.deepcopy(data['hello']);hello['map']['dir']=str(fixtures.ROOT/'arena')
        bot=fixtures.policy.Bot(hello)
        if not bot.map.available:self.skipTest('real arena not mounted')
        bot.history=deque((t,tuple(pos),intent) for t,pos,intent,key in data['history'])
        bot.resource_history=deque((t,tuple(pos),intent,tuple(key) if key else None)
                                  for t,pos,intent,key in data['history'])
        bot.resource_key=tuple(data['resource_key']) if data['resource_key'] else None
        bot.last_move=tuple(data['last_move']);bot.blacklist={tuple(k):v for k,v in data['blacklist']}
        bot.last_jump=data['last_jump']
        return bot,data

    def test_rotation_return_and_consecutive_recorded_followups_keep_cube(self):
        bot,data=self.fixture('rotation_returning_22_4.json');key=('cubes',5008)
        first=data['observations'][0];goal=next(x['pos'] for x in first['cubes'] if x['id']==5008)
        s=bot.stats(first['self'])
        self.assertTrue(bot.map.move_clear(first['self']['pos'],goal,s['radius'],s['height']))
        original=bot.resource_goal
        with patch.object(bot,'resource_goal',side_effect=lambda obs,threats,deadline=None:
                          original(obs,threats,deadline=None)):
            for i,obs in enumerate(data['observations']):
                action=bot.act(copy.deepcopy(obs))
                if i==0:
                    self.assertTrue(bot.telemetry['stuck'])
                    self.assertIsNotNone(bot.resource_progress_veto)
                    self.assertEqual(action['jump'],data['recorded'][0]['data']['jump'])
                self.assertEqual(bot.resource_key,key)
                self.assertNotIn(key,bot.blacklist)

    def test_spacing_blocked_drop_still_blacklists(self):
        bot,data=self.fixture('spacing_blocked_77.json');key=('drop',20001)
        first=data['observations'][0];goal=next(x['pos'] for x in first['drops'] if x['id']==20001)
        s=bot.stats(first['self'])
        self.assertFalse(bot.map.move_clear(first['self']['pos'],goal,s['radius'],s['height']))
        original=bot.resource_goal
        with patch.object(bot,'resource_goal',side_effect=lambda obs,threats,deadline=None:
                          original(obs,threats,deadline=None)):
            action=bot.act(copy.deepcopy(first))
        self.assertTrue(bot.telemetry['stuck'])
        self.assertEqual(bot.blacklist[key],89.)
        self.assertTrue(action['jump'])
        self.assertIsNone(bot.resource_progress_veto)


if __name__=='__main__':unittest.main()
