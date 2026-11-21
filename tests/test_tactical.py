"""Causal trajectory-controller checks, not a match-strength benchmark."""
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tactical import TacticalPlanner,accelerate


class FlatMap:
    def ground_height(self,x,y):
        return 0.0

    def support_height(self,x,y,z):
        return 0.0

    def move_clear(self,start,end,radius,height):
        return True

    def point_clear(self,pos,radius,height):
        return True

    def line_of_fire(self,start,end):
        return True


class WallMap(FlatMap):
    """A wall at x=5.5; a radius2.5 mech center must remain at x<=3."""
    def point_clear(self,pos,radius,height):
        return pos[0]+radius<=5.5

    def move_clear(self,start,end,radius,height):
        return max(start[0],end[0])+radius<=5.5


class TacticalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT/'check/stream.jsonl.gz','rt',encoding='utf-8') as stream:
            cls.config=json.loads(next(stream))['config']

    def setUp(self):
        self.stats=dict(self.config['mech'])
        self.planner=TacticalPlanner(self.config,FlatMap())
        self.me={'pos':[0.,0.,0.],'vel':[0.,0.,0.],'energy':100.,'grounded':True,
                 'weapons':[{'kind':'gun','cooldown':0,'ammo':12,'stats':dict(self.config['weapons']['gun'])},None]}
        self.obs={'tick':100,'t':5.,'self':self.me,'projectiles':[],
                  'zone':{'center':[0,0],'radius':500,'next_center':[0,0],
                          'next_radius':400,'shrink_start':60,'shrink_end':110,'dps':20}}

    def test_vector_acceleration_is_not_axis_acceleration(self):
        vx,vy=accelerate(0,0,11.7,11.7,2.925)
        self.assertAlmostEqual(math.hypot(vx,vy),2.925)
        self.assertAlmostEqual(vx,vy)

    def test_startup_two_frames_matches_recorded_movement(self):
        direction=(.107,.994258)
        length=math.hypot(*direction)
        path=self.planner.rollout(self.me,tuple(v/length for v in direction),False,self.stats)
        state=path[2]
        # Actual private trace tick2->4: displacement(.05,.44), velocity(.63,5.82).
        self.assertAlmostEqual(state[1],.05,delta=.01)
        self.assertAlmostEqual(state[2],.44,delta=.01)
        self.assertAlmostEqual(state[4],.63,delta=.01)
        self.assertAlmostEqual(state[5],5.82,delta=.01)

    def test_braking_has_nonzero_stopping_distance(self):
        self.me['vel']=[19.5,0,0]
        path=self.planner.rollout(self.me,(0,0),False,self.stats)
        self.assertGreater(path[-1][1],2.5)
        self.assertAlmostEqual(path[-1][4],0)

    def test_boost_uses_live_speed_and_drains_live_energy(self):
        path=self.planner.rollout(self.me,(1,0),True,self.stats)
        self.assertAlmostEqual(path[-1][4],self.stats['boost_speed'])
        self.assertAlmostEqual(path[-1][7],100-self.stats['boost_drain']*self.planner.horizon)

    def test_laser_charge_reduces_movement_speed(self):
        self.me['weapons'][1]={'kind':'laser','charge':.2}
        path=self.planner.rollout(self.me,(1,0),False,self.stats)
        self.assertAlmostEqual(path[-1][4],self.stats['walk_speed']*self.stats['charge_move_mult'])

    def test_swept_projectile_hits_between_observation_samples(self):
        path=self.planner.rollout(self.me,(0,0),False,self.stats)
        points=[(-5+252*s[0],0,4.5) for s in path]
        self.assertAlmostEqual(self.planner._swept_distance(path,points,9),0)

    def test_overhead_projectile_does_not_trigger_ground_dodge(self):
        path=self.planner.rollout(self.me,(0,0),False,self.stats)
        points=[(-5+252*s[0],0,30) for s in path]
        self.assertTrue(math.isinf(self.planner._swept_distance(path,points,9)))

    def test_wall_validation_checks_inertial_arc(self):
        self.me['vel']=[19.5,0,0]
        self.planner.map=WallMap()
        north=self.planner.rollout(self.me,(0,1),False,self.stats)
        brake=self.planner.rollout(self.me,(-1,0),False,self.stats)
        self.assertIsNone(self.planner._geometry(north,self.stats,time.perf_counter()+1))
        self.assertIsNotNone(self.planner._geometry(brake,self.stats,time.perf_counter()+1))

    def test_mortar_near_ground_impact_is_a_threat(self):
        self.obs['projectiles']=[{'kind':'mortar','pos':[0,0,10],'vel':[0,0,-20]}]
        tracks=self.planner._projectiles(self.obs,time.perf_counter()+1)
        self.assertIsNotNone(tracks[0]['impact'])
        path=self.planner.rollout(self.me,(0,0),False,self.stats)
        self.assertGreater(self.planner.projectile_cost(path,tracks,self.stats),100)

    def test_zone_cost_integrates_shrink_over_trajectory(self):
        self.obs['zone'].update(radius=10,next_radius=0,shrink_start=5,shrink_end=5.6,dps=100)
        path=self.planner.rollout(self.me,(1,0),False,self.stats)
        self.assertGreater(self.planner._zone_cost(path,self.obs,self.stats),10)

    def test_expired_budget_returns_finite_braking_action(self):
        self.planner._recovery_origin=(0,0)
        direction,boost=self.planner.choose(self.obs,(1,0),[],self.stats,deadline=time.perf_counter()-1)
        self.assertEqual(direction,(0,0))
        self.assertFalse(boost)
        self.assertIsNone(self.planner._recovery_origin)

    def test_unobstructed_goal_makes_progress(self):
        direction,boost=self.planner.choose(self.obs,(1,0),[],self.stats,goal=[50,0,0],deadline=time.perf_counter()+1)
        self.assertGreater(direction[0],.9)

    def test_current_occlusion_does_not_reduce_intrinsic_strength(self):
        actor={'id':3,'kind':'mech','pos':[50,0,0],'weapons':['gun'],'cubes':0}
        self.assertGreater(self.planner._strength(actor,50),self.planner._strength(actor,150))

    def test_expensive_failed_boost_cannot_repeatedly_starve_legal_walk(self):
        clock=[100.0]
        class ExpensiveWall(FlatMap):
            def move_clear(self,start,end,radius,height):
                clock[0]+=.00065
                return max(start[0],end[0])<=7.0
        self.planner.map=ExpensiveWall()
        with patch('tactical.time.perf_counter',side_effect=lambda:clock[0]):
            first=self.planner.choose(self.obs,(1,0),[],self.stats,goal=[50,0,0],urgent=True)
            self.assertEqual(first,((0.0,0.0),False))
            self.assertTrue(self.planner.last_report['fallback'])
            for i in range(3):
                self.obs['t']+=.1
                started=clock[0]
                direction,boost=self.planner.choose(self.obs,(1,0),[],self.stats,goal=[50,0,0],urgent=True)
                self.assertEqual(direction,(1.0,0.0))
                self.assertFalse(boost)
                self.assertTrue(self.planner.last_report['walk_checked_first'])
                self.assertFalse(self.planner.last_report['fallback'])
                self.assertLess(clock[0]-started,.014)

    def test_navigation_recovery_ends_after_observed_progress(self):
        self.planner._recovery_origin=(0,0)
        self.me['pos']=[1.4,0,0]
        self.planner.choose(self.obs,(1,0),[],self.stats,goal=[50,0,0])
        self.assertFalse(self.planner.last_report['navigation_recovery'])

    def test_navigation_recovery_ends_when_destination_is_reached(self):
        self.planner._recovery_origin=(0,0)
        self.planner.choose(self.obs,(0,0),[],self.stats,goal=[0,0,0])
        self.assertFalse(self.planner.last_report['navigation_recovery'])

    def test_navigation_recovery_uses_changed_intent_not_previous_direction(self):
        self.planner._recovery_origin=(0,0)
        self.planner.last_direction=(1,0)
        checked=[]
        original=self.planner._geometry
        def capture(*args,**kwargs):
            checked.append(args[3])
            return original(*args,**kwargs)
        with patch.object(self.planner,'_geometry',side_effect=capture):
            self.planner.choose(self.obs,(0,1),[],self.stats,goal=[0,50,0],urgent=True)
        self.assertEqual(checked[0],(0,1))

    def test_validated_stop_clears_navigation_recovery(self):
        self.planner._recovery_origin=(0,0)
        self.obs['zone'].update(radius=3,next_radius=3,shrink_start=5,shrink_end=5.6,dps=10000)
        direction,boost=self.planner.choose(self.obs,(1,0),[],self.stats,goal=[50,0,0])
        self.assertEqual(direction,(0,0))
        self.assertFalse(self.planner.last_report['fallback'])
        self.assertIsNone(self.planner._recovery_origin)

    def test_recovery_does_not_bypass_collision_with_momentum_or_charging(self):
        for energy,charging in ((0,False),(100,False),(100,True)):
            with self.subTest(energy=energy,charging=charging):
                self.planner=TacticalPlanner(self.config,WallMap())
                self.planner._recovery_origin=(0,0)
                self.me['vel']=[19.5,0,0]
                self.me['energy']=energy
                self.me['weapons'][1]={'kind':'laser','charge':.2} if charging else None
                direction,boost=self.planner.choose(self.obs,(1,0),[],self.stats,goal=[50,0,0])
                if not self.planner.last_report['fallback']:
                    path=self.planner.rollout(self.me,direction,boost,self.stats)
                    self.assertIsNotNone(self.planner._geometry(path,self.stats,time.perf_counter()+1,
                                                               direction,boost,charging))
                else:
                    self.assertEqual(direction,(0,0))
                    self.assertFalse(boost)

    def test_recovery_walk_with_known_projectile_risk_is_not_promoted_over_braking(self):
        self.planner._recovery_origin=(0,0)
        self.obs['projectiles']=[{'kind':'gun','pos':[15,0,4.5],'vel':[-15,0,0]}]
        self.planner.choose(self.obs,(1,0),[],self.stats,goal=[50,0,0],urgent=True)
        self.assertFalse(self.planner.last_report['walk_checked_first'])


if __name__=='__main__':
    unittest.main()
