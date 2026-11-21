"""Conditional route/lease fixtures, not simulated or scored games."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from arena_map import ArenaMap
from combat import Combat
from zone_resource import ZoneResourcePlanner, circle_at, distance
from bot import Bot

DATA=json.loads((ROOT/'tests/fixtures/c1-resource-boundary.json').read_text(encoding='utf-8'))
CONFIG=DATA['config']


def fixture(t='65.8'):
    row=copy.deepcopy(DATA['observations'][t])
    return row['obs'],row['candidate']


def stats(obs):
    s={**CONFIG['mech'],**obs['self']['stats']}
    scale=1+CONFIG['cubes']['size_per_cube']*obs['self']['cubes']
    s['radius']*=scale
    s['height']*=scale
    return s


class Corridor:
    """Controlled fixture: endpoints clear, a full corridor has a width limit."""
    available=True
    def __init__(self,max_radius=math.inf):
        self.max_radius=max_radius
        self.checked=[]
    def ground_height(self,x,y): return -5.13
    def point_clear(self,p,r,h): return True
    def move_clear(self,a,b,r,h):
        self.checked.append((tuple(a),tuple(b),r,h))
        return r<self.max_radius


class ZoneResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arena=ArenaMap(str(ROOT/'arena'),CONFIG)
        assert cls.arena.available and len(cls.arena.prisms)==259

    def setUp(self):
        self.obs,self.candidate=fixture()
        self.s=stats(self.obs)
        self.planner=ZoneResourcePlanner(CONFIG,self.arena)

    def test_real_658_has_complete_online_exit_after_twelve_cube_growth(self):
        plan=self.planner.plan(self.obs,self.candidate,self.s)
        self.assertIsNotNone(plan,self.planner.last_report)
        self.assertTrue(self.planner.rotation_required(self.obs,self.s))
        self.assertEqual(plan['modeled_cubes'],12)
        self.assertAlmostEqual(plan['radius'],4.375)
        self.assertAlmostEqual(plan['height'],15.75)
        self.assertGreater(plan['min_zone_slack'],0)
        self.assertLess(plan['trip_s'],9)
        # This exit is generated from this observation's circle, not copied
        # from a later recorded position or the old bot's rotation goal.
        self.assertAlmostEqual(plan['escape'][0],-269.7048236071765)
        self.assertAlmostEqual(plan['escape'][1],-82.23938130981144)
        for a,b in ((self.obs['self']['pos'],plan['pickup']),(plan['pickup'],plan['escape'])):
            self.assertTrue(self.arena.move_clear(a,b,plan['radius'],plan['height']))
        self.assertTrue(plan['suppress_laser_charge'])

    def test_actual_750_memory_only_backtrack_is_not_admitted(self):
        obs,candidate=fixture('75')
        self.assertIsNotNone(candidate)
        self.assertIsNone(self.planner.plan(obs,candidate,stats(obs)))
        self.assertEqual(self.planner.last_report['reason'],'not_currently_observed')

    def test_rotation_latch_does_not_release_at_actual_750_small_positive_slack(self):
        self.assertTrue(self.planner.rotation_required(self.obs,self.s))
        obs,_=fixture('75')
        center,radius=circle_at(obs,12)
        slack=radius-distance(obs['self']['pos'],center)-stats(obs)['radius']-8
        self.assertGreater(slack,0)
        self.assertLess(slack,6)
        self.assertTrue(self.planner.rotation_required(obs,stats(obs)))
        obs['self']['pos'][:2]=center
        self.assertFalse(self.planner.rotation_required(obs,stats(obs)))

    def test_active_charge_is_rejected_before_route_admission(self):
        laser=next(w for w in self.obs['self']['weapons'] if w and w['kind']=='laser')
        laser['charge']=.45
        self.assertIsNone(self.planner.plan(self.obs,self.candidate,self.s))
        self.assertEqual(self.planner.last_report['reason'],'active_charge')

    def test_fast_shrink_rejects_route_even_with_clear_geometry(self):
        planner=ZoneResourcePlanner(CONFIG,Corridor())
        self.obs['zone'].update(shrink_start=self.obs['t'],shrink_end=self.obs['t']+4)
        self.assertIsNone(planner.plan(self.obs,self.candidate,self.s))
        self.assertEqual(planner.last_report['reason'],'route_or_zone_unsafe')

    def test_current_acceleration_delay_can_invalidate_route(self):
        self.s['ground_accel']=.1
        self.assertIsNone(self.planner.plan(self.obs,self.candidate,self.s))

    def test_clear_endpoints_do_not_prove_route_after_cube_growth(self):
        corridor=Corridor(max_radius=4)
        planner=ZoneResourcePlanner(CONFIG,corridor)
        self.assertTrue(corridor.move_clear(self.obs['self']['pos'],self.candidate[1],self.s['radius'],self.s['height']))
        self.assertIsNone(planner.plan(self.obs,self.candidate,self.s))
        self.assertTrue(any(r>=4.375 for _,_,r,_ in corridor.checked))

    def test_expired_budget_does_not_admit(self):
        self.assertIsNone(self.planner.plan(self.obs,self.candidate,self.s,time.perf_counter()-1))
        self.assertEqual(self.planner.last_report['reason'],'budget')

    def test_progress_keeps_same_pickup_and_escape(self):
        initial=self.planner.start_lease(self.obs,self.candidate,self.s)
        self.assertIsNotNone(initial)
        self.obs['t']+=.2
        p=self.obs['self']['pos']
        d=distance(p,initial['pickup'])
        p[:2]=[p[i]+(initial['pickup'][i]-p[i])*2/d for i in (0,1)]
        continued=self.planner.continue_lease(self.obs,self.s,eligible=True)
        self.assertIsNotNone(continued,self.planner.last_report)
        self.assertEqual(continued['goal'],initial['pickup'])
        self.assertEqual(continued['escape'],initial['escape'])

    def test_stalled_commitment_is_cancelled(self):
        self.planner.start_lease(self.obs,self.candidate,self.s)
        self.obs['t']+=2.1
        self.assertIsNone(self.planner.continue_lease(self.obs,self.s,eligible=True))
        self.assertEqual(self.planner.last_report['reason'],'no_progress')

    def test_recovery_or_exposure_preempts_lease(self):
        self.planner.start_lease(self.obs,self.candidate,self.s)
        self.assertIsNone(self.planner.continue_lease(self.obs,self.s,eligible=False))
        self.assertEqual(self.planner.last_report['reason'],'preempted')

    def test_laser_charge_breaks_existing_lease(self):
        self.planner.start_lease(self.obs,self.candidate,self.s)
        next(w for w in self.obs['self']['weapons'] if w and w['kind']=='laser')['charge']=.05
        self.assertIsNone(self.planner.continue_lease(self.obs,self.s,eligible=True))
        self.assertEqual(self.planner.last_report['reason'],'active_charge')

    def test_collection_hands_off_to_validated_fixed_exit(self):
        initial=self.planner.start_lease(self.obs,self.candidate,self.s)
        self.obs['t']+=4.3
        self.obs['self']['pos']=list(initial['pickup'])
        self.obs['self']['cubes']+=12
        self.obs['cubes']=[c for c in self.obs['cubes'] if distance(c['pos'],initial['pickup'])>3.5]
        self.obs['events']=[{'type':'pickup','cubes':15}]
        continued=self.planner.continue_lease(self.obs,stats(self.obs),eligible=True)
        self.assertIsNotNone(continued,self.planner.last_report)
        self.assertEqual(continued['phase'],'exit')
        self.assertEqual(continued['goal'],initial['escape'])
        self.assertGreaterEqual(continued['radius'],4.375)
        self.obs['self']['pos']=list(initial['escape'])
        self.assertIsNone(self.planner.continue_lease(self.obs,stats(self.obs),eligible=True))
        self.assertEqual(self.planner.last_report['reason'],'exit_reached')

    def test_unexpected_body_growth_invalidates_existing_exit_geometry(self):
        corridor=Corridor(max_radius=4.6)
        planner=ZoneResourcePlanner(CONFIG,corridor)
        self.assertIsNotNone(planner.start_lease(self.obs,self.candidate,self.s))
        self.obs['self']['cubes']+=4
        self.assertIsNone(planner.continue_lease(self.obs,stats(self.obs),eligible=True))
        self.assertEqual(planner.last_report['reason'],'route_or_zone_unsafe')

    def test_missing_resource_cancels_instead_of_backtracking_from_memory(self):
        self.planner.start_lease(self.obs,self.candidate,self.s)
        self.obs['cubes']=[]
        self.assertIsNone(self.planner.continue_lease(self.obs,self.s,eligible=True))
        self.assertEqual(self.planner.last_report['reason'],'resource_disappeared')

    def test_new_zone_observation_invalidates_live_lease(self):
        self.planner.start_lease(self.obs,self.candidate,self.s)
        self.obs['zone'].update(shrink_start=self.obs['t'],shrink_end=self.obs['t']+4)
        self.assertIsNone(self.planner.continue_lease(self.obs,self.s,eligible=True))
        self.assertEqual(self.planner.last_report['reason'],'route_or_zone_unsafe')

    def test_elapsed_lease_is_cancelled(self):
        self.planner.start_lease(self.obs,self.candidate,self.s)
        self.obs['t']+=15
        self.assertIsNone(self.planner.continue_lease(self.obs,self.s,eligible=True))
        self.assertEqual(self.planner.last_report['reason'],'expired')

    def test_charge_suppression_preserves_same_target_gun_solution(self):
        # Contract with unchanged Combat.plan: regular target selection stays
        # outside this component, and the emergency flag only prevents charge.
        obs=copy.deepcopy(self.obs)
        obs['self']['pos']=[0,0,0]
        obs['self']['aim']=[0,0]
        for w in obs['self']['weapons']:
            if w:
                w['cooldown']=0
                if w['kind']=='gun': w.update(ammo=12,reload=0)
                if w['kind']=='laser': w['charge']=0
        target={'id':123,'kind':'mech','pos':[100,0,0],'vel':[0,15,0],'hp':1400,'cubes':0}
        suppressed=Combat(CONFIG).plan(obs,target,emergency=True)
        only_gun=copy.deepcopy(obs)
        only_gun['self']['weapons'][1]=None
        gun=Combat(CONFIG).plan(only_gun,target)
        self.assertEqual(suppressed['aim'],gun['aim'])
        self.assertEqual(suppressed['fire'][0],gun['fire'][0])
        self.assertFalse(suppressed['fire'][1])
        obs['self']['weapons'][1]['charge']=.45
        release=Combat(CONFIG).plan(obs,target,emergency=True)
        self.assertFalse(release['fire'][1])
        self.assertLess(abs(release['aim'][0]),.01)

    def make_bot(self):
        with patch('bot.ArenaMap',return_value=self.arena):
            return Bot({'config':CONFIG,'map':{'dir':str(ROOT/'arena')},'slot':0})

    def test_pipeline_658_uses_lease_grown_tactical_body_without_changing_target(self):
        bot=self.make_bot()
        captured={}
        original=bot.movement
        def movement(obs,navigation,threats,s,urgent,deadline,goal=None):
            captured.update(stats=s,urgent=urgent,weapons=obs['self']['weapons'])
            return original(obs,navigation,threats,s,urgent,deadline,goal)
        bot.movement=movement
        action=bot.act(self.obs)
        self.assertEqual(bot.mode,'loot')
        self.assertTrue(bot.telemetry['zone_resource']['active'])
        self.assertEqual(bot.resource_key,('cubes',5050))
        self.assertEqual(bot.telemetry['target'],11)
        self.assertAlmostEqual(captured['stats']['radius'],4.375)
        self.assertAlmostEqual(captured['stats']['height'],15.75)
        self.assertFalse(action['fire'][1])
        self.assertFalse(action['jump'])
        self.assertEqual(captured['weapons'][1]['charge'],0)

    def test_pipeline_never_admits_unreleasable_subminimum_charge(self):
        bot=self.make_bot()
        self.obs['self']['weapons'][1]['charge']=.1
        bot.act(self.obs)
        self.assertEqual(bot.mode,'rotate')
        self.assertIsNone(bot.zone_resources.lease_key)
        self.assertFalse(bot.telemetry['zone_resource']['active'])

    def test_pipeline_recovery_preempts_active_lease(self):
        bot=self.make_bot()
        bot.act(self.obs)
        self.assertIsNotNone(bot.zone_resources.lease_key)
        self.obs['t']+=.1
        self.obs['self']['hp']=500
        bot.act(self.obs)
        self.assertTrue(bot.recover)
        self.assertIsNone(bot.zone_resources.lease_key)
        self.assertFalse(bot.telemetry['zone_resource']['active'])

    def test_pipeline_pickup_handoff_keeps_exit_and_suppresses_charge(self):
        bot=self.make_bot()
        bot.act(self.obs)
        initial=dict(bot.zone_resources._lease)
        self.obs['t']+=4.3
        self.obs['self']['pos']=list(initial['pickup'])
        self.obs['self']['cubes']+=12
        self.obs['cubes']=[c for c in self.obs['cubes'] if distance(c['pos'],initial['pickup'])>3.5]
        self.obs['events']=[{'type':'pickup','cubes':15}]
        action=bot.act(self.obs)
        self.assertEqual(bot.mode,'rotate')
        self.assertEqual(bot.telemetry['goal'],initial['escape'])
        self.assertTrue(bot.telemetry['zone_resource']['active'])
        self.assertFalse(action['fire'][1])

    def test_pipeline_750_rotation_does_not_reverse_for_remembered_cube(self):
        bot=self.make_bot()
        obs,candidate=fixture('75')
        bot.loot[tuple(candidate[3])]=(candidate[4],72)
        bot.zone_resources.rotating=True
        bot.act(obs)
        self.assertEqual(bot.mode,'rotate')
        self.assertIsNone(bot.resource_key)
        self.assertFalse(bot.telemetry['zone_resource']['active'])


if __name__=='__main__':
    unittest.main()
