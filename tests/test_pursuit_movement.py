"""Close pursuit preferences and physical movement authority, not game results."""
import copy
import math
import time
import unittest
from unittest.mock import patch

import test_tactical as fixtures
from tactical import TacticalPlanner,pursuit_distance


class PursuitMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.TacticalTests.setUpClass()
        cls.config=fixtures.TacticalTests.config

    setUp=fixtures.TacticalTests.setUp

    def actor(self,kind="mech",distance=200,**kw):
        return {"id":100 if kind=="npc" else 5,"kind":kind,"pos":[distance,0,0],
                "vel":[0,0,0],"cubes":0,"weapons":["gun"],"aim":[math.pi,0],**kw}

    def weapon(self,kind,**stats):
        return {"kind":kind,"stats":{**self.config['weapons'][kind],**stats}}

    def distance(self,target=None,**kw):
        return pursuit_distance(self.config,self.me,target or self.actor(),self.stats,**kw)

    def choose(self,**kw):
        return self.planner.choose(self.obs,(1,0),[],self.stats,goal=[500,0,0],
                                   deadline=time.perf_counter()+.1,**kw)

    def test_gun_laser_and_npc_close_preferences(self):
        self.assertEqual(self.distance(),70)
        self.me['weapons'][1]=self.weapon('laser')
        self.assertEqual(self.distance(),80)
        self.assertEqual(self.distance(self.actor('npc')),35)

    def test_only_gun_only_mech_restores_closer_clear_spacing(self):
        self.assertEqual(self.distance(self.actor(distance=45)),70)
        self.me['weapons'][1]=self.weapon('laser')
        self.assertEqual(self.distance(self.actor(distance=45)),45)

    def test_occluded_target_inside_gun_anchor_still_calls_for_approach(self):
        preferred=self.distance(self.actor(distance=50),line_clear=False)
        self.assertLess(preferred,50)
        self.assertAlmostEqual(preferred,2.5+2.5+2)

    def test_body_separation_can_require_backpedal_at_contact(self):
        self.assertGreater(self.distance(self.actor(distance=3)),3)
        self.stats['radius']=10
        target=self.actor(distance=5,cubes=40)
        self.assertGreaterEqual(self.distance(target),10+2.5*3+2)

    def test_large_self_uses_pitch_distance_for_low_npc(self):
        self.stats.update(radius=15,height=54,muzzle_height=42)
        expected=(42-self.config['npc']['height']*.9)/math.tan(-self.stats['min_pitch'])+2
        self.assertGreater(expected,35)
        self.assertAlmostEqual(self.distance(self.actor('npc')),expected)

    def test_upgraded_lightning_range_requires_funded_trigger(self):
        self.me['weapons'][1]=self.weapon('lightning',range=61.2,energy=3)
        self.me['energy']=11
        self.assertAlmostEqual(self.distance(),55.2)
        self.me['energy']=10.99
        self.assertEqual(self.distance(),70)

    def test_lightning_close_band_matches_ordinary_fire_energy_reserve(self):
        self.me['weapons'][1]=self.weapon('lightning',energy=3)
        for energy,expected in ((3,70),(10,70),(11,39)):
            with self.subTest(energy=energy):
                self.me['energy']=energy
                self.assertEqual(self.distance(),expected)
        self.me['weapons'][1]=self.weapon('lightning',energy=2.25)
        self.me['energy']=10.24
        self.assertEqual(self.distance(),70)
        self.me['energy']=10.25
        self.assertEqual(self.distance(),39)

    def test_default_lightning_joint_band_and_npc_band(self):
        self.me['weapons'][1]=self.weapon('lightning')
        self.assertEqual(self.distance(),39)
        self.assertEqual(self.distance(self.actor('npc')),35)

    def test_short_live_direct_range_caps_preference(self):
        self.me['weapons'][0]['stats']['range']=50
        self.assertEqual(self.distance(),44)

    def test_mortar_floor_uses_live_splash_and_scaled_self_body(self):
        self.me['weapons'][1]=self.weapon('mortar',splash_radius=20)
        self.stats['radius']=40
        self.assertGreaterEqual(self.distance(self.actor('npc')),20+40+3)
        self.assertGreaterEqual(self.distance(line_clear=False),20+40+3)

    def test_preference_does_not_mutate_inputs(self):
        target=self.actor()
        before=copy.deepcopy((self.me,target,self.stats))
        self.distance(target)
        self.assertEqual((self.me,target,self.stats),before)

    def test_calm_pursuit_selects_boost_and_gains_progress(self):
        direction,boost=self.choose(pursuit=True)
        self.assertGreater(direction[0],.9)
        self.assertTrue(boost)
        boosted=self.planner.rollout(self.me,direction,boost,self.stats)[-1][1]
        walked=self.planner.rollout(self.me,direction,False,self.stats)[-1][1]
        self.assertGreater(boosted-walked,2.7)
        self.assertLessEqual(self.planner.last_report['geometry_checked'],6)

    def test_non_pursuit_preserves_ordinary_boost_preference(self):
        direction,boost=self.choose()
        self.assertGreater(direction[0],.9)
        self.assertFalse(boost)

    def test_lightning_and_action_drain_are_reserved_before_boost(self):
        self.me['energy']=39.5
        _,boost=self.choose(pursuit=True,shot_energy=3)
        self.assertFalse(boost)
        self.assertFalse(self.planner.last_report['boost_allowed'])
        self.me['energy']=39.8
        _,boost=self.choose(pursuit=True,shot_energy=3)
        self.assertTrue(self.planner.last_report['boost_allowed'])
        self.assertTrue(boost)
        self.assertGreaterEqual(self.me['energy']-3-self.stats['boost_drain']*self.planner.action_dt,35)

    def test_live_drain_and_decision_interval_determine_boost_reserve(self):
        cfg=copy.deepcopy(self.config)
        cfg['match']['decide_every']=4
        self.planner=TacticalPlanner(cfg,fixtures.FlatMap())
        self.me['energy']=39.8
        self.choose(pursuit=True,shot_energy=3)
        self.assertFalse(self.planner.last_report['boost_allowed'])
        self.stats['boost_drain']=5
        self.choose(pursuit=True,shot_energy=3)
        self.assertTrue(self.planner.last_report['boost_allowed'])

    def test_shot_energy_is_deducted_consistently_without_obs_mutation(self):
        before=copy.deepcopy(self.obs)
        with patch.object(self.planner,'rollout',wraps=self.planner.rollout) as rollout:
            self.choose(pursuit=True,shot_energy=3)
        self.assertTrue(rollout.call_args_list)
        self.assertTrue(all(call.args[0]['energy']==97 for call in rollout.call_args_list))
        self.assertEqual(self.obs,before)

    def test_pursuit_does_not_borrow_urgent_energy_reserve(self):
        self.me['energy']=20
        self.choose(pursuit=True)
        self.assertFalse(self.planner.last_report['boost_allowed'])
        self.assertEqual(self.planner.last_report['boost_reserve'],35)
        self.choose(pursuit=True,urgent=True)
        self.assertTrue(self.planner.last_report['boost_allowed'])
        self.assertEqual(self.planner.last_report['boost_reserve'],12)

    def test_pursuit_keeps_wall_sweeps_authoritative(self):
        self.planner.map=fixtures.WallMap()
        direction,boost=self.choose(pursuit=True)
        path=self.planner.rollout(self.me,direction,boost,self.stats)
        checked=self.planner._geometry(path,self.stats,time.perf_counter()+.1,direction,boost,False)
        self.assertIsNotNone(checked)
        self.assertTrue(all(state[1]+self.stats['radius']<=5.5+1e-8 for state in checked))

    def test_actual_incoming_projectile_can_override_straight_pursuit(self):
        self.obs['projectiles']=[{'kind':'gun','pos':[120,0,4.5],'vel':[-252,0,0]}]
        direction,boost=self.choose(pursuit=True)
        tracks=self.planner._projectiles(self.obs,time.perf_counter()+.1)
        chosen=self.planner.rollout(self.me,direction,boost,self.stats)
        direct=self.planner.rollout(self.me,(1,0),True,self.stats)
        self.assertGreater(abs(direction[1]),.2)
        self.assertLess(self.planner.projectile_cost(chosen,tracks,self.stats),
                        self.planner.projectile_cost(direct,tracks,self.stats))

    def test_aimed_charging_beam_can_override_straight_pursuit(self):
        target=self.actor(distance=80,weapons=['laser'],charging=True)
        q={'actor':target,'d':80,'los':True,'risk':1}
        direction,boost=self.planner.choose(self.obs,(1,0),[q],self.stats,goal=[500,0,0],
                                            pursuit=True,deadline=time.perf_counter()+.1)
        chosen=self.planner.rollout(self.me,direction,boost,self.stats)
        direct=self.planner.rollout(self.me,(1,0),True,self.stats)
        self.assertLess(self.planner._beam_cost(chosen,[q],self.stats),
                        self.planner._beam_cost(direct,[q],self.stats))

    def test_pursuit_respects_live_charge_movement_multiplier(self):
        self.me['weapons'][1]={'kind':'laser','charge':.2}
        self.stats['charge_move_mult']=.4
        direction,boost=self.choose(pursuit=True)
        path=self.planner.rollout(self.me,direction,boost,self.stats)
        cap=self.stats['boost_speed' if boost else 'walk_speed']*.4
        self.assertLessEqual(math.hypot(*path[-1][4:6]),cap+1e-8)

    def test_unknown_sight_does_not_get_known_occlusion_discount(self):
        actor=self.actor(distance=80)
        visible={'actor':actor,'d':80,'los':True}
        occluded={**visible,'los':False}
        unknown={**occluded,'los_known':False}
        path=self.planner.rollout(self.me,(1,0),False,self.stats)
        deadline=time.perf_counter()+.1
        known_cost=self.planner._exposure(path,[visible],self.stats,False,deadline)
        unknown_cost=self.planner._exposure(path,[unknown],self.stats,False,deadline)
        occluded_cost=self.planner._exposure(path,[occluded],self.stats,False,deadline)
        self.assertGreater(known_cost,0)
        self.assertAlmostEqual(unknown_cost,known_cost)
        self.assertAlmostEqual(occluded_cost,known_cost*.3)
        with patch.object(self.planner.map,'line_of_fire',return_value=False):
            self.assertEqual(self.planner._exposure(path,[unknown],self.stats,True,
                                                   time.perf_counter()+.1),0)

    def test_unknown_charging_beam_is_conservative_but_known_cover_is_not(self):
        actor=self.actor(distance=80,weapons=['laser'],charging=True)
        visible={'actor':actor,'d':80,'los':True}
        occluded={**visible,'los':False}
        unknown={**occluded,'los_known':False}
        path=self.planner.rollout(self.me,(1,0),True,self.stats)
        known_cost=self.planner._beam_cost(path,[visible],self.stats)
        self.assertGreater(known_cost,0)
        self.assertEqual(self.planner._beam_cost(path,[unknown],self.stats),known_cost)
        self.assertEqual(self.planner._beam_cost(path,[occluded],self.stats),0)

    def test_expired_pursuit_budget_returns_bounded_fallback(self):
        direction,boost=self.planner.choose(self.obs,(1,0),[],self.stats,pursuit=True,
                                            deadline=time.perf_counter()-1)
        self.assertEqual(direction,(0,0))
        self.assertFalse(boost)
        self.assertTrue(self.planner.last_report['fallback'])
        self.assertTrue(self.planner.last_report['pursuit'])


if __name__=='__main__':
    unittest.main()
