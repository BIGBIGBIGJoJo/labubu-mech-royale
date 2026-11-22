"""Captured pair geometry and cycle safety; real-time budgets use Linux replay."""
import copy
import json
import math
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from arena_map import ArenaMap
from bot import Bot

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT/'tests/fixtures/reload-cover-96_4.json').read_text())


class ReloadCoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arena = ArenaMap(ROOT/'arena', DATA['config'])
        assert cls.arena.available and len(cls.arena.prisms) == 259

    def setUp(self):
        self.obs = copy.deepcopy(DATA['obs'])
        with patch('bot.ArenaMap', return_value=self.arena):
            self.bot = Bot({'config': DATA['config'], 'map': {'dir': str(ROOT/'arena')}, 'slot': 0})
        self.helper = self.bot.reload_cover
        self.target = self.obs['mechs'][0]
        self.stats = self.bot.stats(self.obs['self'])
        self.bot.combat.plan(self.obs, self.target)

    def step(self, eligible=True):
        # Fixed-clock tests certify geometry/state only, never wall-clock speed.
        with patch('time.perf_counter', return_value=0.):
            return self.helper.step(self.obs, self.target, self.stats, eligible, .019)

    def admit(self):
        goal = self.step()
        self.assertIsNotNone(goal, self.helper.last_report)
        self.assertTrue(self.helper.last_report['admitted'])
        return goal

    def test_captured_reload_discovers_local_pair_with_complete_ground_proof(self):
        goal = self.admit()
        self.assertLessEqual(((goal[0]+68.73)**2+(goal[1]-78.82)**2)**.5, 6.0001)
        self.assertEqual(self.helper.pair['P'], tuple(self.obs['self']['pos']))
        self.assertTrue(self.helper.last_report['incoming_complete'])
        self.assertTrue(self.helper.last_report['static_complete'])
        # The target is 16-cube sized; a clear outgoing gun solution is not a
        # claim that the first slew tick is aligned or protection is continuous.
        self.assertEqual(self.target['cubes'], 16)
        self.assertFalse(self.bot.combat._aligned(
            self.bot.combat._slewed(self.obs['self']['aim'], self.bot.combat.last_report['solution']['aim'], self.stats),
            self.bot.combat.last_report['solution'], *self.bot.combat._body(self.target), .2))

    def test_expired_budget_does_not_admit_a_shelter(self):
        self.assertIsNone(self.helper.step(self.obs, self.target, self.stats, True, time.perf_counter()-1))
        self.assertIsNone(self.helper.pair)

    def test_stale_or_unclear_same_call_solution_cannot_admit(self):
        self.bot.combat.last_report['tick'] -= 1
        self.assertIsNone(self.step())
        self.bot.combat.last_report['tick'] += 1
        self.bot.combat.last_report['solution']['clear'] = False
        self.assertIsNone(self.step())

    def test_budget_unknown_keeps_candidate_cursor_for_next_observation(self):
        p = self.obs['self']['pos']
        shelter = (p[0], p[1]+6, self.arena.ground_height(p[0], p[1]+6))
        with patch.object(self.helper, '_candidates', return_value=[shelter]), \
             patch.object(self.helper, '_protected', side_effect=[True, None]):
            self.assertIsNone(self.step())
        self.assertEqual(self.helper._cursor, 0)
        with patch.object(self.helper, '_candidates', return_value=[shelter]):
            self.assertIsNotNone(self.step())

    def test_dense_anchor_cap_keeps_bounded_candidates_and_expiry_keeps_none(self):
        p = self.obs['self']['pos']
        covers = [(p[0]+3+i*.01, p[1], p[2], 0, 1, 20) for i in range(140)]
        bins = {(math.floor(p[0]/self.arena.BIN), math.floor(p[1]/self.arena.BIN)): list(range(140))}
        with patch.object(self.arena, '_cover', covers), patch.object(self.arena, '_cover_bins', bins), \
             patch('time.perf_counter', return_value=0.):
            self.assertEqual(len(list(self.helper._candidates(p, self.stats, 1.))), 128)
            self.assertEqual(list(self.helper._candidates(p, self.stats, -1.)), [])

    def test_same_call_ray_memo_never_overrides_expired_deadline(self):
        self.helper._incoming = {}
        with patch('time.perf_counter', return_value=0.):
            self.assertIs(self.helper._protected(self.obs['self']['pos'], [], self.stats, 1.), True)
            self.assertIsNone(self.helper._protected(self.obs['self']['pos'], [], self.stats, -1.))

    def test_travel_estimate_budgets_stationary_toward_away_and_large_braking(self):
        a, b = (0., 0., 0.), (6., 0., 0.)
        speed, accel = self.stats['walk_speed'], self.stats['ground_accel']
        stationary = 6/speed+speed/accel+self.bot.combat.action_dt
        self.assertAlmostEqual(self.helper._travel(a, b, (0, 0), self.stats), stationary)
        for velocity in ((speed, 0), (-speed, 0), (40., 0), (0, -40.)):
            with self.subTest(velocity=velocity):
                magnitude = math.hypot(*velocity)
                estimate = self.helper._travel(a, b, velocity, self.stats)
                self.assertAlmostEqual(estimate, stationary+magnitude/accel+magnitude*magnitude/(2*accel*speed))
                self.assertGreater(estimate, stationary+magnitude/accel)
        # We deliberately budget the same worst-direction braking displacement
        # for toward/away motion, rather than promise a favorable controller turn.
        self.assertEqual(self.helper._travel(a, b, (speed, 0), self.stats),
                         self.helper._travel(a, b, (-speed, 0), self.stats))

    def test_incomplete_route_is_not_cached_as_blocked_or_cursor_skipped(self):
        p = self.obs['self']['pos']
        shelter = (p[0], p[1]+6, self.arena.ground_height(p[0], p[1]+6))
        with patch.object(self.helper, '_candidates', return_value=[shelter]), \
             patch.object(self.helper, '_route', return_value=None):
            self.assertIsNone(self.step())
        self.assertEqual(self.helper._cursor, 0)
        self.assertFalse(self.helper._geometry)
        with patch.object(self.helper, '_candidates', return_value=[shelter]):
            self.assertIsNotNone(self.step())

    def test_ready_gun_or_secondary_prevents_entry(self):
        self.obs['self']['weapons'][0]['reload'] = 0
        self.assertIsNone(self.step())
        self.obs['self']['weapons'][0]['reload'] = 2.35
        self.obs['self']['weapons'][1] = {'kind': 'laser', 'charge': 0, 'cooldown': 1.65}
        self.assertIsNone(self.step())

    def test_off_terrain_grounded_and_airborne_prevent_entry(self):
        self.obs['self']['pos'][2] += 9
        self.assertIsNone(self.step())
        self.obs['self']['pos'][2] -= 9
        self.obs['self']['grounded'] = False
        self.assertIsNone(self.step())

    def test_cube_on_corridor_rejects_growth_before_it_happens(self):
        self.obs['cubes'] = [{'id': 999, 'pos': list(self.obs['self']['pos'])}]
        self.assertIsNone(self.step())

    def test_deviated_return_checks_actual_connector_for_incidental_cube(self):
        self.admit()
        P, S, current = (0., 0., 0.), (0., 6., 0.), (3., 3., 0.)
        self.helper.pair.update(P=P, S=S, phase='return')
        self.obs['self']['pos'] = list(current)
        self.obs['cubes'] = [{'id': 999, 'pos': [3.904, -.904, 0.]}]
        self.assertFalse(self.helper._cube_corridor(self.obs, current, S))
        self.assertFalse(self.helper._cube_corridor(self.obs, S, P))
        self.assertTrue(self.helper._cube_corridor(self.obs, current, P))
        with patch.object(self.helper.ground, '_ground_scope', return_value=True), \
             patch.object(self.helper, '_zone_safe', return_value=True):
            self.assertIsNone(self.step())
        self.assertEqual(self.helper.last_report['reason'], 'zone_or_growth')

    def test_indirect_or_chain_threat_is_not_certified_by_rays(self):
        self.target['weapons'].append('mortar')
        self.assertIsNone(self.step())
        self.target['weapons'][-1] = 'lightning'
        self.assertIsNone(self.step())

    def test_private_schedule_extends_only_verified_post_shrink_hold(self):
        self.assertAlmostEqual(self.helper._known_zone_until(self.obs), 115.)
        self.obs['zone']['shrink_start'] += 1
        self.assertAlmostEqual(self.helper._known_zone_until(self.obs), 97.5)
        self.assertFalse(self.helper._zone_safe(self.obs, [self.obs['self']['pos']], 2.5, 98))

    def test_final_phase_has_no_unannounced_following_hold(self):
        zone = self.obs['zone']
        phases = DATA['config']['zone']['phases']
        start = sum(p['hold_s']+p['shrink_s'] for p in phases[:-1])+phases[-1]['hold_s']
        end = start+phases[-1]['shrink_s']
        zone.update(shrink_start=start, shrink_end=end, next_radius=0)
        self.assertEqual(self.helper._known_zone_until(self.obs), end)

    def test_observed_target_retained_through_own_outgoing_occlusion_only(self):
        self.admit()
        self.assertIs(self.helper.retain_target(self.obs, None, True), self.target)
        self.assertIsNone(self.helper.retain_target(self.obs, None, False))
        self.assertIsNone(self.helper.pair)
        self.assertIsNone(self.step())  # Same partial reload cannot immediately restart.

    def test_absent_or_different_priority_target_cancels(self):
        self.admit()
        other = {**self.target, 'id': 99}
        self.assertIs(self.helper.retain_target(self.obs, other, True), other)
        self.assertIsNone(self.helper.pair)
        self.helper._blocked_until = -1
        self.admit()
        self.obs['mechs'] = []
        self.assertIsNone(self.helper.retain_target(self.obs, None, True))

    def test_body_growth_cancels_even_with_same_target(self):
        self.admit()
        self.stats['radius'] *= 1.05
        self.stats['height'] *= 1.05
        self.assertIsNone(self.step())
        self.assertEqual(self.helper.last_report['reason'], 'body_target_or_cycle_changed')

    def test_arrival_requires_actual_protection_and_return_starts_before_ready(self):
        shelter = self.admit()
        self.obs['t'] += .5
        self.obs['self']['pos'] = list(shelter)
        self.obs['self']['vel'] = [0, 0, 0]
        self.obs['self']['weapons'][0]['reload'] = 1.85
        self.assertIsNotNone(self.step())
        self.assertEqual(self.helper.pair['phase'], 'hold')
        self.assertIs(self.helper.last_report['actual_protected'], True)
        self.obs['t'] += .7
        self.obs['self']['weapons'][0]['reload'] = .6
        goal = self.step()
        self.assertEqual(goal, self.helper.pair['P'])
        self.assertEqual(self.helper.pair['phase'], 'return')

    def test_near_shelter_exposed_position_is_not_hold(self):
        shelter = self.admit()
        self.obs['self']['pos'] = [shelter[0]+.2, shelter[1], shelter[2]]
        original = self.helper._protected
        def protected(point, *args):
            return False if tuple(point) == tuple(self.obs['self']['pos']) else original(point, *args)
        with patch.object(self.helper, '_protected', side_effect=protected):
            self.step()
        self.assertEqual(self.helper.pair['phase'], 'out')
        self.assertIs(self.helper.last_report['actual_protected'], False)

    def test_no_progress_and_expired_dynamic_proof_cancel(self):
        self.admit()
        self.obs['t'] += 1.1
        # Remaining reload is deliberately held here to isolate observed
        # progress from the separate return-start condition.
        self.assertIsNone(self.step())
        self.assertEqual(self.helper.last_report['reason'], 'no_observed_progress')
        self.helper._blocked_until = -1
        self.obs = copy.deepcopy(DATA['obs'])
        self.target = self.obs['mechs'][0]
        self.admit()
        self.assertIsNone(self.helper.step(self.obs, self.target, self.stats, True, time.perf_counter()-1))
        self.assertIsNone(self.helper.pair)


if __name__ == '__main__':
    unittest.main()
