"""Recovery-only directional exposure and an actual recorded cover fixture."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bot as policy
from arena_map import ArenaMap
from test_strategy import FlatArena, official_fixture

FIXTURES = json.loads((ROOT/'tests/fixtures/recovery_c1.json').read_text(encoding='utf-8'))


class RecoveryCoverUnitTests(unittest.TestCase):
    def setUp(self):
        hello, _ = official_fixture()
        with patch.object(policy, 'ArenaMap', FlatArena):
            self.bot = policy.Bot(hello)
        self.obs = copy.deepcopy(FIXTURES[0])
        self.me = self.obs['self']
        self.me.update(pos=[0,0,0], cubes=0, stats=dict(hello['config']['mech']))
        self.stats = self.bot.stats(self.me)
        self.actor = {'id':10,'kind':'mech','pos':[100,0,0], 'cubes':0,'weapons':['gun','laser']}
        self.threats = [dict(actor=self.actor,d=100,los=False,risk=.18)]

    @staticmethod
    def low_wall(a,b):
        fraction = (5-a[0])/(b[0]-a[0])
        return not (0<=fraction<=1 and a[2]+fraction*(b[2]-a[2])<=7.5)

    def score(self, recovering=True, **kwargs):
        return self.bot.position_cost(self.me['pos'], self.threats,[0,0],500,
            self.stats['radius'],recovering,self.stats['muzzle_height'],
            me=self.me,effective_stats=self.stats,**kwargs)

    def test_outgoing_blockage_is_not_recovery_protection(self):
        with patch.object(self.bot.map,'line_of_fire',side_effect=self.low_wall):
            self.assertEqual(self.score(recovering=False),0)
            self.assertGreater(self.score(recovering=True),0)
        self.assertTrue(self.bot._last_recovery_samples[0]['visible'])
        self.assertEqual(self.bot._last_recovery_samples[0]['rays'],1)

    def test_deadline_and_ray_budget_uncertainty_keep_risk(self):
        with patch.object(self.bot.map,'line_of_fire',return_value=False):
            self.assertGreater(self.score(deadline=0),0)
            self.assertIsNone(self.bot._last_recovery_samples[0]['visible'])
            self.bot.recovery_exposure.begin_frame(1,ray_budget=2)
            self.assertGreater(self.score(),0)
            self.assertIsNone(self.bot._last_recovery_samples[0]['visible'])
            self.bot.recovery_exposure.begin_frame(2,ray_budget=4)
            self.assertEqual(self.score(),0)
            self.assertFalse(self.bot._last_recovery_samples[0]['visible'])

    def test_missing_body_state_does_not_produce_protection(self):
        with patch.object(self.bot.map,'line_of_fire',return_value=False):
            cost=self.bot.position_cost([0,0,0],self.threats,[0,0],500,2.5,True,7)
        self.assertGreater(cost,0)
        self.assertIsNone(self.bot._last_recovery_samples[0]['visible'])

    def test_clear_center_stops_before_additional_body_samples(self):
        with patch.object(self.bot.map,'line_of_fire',return_value=True) as ray:
            self.assertGreater(self.score(),0)
        self.assertEqual(ray.call_count,1)

    def test_bounded_scans_reach_late_cover_and_recheck_previous_goal(self):
        bot=self.bot;bot.recover=True;bot.mode='recover'
        points=[[x,0,0] for x in range(20,181,20)]
        clock=[100.];seen=[]
        def expensive_score(point,*args,**kwargs):
            clock[0]+=.001
            seen.append(point[0])
            covered=point[0]>=120
            bot._last_recovery_samples=[dict(id=10,visible=not covered,rays=1,reasons=[])]
            return 0 if covered else 100
        with patch.object(bot.map,'cover_candidates',return_value=points), \
                patch.object(bot,'position_cost',side_effect=expensive_score), \
                patch('bot.time.perf_counter',side_effect=lambda:clock[0]):
            goals=[]
            for i in range(4):
                clock[0]=100.;self.obs.update(t=95+i,tick=1900+20*i)
                goal=bot.safe_goal(self.obs,[],self.stats,100.0035)
                goals.append(goal)
                bot.goal=list(goal);bot.goal_kind='recover'
        self.assertEqual(goals[0],[0,0,0], 'Late cover is outside the first bounded pass')
        self.assertTrue(any(g[0]>=120 for g in goals[1:]))
        self.assertGreater(seen.count(120),1, 'Previously selected cover must be reevaluated')

    def test_unresolved_candidate_is_not_skipped_by_rotating_scan(self):
        bot=self.bot;bot.recover=True;bot.mode='recover'
        points=[[20,0,0],[40,0,0]]
        def unresolved(point,*args,**kwargs):
            partial=point[0]==20
            bot._last_recovery_samples=[dict(id=10,visible=None if partial else True,
                                            rays=1,reasons=['deadline'] if partial else [])]
            return 100
        with patch.object(bot.map,'cover_candidates',return_value=points), \
                patch.object(bot,'position_cost',side_effect=unresolved), \
                patch('bot.time.perf_counter',return_value=100):
            bot.safe_goal(self.obs,[],self.stats,101)
        self.assertEqual(bot._recovery_scan_cursor,0)
        self.assertEqual(bot.recovery_cover_report['scanned'],0)


class RecordedRecoveryCoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello,_=official_fixture()
        cls.map=ArenaMap(str(ROOT/'arena'),cls.hello['config'])
        assert cls.map.available,cls.map.error

    def make_bot(self):
        with patch.object(policy,'ArenaMap',return_value=self.map):
            bot=policy.Bot(copy.deepcopy(self.hello))
        bot.recover=True
        return bot

    def test_recorded_false_shelter_stays_exposed_at_95_97_101_102_seconds(self):
        bot=self.make_bot()
        for obs in FIXTURES:
            with self.subTest(t=obs['t']):
                stats=bot.stats(obs['self']);threats=bot.threats(obs,stats)
                center,radius=bot.zone_future(obs,22)
                bot.recovery_exposure.begin_frame(obs['tick'],ray_budget=64)
                cost=bot.position_cost(obs['self']['pos'],threats,center,radius,stats['radius'],
                    True,stats['muzzle_height'],me=obs['self'],effective_stats=stats)
                self.assertGreater(cost,0)
                self.assertTrue(any(r['visible'] for r in bot._last_recovery_samples))

    def test_existing_online_generator_offers_directly_reachable_cover(self):
        bot=self.make_bot();obs=copy.deepcopy(FIXTURES[0]);me=obs['self'];stats=bot.stats(me)
        center,radius=bot.zone_future(obs,22)
        # Remove wall-clock variance for this static geometry/12-candidate test;
        # the real runtime budget is separately checked in the Linux replay.
        with patch('arena_map.time.perf_counter',return_value=100):
            points=bot.map.cover_candidates(me['pos'],center,radius,stats['radius'],stats['height'],limit=12,deadline=101)
        self.assertEqual(len(points),12)
        actor=next(a for a in obs['mechs'] if a['id']==10)
        reachable=[]
        for point in points:
            result=bot.recovery_exposure.incoming(me,actor,position=point,effective_stats=stats,
                                                 max_rays=4,include_width=True)
            if result.visible is False and bot.map.move_clear(me['pos'],point,stats['radius'],stats['height']):
                reachable.append(point)
        self.assertTrue(reachable)
        self.assertTrue(any(abs(point[0]+11.07206651122492)<1.e-6 for point in reachable))

    def test_safe_goal_selects_protected_online_candidate_over_false_shelter(self):
        bot=self.make_bot();obs=copy.deepcopy(FIXTURES[0]);stats=bot.stats(obs['self'])
        threats=bot.threats(obs,stats)
        bot.recovery_exposure.begin_frame(obs['tick'],ray_budget=64)
        with patch('arena_map.time.perf_counter',return_value=100):
            goal=bot.safe_goal(obs,threats,stats,101)
        self.assertNotEqual(list(goal),obs['self']['pos'])
        self.assertTrue(bot.map.move_clear(obs['self']['pos'],goal,stats['radius'],stats['height']))
        self.assertTrue(bot.map.point_clear(goal,stats['radius'],stats['height']))
        self.assertTrue(any(q['visible'] for q in bot.recovery_cover_report['origin']['samples']))
        self.assertTrue(all(q['visible'] is False for q in bot.recovery_cover_report['selected']['samples']))


if __name__=='__main__':unittest.main()
