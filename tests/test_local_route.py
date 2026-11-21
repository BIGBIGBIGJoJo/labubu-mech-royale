"""Bounded route recovery, vertical guards and portable captured geometry."""
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
from local_route import LocalRouteRecovery


class FlatArena:
    available=True
    def ground_height(self,x,y):return 0.
    def navigate(self,*args):return (.6,.8)


class LocalRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT/'check/stream.jsonl.gz','rt',encoding='utf-8') as stream:
            cls.config=json.loads(next(stream))['config']
        cls.fixture=json.loads((ROOT/'tests/tactical_recovery_fixture.json').read_text())
        cls.directory=tempfile.TemporaryDirectory(prefix='mechfight-local-route-')
        root=Path(cls.directory.name)/'v2';root.mkdir()
        (root/'world.json').write_text(json.dumps(cls.fixture['world']))
        (root/'terrain.i16').write_bytes(zlib.decompress(base64.b64decode(cls.fixture['terrain_zlib_base64'])))
        cls.arena=ArenaMap(cls.directory.name,cls.config)
        if not cls.arena.available:raise RuntimeError(cls.arena.error)

    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()

    def setUp(self):
        self.case=copy.deepcopy(self.fixture['cases'][1])
        self.obs,self.stats,self.goal=self.case['obs'],self.case['stats'],self.case['goal']
        self.arena._search=None
        self.manager=LocalRouteRecovery(self.arena)

    def call(self,request=False):
        with patch('local_route.time.perf_counter',return_value=0):
            return self.manager.navigate(self.obs,self.goal,self.stats,request,1)

    def test_current_grounded_failed_component_can_start_recovery(self):
        self.call()
        self.assertTrue(self.manager.active)
        self.assertEqual(self.manager.status,'local_searching')
        self.assertTrue(self.manager.last_report['active'])

    def test_ready_route_can_start_from_root_stall_request(self):
        case=copy.deepcopy(self.fixture['cases'][0])
        self.obs,self.stats,self.goal=case['obs'],case['stats'],case['goal']
        self.call(request=True)
        self.assertTrue(self.manager.active)
        self.assertEqual(self.manager.local['episode']['reason'],'planner_stalled')

    def test_normal_success_delegates_unchanged(self):
        manager=LocalRouteRecovery(FlatArena())
        direction,goal=manager.navigate(self.obs,self.goal,self.stats,False,time.perf_counter()+1)
        self.assertEqual(direction,(.6,.8));self.assertIs(goal,self.goal)
        self.assertFalse(manager.active)

    def test_stub_without_coarse_search_declines_gracefully(self):
        arena=FlatArena();self.obs['self']['pos'][2]=0
        manager=LocalRouteRecovery(arena)
        direction,goal=manager.navigate(self.obs,self.goal,self.stats,True,time.perf_counter()+1)
        self.assertEqual(direction,(.6,.8));self.assertIs(goal,self.goal)
        self.assertEqual(manager.last_report['reason'],'coarse_geometry_unavailable')

    def test_airborne_state_cannot_start_ground_search(self):
        self.obs['self']['grounded']=False;self.call(request=True)
        self.assertFalse(self.manager.active)

    def test_missing_grounded_flag_cannot_authorize_ground_recovery(self):
        del self.obs['self']['grounded'];self.call(request=True)
        self.assertFalse(self.manager.active)

    def test_elevated_roof_or_bridge_support_cannot_start_ground_search(self):
        self.obs['self']['pos'][2]+=5;self.call(request=True)
        self.assertFalse(self.manager.active)

    def test_vertical_transition_cancels_existing_episode(self):
        self.call();episode=self.manager.episodes[-1]
        self.obs['self']['pos'][2]+=5;self.call()
        self.assertFalse(self.manager.active)
        self.assertEqual(episode['invalidated'],'vertical_level_changed')

    def test_goal_arrival_cancels_recovery_and_preserves_intended_hold(self):
        self.call();episode=self.manager.episodes[-1]
        self.goal=list(self.obs['self']['pos']);self.goal[0]+=1.2
        direction,goal=self.call()
        self.assertEqual(direction,(0,0));self.assertIs(goal,self.goal)
        self.assertFalse(self.manager.active)
        self.assertEqual(episode['invalidated'],'strategic_goal_reached')

    def test_goal_refresh_updates_preference_without_discarding_geometry(self):
        self.call();episode=self.manager.local
        first=self.manager._ordered_offsets((0,0),self.obs,self.stats)
        self.goal=[-200,200,0]
        # Preserve a partial discovery episode so this check isolates goal churn.
        with patch.object(self.manager,'_search'):
            self.call()
        self.assertIs(self.manager.local,episode)
        self.assertNotEqual(first,self.manager._ordered_offsets((0,0),self.obs,self.stats))
        self.assertEqual(self.manager.goal,self.goal)

    def test_body_change_discards_episode_and_component_cache(self):
        self.call();episode=self.manager.episodes[-1]
        self.manager.components['sentinel']=123
        self.stats['radius']+=.1;self.call()
        self.assertEqual(episode['invalidated'],'body_or_map_changed')
        self.assertNotIn('sentinel',self.manager.components)

    def test_map_change_discards_geometry_and_delegates_new_map(self):
        self.call();episode=self.manager.episodes[-1]
        self.manager.arena=FlatArena();self.obs['self']['pos'][2]=0
        direction,_=self.call()
        self.assertEqual(direction,(.6,.8));self.assertFalse(self.manager.active)
        self.assertEqual(episode['invalidated'],'body_or_map_changed')

    def test_expired_budget_does_not_start_map_work(self):
        with patch.object(self.arena,'navigate') as navigate:
            direction,_=self.manager.navigate(self.obs,self.goal,self.stats,True,time.perf_counter()-1)
        navigate.assert_not_called();self.assertEqual(direction,(0,0))
        self.assertEqual(self.manager.last_report['reason'],'deadline')

    def test_partial_search_resumes_without_starting_geometry_after_deadline(self):
        self.call();clock=[0.0]
        def nearest(*args):clock[0]=1.;return (96,78)
        with patch('local_route.time.perf_counter',side_effect=lambda:clock[0]), \
                patch.object(self.arena,'_nearest_free',side_effect=nearest),patch.object(self.arena,'move_clear') as sweep:
            self.manager.navigate(self.obs,self.goal,self.stats,True,.01)
        sweep.assert_not_called();self.assertTrue(self.manager.active)
        self.assertFalse(self.manager.local['initial_linked'])

    def test_stale_coarse_search_start_is_not_used_for_component_classification(self):
        self.call();self.arena._search['start']=(0,0)
        with patch.object(self.manager,'_component',return_value=None) as component:
            self.call()
        current=self.arena._nearest_free(self.arena._cell(self.obs['self']['pos']),(3,10.5))
        self.assertEqual(component.call_args.args[0],current)
        self.assertNotEqual(current,(0,0))
        self.assertTrue(self.manager.local['initial_linked'])

    def test_disconnected_current_coarse_anchor_is_rejected(self):
        self.call()
        with patch.object(self.arena,'move_clear',return_value=False):self.call()
        self.assertFalse(self.manager.active)
        self.assertEqual(self.manager.last_report['reason'],'coarse_anchor_not_connected')

    def test_large_initial_component_declines_and_does_not_repeat_same_search(self):
        self.call()
        with patch.object(self.manager,'_component',return_value=8):self.call()
        self.assertFalse(self.manager.active)
        self.assertEqual(self.manager.last_report['reason'],'initial_component_not_small')
        count=len(self.manager.episodes);self.call(request=True)
        self.assertFalse(self.manager.active);self.assertEqual(len(self.manager.episodes),count)
        self.assertEqual(self.manager.last_report['reason'],'failed_anchor')

    def test_meaningful_observed_motion_clears_failed_anchor(self):
        self.call();self.manager._fail('test')
        self.obs['self']['pos'][0]+=10
        self.obs['self']['pos'][2]=self.arena.ground_height(*self.obs['self']['pos'][:2])
        self.call();self.assertEqual(self.manager.failed_anchors,[])

    def test_moving_actor_does_not_activate_on_coarse_failure_alone(self):
        self.obs['self']['vel']=[10,0,0];self.call()
        self.assertFalse(self.manager.active)

    def test_component_job_cap_terminates_episode_without_detached_state_error(self):
        self.call();self.manager.component_jobs={i:{} for i in range(self.manager.COMPONENT_LIMIT)}
        self.call()
        self.assertFalse(self.manager.active)
        self.assertEqual(self.manager.last_report['reason'],'component_cache_cap')

    def test_stale_episode_ends_with_bounded_failed_anchor_memory(self):
        self.call();self.obs['t']+=31;self.call()
        self.assertFalse(self.manager.active)
        self.assertEqual(self.manager.last_report['reason'],'episode_timeout')
        self.assertLessEqual(len(self.manager.failed_anchors),8)

    def test_captured_small_component_discovers_only_swept_links_to_larger_component(self):
        self.call();direction,tactical_goal=self.call()
        self.assertEqual(self.manager.status,'local_following')
        local=self.manager.local;path=local['path']
        self.assertEqual(local['initial_component'],2)
        self.assertGreater(local['episode']['exit_component_cap8'],2)
        self.assertLessEqual(len(local['parents']),self.manager.LIMIT)
        self.assertTrue(all(self.arena.move_clear(a,b,self.stats['radius'],self.stats['height']) for a,b in zip(path,path[1:])))
        self.assertEqual(path[-1],self.arena._point(local['episode']['exit_cell']))
        self.assertEqual(tactical_goal,path[-1])
        self.assertGreater(math.hypot(*direction),.5)
        # Links are validated separately for each exact fine cell, even when
        # several fine cells map to the same coarse-cell cache entry.
        self.assertTrue(all(len(key)==2 and isinstance(key[0],tuple) for key in local['exit_links']))

    def test_route_completion_clears_old_coarse_search(self):
        self.call();self.call();goal=self.manager.local['path'][-1]
        self.obs['self']['pos']=list(goal)
        direction,_=self.call()
        self.assertEqual(direction,(0,0));self.assertEqual(self.manager.status,'exit_reached')
        self.assertFalse(self.manager.active);self.assertIsNone(self.arena._search)

    def test_exit_sweep_cannot_be_reused_from_another_fine_point(self):
        self.call();local=self.manager.local
        coarse=(95,82);first=(50,0);second=(50,1)
        local.update(initial_cell=(96,78),initial_linked=True,initial_component=2,
                     exit_pending=second,active=second,cursor=0,offsets=((1,0),),
                     exit_cells={coarse:coarse},exit_links={(first,coarse):True})
        local['parents'][second]=(0,0)
        clock=[0.0]
        def blocked_link(*args):clock[0]=1.0;return False
        with patch('local_route.time.perf_counter',side_effect=lambda:clock[0]), \
                patch.object(self.arena,'_cell',return_value=coarse), \
                patch.object(self.arena,'move_clear',side_effect=blocked_link) as sweep, \
                patch.object(self.manager,'_component') as component, \
                patch.object(self.arena,'point_clear') as point_clear:
            self.manager._search(self.obs,self.stats,.01)
        sweep.assert_called_once();component.assert_not_called();point_clear.assert_not_called()
        self.assertFalse(local['exit_links'][(second,coarse)])
        self.assertIsNone(local['path'])


if __name__=='__main__':unittest.main()
