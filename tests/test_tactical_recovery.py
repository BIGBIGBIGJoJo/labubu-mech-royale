"""Recover candidate starvation without relaxing collision or hazard checks."""
import base64
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from arena_map import ArenaMap
from tactical import TacticalPlanner


class Corridor:
    def __init__(self,end=4.0,width=.3):
        self.end,self.width=end,width
        self.sweeps=[]

    def ground_height(self,x,y):return 0.0
    def support_height(self,x,y,z):return 0.0
    def line_of_fire(self,start,end):return True
    def point_clear(self,p,radius,height):return -.1<=p[0]<=self.end and abs(p[1])<=self.width
    def move_clear(self,start,end,radius,height):
        self.sweeps.append((tuple(start),tuple(end),radius,height))
        return self.point_clear(start,radius,height) and self.point_clear(end,radius,height)


class TacticalRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT/'check/stream.jsonl.gz','rt',encoding='utf-8') as stream:
            cls.config=json.loads(next(stream))['config']

    def setUp(self):
        self.stats=dict(self.config['mech'])
        self.map=Corridor()
        self.planner=TacticalPlanner(self.config,self.map)
        self.me={'pos':[0.,0.,0.],'vel':[0.,0.,0.],'energy':100.,'grounded':True,
                 'weapons':[{'kind':'gun','cooldown':0,'ammo':12},None]}
        self.obs={'tick':100,'t':5.,'self':self.me,'projectiles':[],
                  'zone':{'center':[0,0],'radius':500,'next_center':[0,0],
                          'next_radius':400,'shrink_start':60,'shrink_end':110,'dps':20}}

    def choose(self,nav=(1,0),threats=None,**kwargs):
        with patch('tactical.time.perf_counter',return_value=0):
            return self.planner.choose(self.obs,nav,threats or [],self.stats,goal=[50,0,0],deadline=1,**kwargs)

    def test_real_geometry_failure_enables_next_slow_candidate(self):
        first=self.choose()
        self.assertEqual(first,((0.,0.),False))
        self.assertTrue(self.planner.last_report['fallback'])
        direction,boost=self.choose()
        self.assertEqual(direction,(.5,0.))
        self.assertFalse(boost)
        self.assertFalse(self.planner.last_report['fallback'])
        self.assertTrue(self.planner.last_report['recovery_seed_selected'])
        self.assertLessEqual(self.planner.last_report['geometry_checked'],6)

    def test_seed_holds_priority_until_an_ordinary_candidate_can_win(self):
        self.planner._geometry_recovery_pending=True
        self.choose()
        self.assertTrue(self.planner._geometry_recovery_pending)
        self.map.end=100
        self.choose()
        self.assertFalse(self.planner.last_report['recovery_seed_selected'])
        self.assertFalse(self.planner._geometry_recovery_pending)

    def test_fully_blocked_body_stays_neutral_across_retries(self):
        self.map.end=-1
        for _ in range(4):
            self.assertEqual(self.choose(),((0.,0.),False))
            self.assertTrue(self.planner.last_report['fallback'])
            self.assertLessEqual(self.planner.last_report['geometry_checked'],6)

    def test_no_navigation_clears_recovery_priority(self):
        self.planner._geometry_recovery_pending=True
        self.assertEqual(self.choose(nav=(0,0)),((0.,0.),False))
        self.assertFalse(self.planner.last_report['recovery_seed_checked'])
        self.assertFalse(self.planner._geometry_recovery_pending)

    def test_deliberately_selected_neutral_does_not_start_recovery(self):
        self.choose(nav=(0,0))
        self.assertFalse(self.planner.last_report['fallback'])
        self.assertFalse(self.planner._geometry_recovery_pending)

    def test_airborne_actor_has_no_grounded_recovery_priority(self):
        self.me['grounded']=False
        self.me['pos'][2]=20
        self.planner._geometry_recovery_pending=True
        self.choose()
        self.assertFalse(self.planner.last_report['recovery_seed_checked'])
        self.assertFalse(self.planner._geometry_recovery_pending)

    def test_expired_deadline_never_checks_or_selects_seed(self):
        self.planner._geometry_recovery_pending=True
        self.assertEqual(self.planner.choose(self.obs,(1,0),[],self.stats,deadline=time.perf_counter()-1),((0.,0.),False))
        self.assertEqual(self.map.sweeps,[])
        self.assertFalse(self.planner.last_report['recovery_seed_checked'])

    def test_deadline_during_sweep_cannot_authorize_partial_validation(self):
        self.planner._geometry_recovery_pending=True
        clock=[0.0]
        def sweep(*args):
            clock[0]=1.0
            return True
        with patch('tactical.time.perf_counter',side_effect=lambda:clock[0]),patch.object(self.map,'move_clear',side_effect=sweep):
            result=self.planner.choose(self.obs,(1,0),[],self.stats,deadline=1)
        self.assertEqual(result,((0.,0.),False))
        self.assertFalse(self.planner.last_report['recovery_seed_selected'])

    def test_incoming_projectile_can_make_braking_better(self):
        self.planner._geometry_recovery_pending=True
        self.obs['projectiles']=[{'kind':'gun','pos':[5,-40,4.5],'vel':[0,80,0]}]
        self.choose()
        self.assertTrue(self.planner.last_report['recovery_seed_checked'])
        self.assertFalse(self.planner.last_report['recovery_seed_selected'])

    def test_aimed_charging_beam_can_reject_seed(self):
        self.planner._geometry_recovery_pending=True
        actor={'id':2,'kind':'mech','pos':[4.5,-50,0],'vel':[0,0,0],
               'weapons':['laser'],'cubes':0,'charging':True,'aim':[math.pi/2,0]}
        self.choose(threats=[{'actor':actor,'d':50,'los':True}])
        self.assertFalse(self.planner.last_report['recovery_seed_selected'])

    def test_outward_zone_crossing_can_reject_seed(self):
        self.planner._geometry_recovery_pending=True
        self.obs['zone'].update(radius=4.5,next_radius=4.5,dps=300)
        self.choose()
        self.assertFalse(self.planner.last_report['recovery_seed_selected'])

    def test_current_momentum_is_not_replaced_with_stationary_start(self):
        self.planner._geometry_recovery_pending=True
        self.me['pos'][0]=2.5
        self.me['vel'][0]=19.5
        self.choose()
        self.assertFalse(self.planner.last_report['recovery_seed_selected'])
        self.assertTrue(any(end[0]>self.map.end for _,end,_,_ in self.map.sweeps))

    def test_charge_and_scaled_body_are_checked_on_seed(self):
        self.planner._geometry_recovery_pending=True
        self.stats.update(radius=3.25,height=11.7,charge_move_mult=.35)
        self.me['weapons'][1]={'kind':'laser','charge':.2}
        geometries=[]
        original=self.planner._geometry
        def record(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            geometries.append((args[2],result))
            return result
        with patch.object(self.planner,'_geometry',side_effect=record):self.choose()
        direction,path=geometries[0]
        self.assertEqual(direction,(.5,0.))
        self.assertAlmostEqual(path[-1][4],self.stats['walk_speed']*.5*.35)
        self.assertTrue(all(radius==3.25 and height==11.7 for _,_,radius,height in self.map.sweeps))

    def test_stationary_geometry_shortcut_keeps_full_horizon_and_body_check(self):
        path=self.planner.rollout(self.me,(0,0),False,self.stats)
        corrected=self.planner._geometry(path,self.stats,float('inf'),(0,0),False,False)
        self.assertEqual(len(corrected),self.planner.steps+1)
        self.assertEqual(len(self.map.sweeps),1)
        self.assertEqual(corrected[-1][0],self.planner.horizon)
        self.map.end=-1
        self.assertIsNone(self.planner._geometry(path,self.stats,float('inf'),(0,0),False,False))

    def test_stationary_geometry_energy_matches_existing_integrator(self):
        self.me['energy']=31.4
        self.me['weapons'][1]={'kind':'laser','charge':.2}
        # Even a boost flag cannot drain energy with zero movement input.
        path=self.planner.rollout(self.me,(0,0),True,self.stats)
        corrected=self.planner._geometry(path,self.stats,float('inf'),(0,0),True,True)
        self.assertEqual([state[7] for state in corrected],[state[7] for state in path])
        self.assertTrue(all(state[7]==31.4 for state in corrected))

    def test_repeated_actual_controller_inputs_do_not_assume_unissued_braking(self):
        self.map.end=12
        self.planner._geometry_recovery_pending=True
        start=tuple(self.me['pos'])
        for _ in range(45):
            direction,boost=self.choose()
            path=self.planner.rollout(self.me,direction,boost,self.stats)
            applied=self.planner._geometry(path[:3],self.stats,float('inf'),direction,boost,False)
            self.assertIsNotNone(applied)
            state=applied[-1]
            self.me.update(pos=list(state[1:4]),vel=list(state[4:7]),energy=state[7],grounded=state[8])
            self.obs['tick']+=2;self.obs['t']+=.1
        self.assertGreater(self.me['pos'][0]-start[0],6)
        self.assertLessEqual(self.me['pos'][0],self.map.end)


class CapturedTacticalRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT/'check/stream.jsonl.gz','rt',encoding='utf-8') as stream:
            cls.config=json.loads(next(stream))['config']
        cls.fixture=json.loads((ROOT/'tests/tactical_recovery_fixture.json').read_text())
        cls.directory=tempfile.TemporaryDirectory(prefix='mechfight-tactical-recovery-')
        root=Path(cls.directory.name)/'v2';root.mkdir()
        (root/'world.json').write_text(json.dumps(cls.fixture['world']))
        (root/'terrain.i16').write_bytes(zlib.decompress(base64.b64decode(cls.fixture['terrain_zlib_base64'])))
        cls.arena=ArenaMap(cls.directory.name,cls.config)
        if not cls.arena.available:raise RuntimeError(cls.arena.error)

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def check_case(self,timestamp):
        case=copy.deepcopy(next(case for case in self.fixture['cases'] if case['obs']['t']==timestamp))
        planner=TacticalPlanner(self.config,self.arena)
        # The preceding captured decision returned neutral with fallback=True.
        planner._geometry_recovery_pending=True
        with patch('tactical.time.perf_counter',return_value=0):
            direction,boost=planner.choose(case['obs'],case['navigation'],case['threats'],case['stats'],
                goal=case['goal'],recover=case['recover'],urgent=case['urgent'],deadline=1)
        self.assertGreater(math.hypot(*direction),.1)
        self.assertFalse(boost)
        self.assertFalse(planner.last_report['fallback'])
        self.assertTrue(planner.last_report['recovery_seed_checked'])
        self.assertLessEqual(planner.last_report['geometry_checked'],6)
        path=planner.rollout(case['obs']['self'],direction,boost,case['stats'])
        self.assertIsNotNone(planner._geometry(path,case['stats'],float('inf'),direction,boost,False))
        return case,planner,direction

    def test_captured_90_has_valid_movement_despite_old_candidate_starvation(self):
        case,planner,_=self.check_case(90)
        path=planner.rollout(case['obs']['self'],case['navigation'],False,case['stats'])
        self.assertIsNotNone(planner._geometry(path,case['stats'],float('inf'),case['navigation'],False,False))

    def test_captured_103_retains_fractional_input_through_full_body_sweep(self):
        case,planner,direction=self.check_case(103)
        self.assertAlmostEqual(math.hypot(*direction),.5)
        full=planner.rollout(case['obs']['self'],case['navigation'],False,case['stats'])
        self.assertIsNone(planner._geometry(full,case['stats'],float('inf'),case['navigation'],False,False))

    def test_captured_118_keeps_zone_cost_while_making_valid_progress(self):
        case,planner,direction=self.check_case(118)
        path=planner.rollout(case['obs']['self'],direction,False,case['stats'])
        self.assertAlmostEqual(math.hypot(*direction),.5)
        self.assertGreater(planner._zone_cost(path,case['obs'],case['stats']),50)


if __name__=='__main__':unittest.main()
