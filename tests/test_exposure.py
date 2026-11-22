"""Incoming cover geometry, explicit uncertainty and bounded ray work."""
import copy
import gzip
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exposure import ExposureModel


class ExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ROOT / 'check/stream.jsonl.gz', 'rt', encoding='utf-8') as stream:
            cls.config = json.loads(next(stream))['config']

    def setUp(self):
        self.me = {'pos': [0., 0., 0.], 'cubes': 0, 'stats': dict(self.config['mech'])}
        self.actor = {'id': 1, 'kind': 'mech', 'pos': [100., 0., 0.],
                      'cubes': 0, 'weapons': ['gun']}

    @staticmethod
    def wall_at(x, height):
        def ray(a, b):
            if abs(b[0] - a[0]) < 1e-12:
                return True
            fraction = (x - a[0]) / (b[0] - a[0])
            return not (0 <= fraction <= 1 and a[2] + fraction * (b[2] - a[2]) <= height)
        return ray

    def test_outgoing_blocked_does_not_mean_incoming_blocked(self):
        # Our muzzle is behind cover but our upper body remains exposed.
        # Geometric rays are symmetric; these tests have different endpoints.
        model = ExposureModel(self.config, self.wall_at(5., 7.5))
        self.assertFalse(model.outgoing(self.me, self.actor).visible)
        self.assertTrue(model.incoming(self.me, self.actor).visible)

    def test_outgoing_clear_does_not_mean_incoming_clear(self):
        # The enemy's muzzle is blocked while its upper body is targetable.
        model = ExposureModel(self.config, self.wall_at(95., 7.5))
        self.assertTrue(model.outgoing(self.me, self.actor).visible)
        self.assertFalse(model.incoming(self.me, self.actor).visible)

    def test_first_clear_sample_uses_one_ray_and_preserves_bounds(self):
        calls = []
        model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or True)
        result = model.incoming(self.me, self.actor)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result.visible)
        self.assertIsNone(result.fraction)
        self.assertEqual((result.lower_fraction, result.upper_fraction), (.5, 1.))
        self.assertEqual(result.conservative_fraction, 1.)

    def test_recovery_width_can_expose_body_after_both_center_rays_block(self):
        calls = []
        model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or abs(b[1]) > 1)
        result = model.incoming(self.me, self.actor, include_width=True, max_rays=4)
        self.assertTrue(result.visible)
        self.assertEqual(len(calls), 3, 'Stop once a flank sample proves exposure')
        self.assertEqual(result.unknown, 1)

    def test_unchecked_recovery_width_is_unknown_not_protected(self):
        model = ExposureModel(self.config, lambda a, b: False)
        result = model.incoming(self.me, self.actor, include_width=True, max_rays=2)
        self.assertIsNone(result.visible)
        self.assertEqual((result.blocked, result.unknown, result.rays), (2, 2, 2))
        self.assertEqual(result.conservative_fraction, 1.)

    def test_recovery_width_uses_cube_scaled_collision_dimensions_once(self):
        self.me['cubes'] = 8
        self.me['stats'].update(radius=2.5, height=9, muzzle_height=9.8, eye_height=11.2)
        self.actor['cubes'] = 15
        calls = []
        model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or False)
        result = model.incoming(self.me, self.actor, position=[10, 0, 30],
                                include_width=True, max_rays=4)
        self.assertFalse(result.visible)
        self.assertEqual(result.rays, 4)
        self.assertAlmostEqual(calls[0][0][2], 7 * 1.75)
        self.assertAlmostEqual(calls[0][1][2], 30 + 9 * 1.4 * .9)
        self.assertAlmostEqual(calls[2][1][2], 30 + 9 * 1.4 * .9)
        self.assertAlmostEqual(abs(calls[2][1][1]), 2.5 * 1.4 * .8)

    def test_recovery_width_honors_effective_stats_without_rescaling(self):
        self.me['cubes'] = 8
        calls = []
        model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or False)
        stats = dict(self.config['mech'], radius=3.5, height=12.6)
        model.incoming(self.me, self.actor, effective_stats=stats, include_width=True, max_rays=4)
        self.assertAlmostEqual(calls[0][1][2], 12.6 * .9)
        self.assertAlmostEqual(abs(calls[2][1][1]), 3.5 * .8)

    def test_upper_body_only_has_resolved_half_sample_fraction(self):
        model = ExposureModel(self.config, lambda a, b: b[2] > 6)
        result = model.incoming(self.me, self.actor)
        self.assertTrue(result.visible)
        self.assertEqual(result.rays, 2)
        self.assertEqual(result.fraction, .5)

    def test_both_direct_samples_blocked(self):
        result = ExposureModel(self.config, lambda a, b: False).incoming(self.me, self.actor)
        self.assertFalse(result.visible)
        self.assertEqual(result.fraction, 0.)
        self.assertEqual(result.conservative_fraction, 0.)

    def test_expired_deadline_is_unknown_not_safe(self):
        with patch('exposure.time.perf_counter', return_value=10):
            result = ExposureModel(self.config, lambda a, b: False).incoming(self.me, self.actor, deadline=9)
        self.assertIsNone(result.visible)
        self.assertIsNone(result.fraction)
        self.assertEqual(result.rays, 0)
        self.assertEqual(result.conservative_fraction, 1.)
        self.assertIn('deadline', result.reasons)

    def test_budget_after_one_blocked_sample_keeps_upper_body_unknown(self):
        result = ExposureModel(self.config, lambda a, b: False).incoming(self.me, self.actor, max_rays=1)
        self.assertIsNone(result.visible)
        self.assertEqual((result.blocked, result.unknown, result.rays), (1, 1, 1))
        self.assertEqual(result.upper_fraction, .5)
        self.assertEqual(result.conservative_fraction, 1.)

    def test_deadline_is_checked_between_uncached_rays(self):
        clock = [10.]
        def slow_blocked(a, b):
            clock[0] = 12.
            return False
        model = ExposureModel(self.config, slow_blocked)
        with patch('exposure.time.perf_counter', side_effect=lambda: clock[0]):
            result = model.incoming(self.me, self.actor, deadline=11.)
        self.assertIsNone(result.visible)
        self.assertEqual((result.blocked, result.unknown, result.rays), (1, 1, 1))
        self.assertIn('deadline', result.reasons)
        self.assertEqual(result.conservative_fraction, 1.)

    def test_exact_cache_reuses_rays_without_rounding_nearby_positions(self):
        calls = []
        model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or False)
        self.assertEqual(model.incoming(self.me, self.actor).rays, 2)
        self.assertEqual(model.incoming(self.me, self.actor, max_rays=0).rays, 0)
        self.assertFalse(model.incoming(self.me, self.actor, max_rays=0).visible)
        self.me['pos'][0] += .000001
        self.assertIsNone(model.incoming(self.me, self.actor, max_rays=0).visible)
        self.assertEqual(len(calls), 2)

    def test_shared_frame_budget_cannot_be_replenished_by_same_token(self):
        model = ExposureModel(self.config, lambda a, b: False)
        model.begin_frame(10, ray_budget=2)
        self.assertFalse(model.incoming(self.me, self.actor).visible)
        model.begin_frame(10, ray_budget=100)
        self.actor['pos'][0] += 1
        self.assertIsNone(model.incoming(self.me, self.actor).visible)
        model.begin_frame(11, ray_budget=2)
        self.assertFalse(model.incoming(self.me, self.actor).visible)

    def test_live_self_geometry_and_enemy_cubes_are_scaled_once(self):
        self.me.update(cubes=10)
        self.me['stats'].update(height=10., radius=3., muzzle_height=10.5)
        self.actor.update(cubes=4)
        calls = []
        model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or False)
        model.incoming(self.me, self.actor)
        self.assertAlmostEqual(calls[0][0][2], 8.4)
        self.assertAlmostEqual(calls[0][1][2], 7.5)
        self.assertAlmostEqual(calls[1][1][2], 13.5)
        calls.clear()
        model.outgoing(self.me, self.actor)
        self.assertAlmostEqual(calls[0][0][2], 10.5)
        self.assertAlmostEqual(calls[0][1][2], 5.4)

    def test_effective_stats_and_proposed_position_are_not_scaled_again(self):
        self.me['cubes'] = 10
        calls = []
        model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or True)
        model.incoming(self.me, self.actor, position=[10, 20, 30],
                       effective_stats={'height': 15., 'muzzle_height': 10.5})
        self.assertEqual(calls[0][1], (10, 20, 37.5))

    def test_mortar_and_unknown_weapons_cannot_be_declared_safe_by_blocked_rays(self):
        for kinds in (['mortar'], ['gun', 'mortar'], ['future_weapon'], None):
            with self.subTest(kinds=kinds):
                actor = dict(self.actor)
                if kinds is None:
                    actor.pop('weapons')
                else:
                    actor['weapons'] = kinds
                result = ExposureModel(self.config, lambda a, b: False).incoming(self.me, actor)
                self.assertIsNone(result.visible)
                self.assertIsNone(result.fraction)
                self.assertEqual(result.conservative_fraction, 1.)

    def test_npc_uses_configured_source_height_without_mech_cube_growth(self):
        config = copy.deepcopy(self.config)
        config['npc']['muzzle_height'] = 2.75
        actor = {**self.actor, 'kind': 'npc', 'cubes': 100}
        calls = []
        model = ExposureModel(config, lambda a, b: calls.append((a, b)) or True)
        model.incoming(self.me, actor)
        self.assertEqual(calls[0][0][2], 2.75)

    def test_unavailable_or_failed_geometry_remains_unknown(self):
        def failed(a, b):
            raise ValueError('fixture')
        for callback in (None, failed, lambda a, b: None):
            result = ExposureModel(self.config, callback).incoming(self.me, self.actor)
            self.assertIsNone(result.visible)
            self.assertEqual(result.conservative_fraction, 1.)

    def test_queries_preserve_inputs_and_cache_is_bounded(self):
        before = copy.deepcopy((self.me, self.actor))
        model = ExposureModel(self.config, lambda a, b: False, cache_size=2)
        model.incoming(self.me, self.actor)
        model.outgoing(self.me, self.actor)
        self.assertEqual((self.me, self.actor), before)
        self.assertLessEqual(len(model._cache), 2)
        model.clear_cache()
        self.assertEqual(len(model._cache), 0)


if __name__ == '__main__':
    unittest.main()
