"""Proactive selection, physical reachability and bounded work regressions."""
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engagement import AggressiveDecision, AggressiveEngagement, Engagement
from combat import Combat

with gzip.open(ROOT/'check/stream.jsonl.gz', 'rt') as stream:
    CONFIG = json.loads(next(stream))['config']


def weapon(kind='gun', **changes):
    w = dict(kind=kind, stats=dict(CONFIG['weapons'][kind]), cooldown=0)
    if kind == 'gun':
        w.update(ammo=12, reload=0)
    if kind == 'laser':
        w['charge'] = 0
    w.update(changes)
    return w


def actor(actor_id=1, x=100, y=0, hp=1400, **changes):
    a = dict(id=actor_id, kind='mech', pos=[x,y,0], vel=[0,0,0], aim=[math.pi,0],
             hp=hp, max_hp=1400, cubes=0, weapons=['gun'])
    a.update(changes)
    return a


def observation(*actors, weapons=None):
    return dict(t=5, tick=100, self=dict(id=0,pos=[0,0,0],vel=[0,0,0],aim=[0,-.025],hp=1400,
        max_hp=1400,energy=100,cubes=0,stats=dict(CONFIG['mech']),weapons=weapons or [weapon(),None]),
        mechs=list(actors),events=[],beams=[],crates=[],projectiles=[])


def candidates(obs):
    return [dict(actor=a,d=math.dist(obs['self']['pos'][:2],a['pos'][:2]),los=True,risk=1) for a in obs['mechs']]


class AggressiveEngagementTests(unittest.TestCase):
    def select(self, obs, controller=None, **kwargs):
        return (controller or AggressiveEngagement(CONFIG)).select(obs,candidates(obs),**kwargs)

    def test_full_health_quiet_enemy_is_proactive_target(self):
        obs=observation(actor())
        decision=self.select(obs)
        self.assertEqual(decision.mode,'ATTACK')
        self.assertEqual(decision.target['id'],1)
        self.assertTrue(decision.allow_fire)
        self.assertIsNone(decision.finish_eta)
        self.assertFalse(Engagement(CONFIG).select(obs,candidates(obs)).allow_fire)

    def test_recovery_is_callers_policy_not_an_admission_gate(self):
        obs=observation(actor())
        obs['self']['hp']=200
        self.assertTrue(self.select(obs,recovering=True).allow_fire)

    def test_every_current_hostile_is_authorized_but_not_npc_or_self(self):
        obs=observation(actor(1),actor(2,x=80,y=40),actor(102,x=50,kind='npc'),actor(0,x=0),actor(3,hp=0))
        result=self.select(obs)
        self.assertEqual(result.authorized_ids,frozenset((1,2)))

    def test_shorter_feasible_kill_beats_lower_absolute_hp_farther_away(self):
        obs=observation(actor(1,x=200,y=-40,hp=1),actor(2,x=60,y=20,hp=30))
        result=self.select(obs)
        self.assertEqual(result.target['id'],2)
        self.assertLessEqual(result.finish_eta,2)

    def test_blocked_low_hp_actor_does_not_displace_reachable_target(self):
        obs=observation(actor(1,x=80,y=-20,hp=1),actor(2,x=100,y=30))
        controller=AggressiveEngagement(CONFIG,lambda a,b:b[1]>0)
        self.assertEqual(self.select(obs,controller).target['id'],2)

    def test_nearer_hostile_intercepts_gun_and_becomes_target(self):
        obs=observation(actor(1,x=100,hp=1),actor(2,x=50))
        result=self.select(obs)
        self.assertEqual(result.target['id'],2)
        self.assertIsNone(result.finish_eta)

    def test_piercing_laser_can_select_farther_short_kill(self):
        laser=weapon('laser');laser['stats']['pierce']=1
        obs=observation(actor(1,x=100,hp=100),actor(2,x=50),weapons=[laser,None])
        result=self.select(obs)
        self.assertEqual(result.target['id'],1)
        self.assertIsNotNone(result.finish_eta)

    def test_nonpiercing_laser_cannot_credit_damage_past_nearer_actor(self):
        obs=observation(actor(1,x=100,hp=1),actor(2,x=50),weapons=[weapon('laser'),None])
        self.assertEqual(self.select(obs).target['id'],2)

    def test_lightning_primary_interceptor_is_reachable_target(self):
        obs=observation(actor(1,x=40,hp=1),actor(2,x=30,y=3),weapons=[weapon('lightning'),None])
        result=self.select(obs)
        self.assertEqual(result.target['id'],2)
        action=Combat(CONFIG).plan(obs,result.target,protected_ids=set(obs_a['id'] for obs_a in obs['mechs'])-result.authorized_ids)
        self.assertTrue(action['fire'][0])

    def test_lightning_hostile_chain_does_not_block_usable_target(self):
        obs=observation(actor(1,x=30,hp=30),actor(2,x=40),weapons=[weapon('lightning'),None])
        result=self.select(obs)
        self.assertEqual(result.target['id'],1)
        self.assertIsNotNone(result.finish_eta)

    def test_lightning_low_energy_can_be_usable_without_false_finish_eta(self):
        obs=observation(actor(x=30,hp=30),weapons=[weapon('lightning'),None])
        obs['self']['energy']=15
        result=self.select(obs)
        self.assertTrue(result.allow_fire)
        self.assertIsNone(result.finish_eta)
        obs['self']['energy']=2
        self.assertFalse(self.select(obs).allow_fire)

    def test_current_focus_survives_small_health_score_change(self):
        controller=AggressiveEngagement(CONFIG)
        obs=observation(actor(1,x=100,y=-20),actor(2,x=100,y=20))
        self.assertEqual(self.select(obs,controller).target['id'],1)
        obs['t']+=.1;obs['tick']+=2;obs['mechs'][1]['hp']-=20
        self.assertEqual(self.select(obs,controller).target['id'],1)

    def test_new_short_kill_overrides_full_health_incumbent(self):
        controller=AggressiveEngagement(CONFIG)
        obs=observation(actor(1,x=100,y=-20),actor(2,x=100,y=20))
        self.select(obs,controller)
        obs['t']+=.1;obs['tick']+=2;obs['mechs'][1]['hp']=20
        self.assertEqual(self.select(obs,controller).target['id'],2)

    def test_charged_laser_keeps_comparable_current_short_kill(self):
        controller=AggressiveEngagement(CONFIG)
        obs=observation(actor(1,hp=200),weapons=[weapon('laser',charge=.4),None])
        self.assertEqual(self.select(obs,controller).target['id'],1)
        obs['mechs'].append(actor(2,x=100,y=40,hp=100));obs['t']+=.1;obs['tick']+=2
        self.assertEqual(self.select(obs,controller).target['id'],1)

    def test_removed_or_dead_incumbent_cannot_remain_firing_target(self):
        controller=AggressiveEngagement(CONFIG)
        obs=observation(actor(1),actor(2,x=120,y=30))
        self.select(obs,controller)
        obs['mechs']=obs['mechs'][1:];obs['t']+=.1;obs['tick']+=2
        self.assertEqual(self.select(obs,controller).target['id'],2)
        obs['events']=[dict(type='kill',target=2)]
        self.assertFalse(self.select(obs,controller).allow_fire)

    def test_reload_and_cooldown_keep_viable_enemy_without_claiming_short_kill(self):
        obs=observation(actor(hp=100),weapons=[weapon(ammo=0,reload=2.4),None])
        result=self.select(obs)
        self.assertTrue(result.allow_fire)
        self.assertIsNone(result.finish_eta)
        obs['self']['weapons'][0]['reload']=5
        self.assertFalse(self.select(obs).allow_fire)

    def test_ready_laser_prevents_reload_penalty_from_flipping_incumbent(self):
        controller=AggressiveEngagement(CONFIG)
        obs=observation(actor(1,hp=332.6),weapons=[weapon(),weapon('laser')])
        self.assertEqual(self.select(obs,controller).target['id'],1)
        obs['mechs'].append(actor(2,x=80,y=60,hp=1276.25))
        for reload_time in (2.35,2.25,2.15,2.05):
            obs['t']+=.1;obs['tick']+=2
            obs['self']['weapons'][0].update(ammo=0,reload=reload_time)
            items=candidates(obs);items[1]['risk']=1.7
            result=controller.select(obs,items)
            self.assertEqual(result.target['id'],1)

    def test_reload_and_ready_laser_target_ranking_is_slot_order_invariant(self):
        selected=[]
        for order in (('gun','laser'),('laser','gun')):
            controller=AggressiveEngagement(CONFIG)
            obs=observation(actor(1,hp=332.6),weapons=[weapon(k) for k in order])
            self.select(obs,controller)
            obs['mechs'].append(actor(2,x=80,y=60,hp=1276.25))
            next(w for w in obs['self']['weapons'] if w['kind']=='gun').update(ammo=0,reload=2.35)
            obs['t']+=.1;obs['tick']+=2
            items=candidates(obs);items[1]['risk']=1.7
            selected.append(controller.select(obs,items).target['id'])
        self.assertEqual(selected,[1,1])

    def test_readiness_lower_bound_does_not_hide_a_faster_aiming_weapon(self):
        gun=weapon();gun['stats']['speed']=20
        obs=observation(actor(x=100,vel=[0,10,0]),weapons=[gun,weapon('laser',cooldown=.05)])
        controller=AggressiveEngagement(CONFIG)
        own=controller.model._self_stats(obs['self'])
        ws=controller._cheap_weapons(obs,obs['mechs'][0],own)
        gun_wait=controller._usable_wait(obs,obs['mechs'][0],own,[ws[0]],time.perf_counter()+1)
        laser_wait=controller._usable_wait(obs,obs['mechs'][0],own,[ws[1]],time.perf_counter()+1)
        self.assertGreater(gun_wait,laser_wait)
        for ordered in (ws,list(reversed(ws))):
            wait,complete=controller._usable_wait(obs,obs['mechs'][0],own,ordered,time.perf_counter()+1,with_completion=True)
            self.assertTrue(complete)
            self.assertEqual(wait,laser_wait)

    def test_impossible_reloading_gun_does_not_spend_ready_laser_finish_budget(self):
        obs=observation(actor(hp=150),weapons=[weapon(ammo=0,reload=2.4),weapon('laser')])
        controller=AggressiveEngagement(CONFIG)
        original=controller._solution
        def solution(me,target,kind,stats,when,own):
            if kind=='gun' and when>2:
                self.fail('A gun that cannot finish within two seconds consumed short geometry work')
            return original(me,target,kind,stats,when,own)
        with patch.object(controller,'_solution',side_effect=solution):
            result=self.select(obs,controller)
        self.assertIsInstance(result,AggressiveDecision)
        self.assertEqual(result.finish_weapon,'laser')
        self.assertLessEqual(result.finish_eta,1.25)

    def test_finishing_weapon_provenance_survives_weapon_slot_order(self):
        for order in (('gun','laser'),('laser','gun')):
            ws=[weapon(k,**({'ammo':0,'reload':2.4} if k=='gun' else {})) for k in order]
            result=self.select(observation(actor(hp=150),weapons=ws))
            self.assertEqual(result.finish_weapon,'laser')
            self.assertLessEqual(result.finish_eta,1.25)

    def test_short_gun_kill_does_not_claim_laser_as_finishing_weapon(self):
        obs=observation(actor(x=20,hp=30),weapons=[weapon(),weapon('laser')])
        result=self.select(obs)
        self.assertEqual(result.finish_weapon,'gun')
        self.assertLess(result.finish_eta,.25)

    def test_shared_aim_damage_is_not_summed_into_false_short_kill(self):
        obs=observation(actor(x=100,hp=450),weapons=[weapon(),weapon('laser')])
        result=self.select(obs)
        self.assertTrue(result.allow_fire)
        self.assertIsNone(result.finish_eta)
        self.assertIsNone(result.finish_weapon)

    def test_solution_cache_does_not_reuse_prior_observation_visibility(self):
        clear=[True]
        controller=AggressiveEngagement(CONFIG,lambda a,b:clear[0])
        obs=observation(actor(hp=100))
        self.assertTrue(self.select(obs,controller).allow_fire)
        clear[0]=False;obs['t']+=.1;obs['tick']+=2
        self.assertFalse(self.select(obs,controller).allow_fire)

    def test_interrupted_ray_does_not_poison_reserved_fallback_cache(self):
        controller=AggressiveEngagement(CONFIG,lambda a,b:True)
        obs=observation(actor(hp=100))
        own=controller.model._self_stats(obs['self'])
        stats=controller.model._stats(obs['self']['weapons'][0])
        controller._solution_cache={}
        with patch('engagement.time.perf_counter',return_value=1):
            controller._geometry_deadline=.5
            incomplete=controller._solution(obs['self'],obs['mechs'][0],'gun',stats,.05,own)
            self.assertFalse(incomplete['clear'])
            controller._geometry_deadline=2
            complete=controller._solution(obs['self'],obs['mechs'][0],'gun',stats,.05,own)
            self.assertTrue(complete['clear'])

    def test_absent_remembered_occluded_and_out_of_range_are_not_fire_targets(self):
        obs=observation(actor(x=400))
        self.assertFalse(self.select(obs).allow_fire)
        obs=observation(actor())
        for changes in (dict(los=False),dict(remembered=True)):
            items=candidates(obs);items[0].update(changes)
            self.assertFalse(AggressiveEngagement(CONFIG).select(obs,items).allow_fire)
        self.assertFalse(AggressiveEngagement(CONFIG).select(observation(),candidates(obs)).allow_fire)

    def test_mortar_only_uses_safe_arc_but_does_not_invent_short_kill(self):
        obs=observation(actor(x=100),weapons=[weapon('mortar'),None])
        result=self.select(obs)
        self.assertTrue(result.allow_fire)
        self.assertEqual(result.reason,'proactive_mortar_path')
        self.assertIsNone(result.finish_eta)
        controller=AggressiveEngagement(CONFIG,lambda a,b:False)
        self.assertFalse(self.select(obs,controller).allow_fire)

    def test_expired_deadline_never_starts_geometry_work(self):
        controller=AggressiveEngagement(CONFIG)
        obs=observation(actor(hp=10))
        with patch.object(controller,'_solution',side_effect=AssertionError('late geometry')):
            result=self.select(obs,controller,deadline=time.perf_counter()-1)
        self.assertFalse(result.allow_fire)
        self.assertEqual(result.reason,'scoring_budget_exhausted')

    def test_dense_short_profiles_and_mortar_arcs_are_explicitly_bounded(self):
        obs=observation(*(actor(i,x=100,y=(i-8)*10,hp=30) for i in range(1,16)))
        controller=AggressiveEngagement(CONFIG,lambda a,b:False)
        self.select(obs,controller)
        self.assertLessEqual(controller.last_scoring['short_profiles'],6)
        obs['self']['weapons']=[weapon('mortar'),None]
        self.select(obs,controller)
        self.assertLessEqual(controller.last_scoring['mortar_profiles'],2)

    def test_blocked_weak_targets_leave_budget_for_healthy_interceptor(self):
        obs=observation(*(actor(i,x=100+i,y=(i-4)*.4,hp=10) for i in range(1,9)),actor(9,x=50))
        controller=AggressiveEngagement(CONFIG)
        original=controller._weapon_profile
        clock=[100.0]
        def costly_profile(*args,**kwargs):
            clock[0]+=.0015
            return original(*args,**kwargs)
        with patch('engagement.time.perf_counter',side_effect=lambda:clock[0]), patch.object(controller,'_weapon_profile',side_effect=costly_profile):
            result=self.select(obs,controller)
        self.assertEqual(result.target['id'],9)
        self.assertLessEqual(controller.last_scoring['short_profiles'],3)


if __name__=='__main__':
    unittest.main()
