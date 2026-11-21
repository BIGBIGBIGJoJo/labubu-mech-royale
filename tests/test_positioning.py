"""Causal movement-safety checks; permission is not a guaranteed match outcome."""
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from positioning import FinishSafety


class FlatMap:
    available = True
    def point_clear(self, position, radius, height):
        return True
    def move_clear(self, start, end, radius, height):
        return True
    def support_height(self, x, y, z):
        return 0.0


class BlockedMap(FlatMap):
    def move_clear(self, start, end, radius, height):
        return False


class LowExitMap(FlatMap):
    """The only exit has the real bridge's approximate 11.46 m headroom."""
    def move_clear(self, start, end, radius, height):
        return height < 11.46


class LedgeMap(FlatMap):
    def support_height(self, x, y, z):
        return -10.0 if math.hypot(x, y) > 4 else 0.0


class PositioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT/'check/stream.jsonl.gz', 'rt') as stream:
            cls.config = json.loads(next(stream))['config']

    def setUp(self):
        self.stats = dict(self.config['mech'])
        self.me = {'id':0, 'pos':[0,0,0], 'vel':[0,0,0], 'hp':1400, 'max_hp':1400,
                   'energy':100, 'grounded':True, 'in_zone':True}
        self.a = {'id':1, 'kind':'mech', 'pos':[120,10,0], 'vel':[0,0,0],
                  'hp':150, 'aim':[0,0], 'weapons':['gun'], 'cubes':0}
        self.b = {'id':2, 'kind':'mech', 'pos':[140,-10,0], 'vel':[0,0,0],
                  'hp':900, 'aim':[0,0], 'weapons':['gun'], 'cubes':0}
        self.obs = {'tick':100, 't':5, 'self':self.me, 'mechs':[self.a,self.b], 'projectiles':[],
                    'zone':{'center':[0,0], 'radius':500, 'next_center':[0,0], 'next_radius':300,
                            'shrink_start':60, 'shrink_end':100}}
        self.threats = [{'actor':a, 'los':True, 'd':math.dist(a['pos'],self.me['pos'])} for a in self.obs['mechs']]

    def evaluate(self, arena=None, **kwargs):
        return FinishSafety(self.config, arena or FlatMap()).evaluate(self.obs,self.threats,self.stats,**kwargs)

    def test_two_visible_fighters_do_not_automatically_veto_finish(self):
        result = self.evaluate()
        self.assertTrue(result.allows(self.a))
        self.assertTrue(result.allows(self.b))
        self.assertEqual(result.budget_s, 2)
        self.assertLess(result.escape_anchor[0], -9)

    def test_safety_permission_does_not_claim_a_fight_or_pick_lowest_hp(self):
        result = self.evaluate()
        self.assertEqual(result.allowed_ids, frozenset((1,2)))
        self.assertFalse(result.allows({'kind':'npc','id':1}))
        self.assertFalse(result.allows(None))
        self.assertFalse(result.allows({'kind':'mech','id':999}))

    def test_occluded_candidate_cannot_borrow_other_targets_permission(self):
        self.threats[0]['los'] = False
        result = self.evaluate()
        self.assertFalse(result.allows(self.a))
        self.assertTrue(result.allows(self.b))
        self.assertEqual(result.reasons[1], 'not_visible')

    def test_unknown_observed_threat_does_not_mean_no_pressure(self):
        self.threats.pop()
        result = self.evaluate()
        self.assertFalse(result.allows(self.a))
        self.assertEqual(result.reasons[1], 'unknown_pressure')

    def test_remembered_or_stale_visibility_cannot_authorize_entry(self):
        self.threats[0]['remembered'] = True
        result = self.evaluate()
        self.assertFalse(result.allowed_ids)
        self.assertEqual(result.reasons[1], 'not_visible')
        self.threats[0].pop('remembered')
        self.threats[0]['actor'] = {**self.a,'pos':[130,10,0]}
        self.assertFalse(self.evaluate().allowed_ids)

    def test_aiming_at_us_changes_pressure_without_changing_actor_count(self):
        for actor in self.obs['mechs']:
            actor['aim'][0] = math.atan2(-actor['pos'][1],-actor['pos'][0])
        result = self.evaluate()
        self.assertFalse(result.allowed_ids)
        self.assertEqual(result.reasons[1], 'concentrated_pressure')

    def test_charging_laser_facing_us_is_immediate_veto(self):
        self.b.update(weapons=['laser'], charging=True, aim=[math.pi,0])
        result = self.evaluate()
        self.assertEqual(result.reasons[1], 'aimed_charge')
        self.assertEqual(result.budget_s, 0)

    def test_low_health_energy_recovery_and_rotation_fail_closed(self):
        self.me['hp'] = 900
        self.assertEqual(self.evaluate().reasons[1], 'health_reserve')
        self.me['hp'] = 1400
        self.me['energy'] = 25
        self.assertEqual(self.evaluate().reasons[1], 'energy_reserve')
        self.me['energy'] = 100
        self.assertEqual(self.evaluate(recovering=True).reasons[1], 'recovering')
        self.assertEqual(self.evaluate(urgent=True).reasons[1], 'urgent_rotation')

    def test_missing_map_and_airborne_exit_are_not_verified(self):
        arena = FlatMap(); arena.available = False
        self.assertEqual(self.evaluate(arena).reasons[1], 'map_unavailable')
        self.me['grounded'] = False
        self.assertEqual(self.evaluate().reasons[1], 'airborne')

    def test_current_circle_is_safe_but_near_future_circle_is_not(self):
        self.obs['zone'].update(radius=100,next_radius=5,shrink_start=5,shrink_end=8)
        self.assertEqual(self.evaluate().reasons[1], 'zone_slack')

    def test_clear_shot_without_physical_retreat_does_not_authorize(self):
        result = self.evaluate(BlockedMap())
        self.assertEqual(result.reasons[1], 'no_escape_corridor')
        self.assertIsNone(result.escape_anchor)

    def test_cube_scaled_height_rejects_low_exit(self):
        self.assertTrue(self.evaluate(LowExitMap()).allows(self.a))
        self.stats.update(radius=3.5,height=12.6)
        self.assertEqual(self.evaluate(LowExitMap()).reasons[1], 'no_escape_corridor')

    def test_momentum_and_ledge_drop_are_not_a_verified_ground_escape(self):
        self.me['vel'] = [19.5,0,0]
        self.assertEqual(self.evaluate(BlockedMap()).reasons[1], 'inertial_collision')
        self.me['vel'] = [0,0,0]
        self.assertEqual(self.evaluate(LedgeMap()).reasons[1], 'no_escape_corridor')
        self.me['vel'] = [25,0,0]
        self.assertEqual(self.evaluate(LedgeMap()).reasons[1], 'inertial_drop')

    def test_incoming_gun_and_mortar_veto_but_overhead_gun_does_not(self):
        self.obs['projectiles'] = [{'kind':'gun','pos':[-40,0,4],'vel':[252,0,0]}]
        self.assertEqual(self.evaluate().reasons[1], 'incoming_projectile')
        self.obs['projectiles'][0]['pos'][2] = 30
        self.assertTrue(self.evaluate().allows(self.a))
        self.obs['projectiles'] = [{'kind':'mortar','pos':[0,0,10],'vel':[0,0,-10]}]
        self.assertEqual(self.evaluate().reasons[1], 'incoming_mortar')

    def test_observed_harmless_npc_bullet_does_not_veto_finish(self):
        # Actual v2 private observation at 50.7s, translated to our origin.
        # NPC bullets are straight projectiles, not an unknown schema kind.
        self.obs['projectiles'] = [{'id':714, 'kind':'npc',
                                   'pos':[60.86,185.15,3.89],
                                   'vel':[84.58,-30.42,4.6]}]
        result = self.evaluate()
        self.assertTrue(result.allows(self.a))
        self.assertEqual(result.reasons[1], 'safe_current_position')

    def test_incoming_npc_bullet_still_vetoes_finish(self):
        self.obs['projectiles'] = [{'kind':'npc','pos':[-40,0,4],'vel':[90,0,0]}]
        result = self.evaluate()
        self.assertFalse(result.allowed_ids)
        self.assertEqual(result.reasons[1], 'incoming_projectile')

    def test_repair_callback_is_per_candidate_and_uncertainty_is_not_permission(self):
        result = self.evaluate(repair_before_finish=lambda actor: actor['id']==1)
        self.assertFalse(result.allows(self.a))
        self.assertTrue(result.allows(self.b))
        self.assertEqual(result.reasons[1], 'opponent_repair')
        result = self.evaluate(repair_before_finish=lambda actor: None)
        self.assertEqual(result.reasons[1], 'repair_unknown')
        def failure(actor):
            raise ValueError('not available')
        self.assertEqual(self.evaluate(repair_before_finish=failure).reasons[1], 'repair_unknown')

    def test_expired_runtime_budget_does_not_approve_unchecked_corridor(self):
        with patch('positioning.time.perf_counter',side_effect=[0,.003,.004]):
            result = self.evaluate()
        self.assertFalse(result.allowed_ids)
        self.assertEqual(result.reasons[1], 'budget_exhausted')


if __name__ == '__main__':
    unittest.main()
