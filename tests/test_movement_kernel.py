"""Parity of the optional loaded-map movement kernel and unchanged Python.

Geometry is immutable after loading. Replacement/configuration/custom-method
cases test the wrapper's Python fallback; they are not a promise to detect
arbitrary in-place edits to nested prism metadata. The original move_clear
ignores end Z, which these tests preserve rather than treating as validated.
"""
from array import array
import gzip
import json
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import arena_map
import native_map
from tactical import TacticalPlanner

ROOT = Path(__file__).resolve().parents[1]
if os.environ.get('MECH_REQUIRE_MOVEMENT_NATIVE') and native_map._create is None:
    raise RuntimeError('Movement kernel is required for this run')


def write_world(root, *, slope=False):
    path = root/'v2'
    path.mkdir(parents=True)
    world = {
        'bounds': {'minX': 0, 'minY': 0, 'maxX': 40, 'maxY': 40},
        'terrain': {'file': 'terrain.i16', 'minX': 0, 'minY': 0,
                    'step': 1, 'nx': 41, 'ny': 41, 'scale': .01},
        'prisms': [
            {'kind': 'building', 'base': 0, 'top': 15,
             'ring': [6,6,14,6,14,14,6,14], 'holes': [[8,8,12,8,12,12,8,12]]},
            {'kind': 'bridge', 'base': 12, 'top': 14,
             'ring': [20,6,24,6,24,14,20,14], 'holes': []},
            {'kind': 'step', 'base': 0, 'top': 1,
             'ring': [28,20,32,20,32,24,28,24], 'holes': []},
        ]}
    heights = [round(max(0, min(10, (x-21)*10/3))*100) if slope else 0
               for y in range(41) for x in range(41)]
    samples = array('h', heights)
    if sys.byteorder != 'little':
        samples.byteswap()
    (path/'world.json').write_text(json.dumps(world))
    (path/'terrain.i16').write_bytes(samples.tobytes())


@unittest.skipIf(native_map._create is None, 'compiled movement kernel unavailable')
class MovementKernelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='movement-kernel-')
        cls.root = Path(cls.directory.name)
        write_world(cls.root/'flat')
        write_world(cls.root/'slope', slope=True)
        write_world(cls.root/'precision')
        precision_path = cls.root/'precision/v2/world.json'
        precision = json.loads(precision_path.read_text())
        precision['bounds'] = {'minX':-20,'minY':-20,'maxX':20,'maxY':20}
        precision['terrain'].update(minX=-20,minY=-20)
        precision['prisms'] = [{'kind':'building','base':0,'top':10,
                                'ring':[0,-10,10,-10,10,10,0,10], 'holes':[]}]
        precision_path.write_text(json.dumps(precision))
        ridge_path = cls.root/'sampling/v2'
        ridge_path.mkdir(parents=True)
        ridge = {'bounds':{'minX':0,'minY':0,'maxX':40,'maxY':40},
                 'terrain':{'file':'terrain.i16','minX':0,'minY':0,'step':.5,
                            'nx':81,'ny':81,'scale':.01},
                 'prisms':[{'kind':'bridge','base':10.7,'top':11.7,
                            'ring':[17.45,20,17.55,20,17.55,30,17.45,30],'holes':[]}]}
        samples = array('h',[round(max(0,1.8-abs(x*.5-17.5)*.72)*100)
                             for y in range(81) for x in range(81)])
        if sys.byteorder!='little':
            samples.byteswap()
        (ridge_path/'world.json').write_text(json.dumps(ridge))
        (ridge_path/'terrain.i16').write_bytes(samples.tobytes())
        cls.config = {'mech': {'step_up': 1.2, 'max_slope_deg': 50}}
        cls.flat = native_map.ArenaMap(cls.root/'flat', cls.config)
        cls.slope = native_map.ArenaMap(cls.root/'slope', cls.config)
        cls.precision = native_map.ArenaMap(cls.root/'precision', cls.config)
        cls.sampling = native_map.ArenaMap(cls.root/'sampling', cls.config)
        for arena in (cls.flat, cls.slope, cls.precision, cls.sampling):
            assert arena.available and arena.movement_kernel_status == 'loaded'
        with gzip.open(ROOT/'check/stream.jsonl.gz', 'rt') as stream:
            cls.full_config = json.loads(next(stream))['config']

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def parity(self, arena, start, end, radius, height, expected=None):
        python = arena_map.ArenaMap.move_clear(arena, start, end, radius, height)
        native = arena.move_clear(start, end, radius, height)
        self.assertEqual(native, python, (start, end, radius, height))
        if expected is not None:
            self.assertEqual(python, expected, (start, end, radius, height))
        return native

    def test_continuous_corner_contact_and_courtyard_hole(self):
        cases = [
            ((3,4,0), (16,4,0), 2.5, 9, False),
            ((3,3,0), (16,3,0), 2.5, 9, True),
            ((3,10,0), (17,10,0), 1, 9, False),
            ((9.5,10,0), (10.5,10,0), .5, 9, True),
            ((10,10,0), (10,10,0), 3, 9, False),
            ((3.501,10,0), (2.75,10,0), 2.5, 9, True),
            ((3.501,10,0), (4,10,0), 2.5, 9, False),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.parity(self.flat, *case)

    def test_bridge_roof_drop_step_and_body_dimensions(self):
        cases = [
            ((17,10,0), (27,10,0), 1, 9, True),
            ((17,10,0), (27,10,0), 1, 13, False),
            ((21,8,14), (23,12,14), .5, 9, True),
            ((7,7,15), (13,7,15), .5, 9, True),
            ((13,7,15), (17,7,0), .5, 9, True),
            ((26,22,0), (34,22,0), 1, 9, True),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.parity(self.flat, *case)
        for radius in (.25, 1., 2.5, 3.5, 5.):
            for height in (3., 9., 12.6, 15.):
                self.parity(self.flat, (17,18,0), (27,18,0), radius, height)

    def test_directional_steep_grade_and_cell_boundary_cuts(self):
        self.parity(self.slope, (25,30,10), (20,30,0), 2.5, 9, True)
        self.parity(self.slope, (20,30,0), (25,30,10), 2.5, 9, False)
        for start, end in [((21.,30,0),(24.,30,10)),
                           ((20.999999,29.5,0),(24.000001,30.5,10)),
                           ((22,28,10/3),(22,32,10/3)),
                           ((25,30,10),(25.0000001,30,10))]:
            self.parity(self.slope, start, end, .5, 4.)
            self.parity(self.slope, end, start, .5, 4.)

    def test_arena_center_margin_and_growth_do_not_double_count_radius(self):
        arena = native_map.ArenaMap(self.root/'flat',
                    {'match': {'arena_margin': 5}, 'mech': self.config['mech']})
        self.assertEqual(arena.movement_kernel_status, 'loaded')
        self.parity(arena, (5,30,0), (6,30,0), 2.5, 9, True)
        self.parity(arena, (6,30,0), (4.9,30,0), 2.5, 9, False)
        self.parity(arena, (5,30,0), (5,30,0), 6, 9, False)
        for x in (5-1.1e-6, 5-1e-6, 5, 35, 35+1e-6, 35+1.1e-6):
            self.parity(arena, (10,30,0), (x,30,0), 2.5, 9)

    def test_zero_length_and_ignored_requested_end_height_match_base(self):
        for end_z in (-100, 0, 100):
            self.parity(self.flat, (18,20,0), (18,20,end_z), 1, 9, True)
            self.parity(self.flat, (17,20,0), (18,20,end_z), 1, 9, True)
        # This preserves a baseline limitation, not a terminal-height proof.

    def test_pow_rounding_contact_and_nextafter_thresholds(self):
        # The original Windows witness rounds differently on Linux libm;
        # retain parity without imposing its host-specific boolean outcome.
        x = -2.75826454639852
        radius = abs(x)+.015
        self.parity(self.precision, (x,0,0), (x,0,0), radius, 9)
        # Verified on this pinned Linux runtime: Python **2 is 1 ULP below
        # x*x. Capsule -1e-6 admits contact; strict point_clear must reject it.
        x = -3.436167995905102
        radius = abs(x)+.015
        self.parity(self.precision, (x,0,0), (x,0,0), radius, 9, False)
        for radius in (.5, 1., 2.5, radius, 3.5):
            contact_x = -(radius-self.precision.CONTACT_EPS)
            positions = [contact_x]
            low = high = contact_x
            for _ in range(4):
                low, high = math.nextafter(low,-math.inf), math.nextafter(high,math.inf)
                positions.extend((low,high))
            for position in positions:
                self.parity(self.precision, (position,0,0), (position,0,0), radius, 9)
                self.parity(self.precision, (position,-1,0), (position,1,0), radius, 9)

    def test_sampling_count_boundaries_use_same_hypot_distance(self):
        for radius in (.5, 1., 2.5, 3.5):
            stride = max(.8,min(2.,radius*.65))
            for count in (1,2,3):
                threshold = count*stride
                for length in (math.nextafter(threshold,0),threshold,math.nextafter(threshold,math.inf)):
                    for dx,dy in ((1.,0.),(.6,.8)):
                        start = (-15.,14.,0.)
                        end = (start[0]+dx*length,start[1]+dy*length,0.)
                        self.parity(self.precision,start,end,radius,4.)

    def test_sampling_boundary_changes_actual_overhang_collision_result(self):
        # A .72-grade ridge peaks at1.8m below a thin10.7m overhang. The
        # four-sample path visits its peak; three samples miss the peak. This
        # makes the original result genuinely sensitive to sample count.
        start,end=(15.,25.,0.),(20.,25.,0.)
        for radius,height,expected in ((2.5,9.,False),(3.,9.5,True),(3.,10.,False),
                                       (2.56,9.5,False),(2.57,9.5,True)):
            with self.subTest(radius=radius,height=height):
                self.assertTrue(self.sampling.point_clear(start,radius,height))
                self.assertTrue(self.sampling.point_clear(end,radius,height))
                self.parity(self.sampling,start,end,radius,height,expected)

    def test_exact_corrected_rollout_matches_with_supported_and_airborne_steps(self):
        stats = dict(self.full_config['mech'])
        stats.update(radius=.5, height=4.)
        pairs = [(self.flat, (27,22,0), (9,0,0), True, (1,0)),
                 (self.flat, (13,7,15), (8,0,0), True, (1,0)),
                 (self.flat, (18,20,4), (3,0,-2), False, (1,0)),
                 (self.slope, (25,30,10), (-8,0,0), True, (-1,0))]
        for arena, pos, velocity, grounded, direction in pairs:
            with self.subTest(pos=pos, velocity=velocity):
                planner = TacticalPlanner(self.full_config, arena)
                me = {'pos':pos,'vel':velocity,'grounded':grounded,'energy':100.,'weapons':[None,None]}
                path = planner.rollout(me, direction, False, stats)
                native = planner._geometry(path, stats, time.perf_counter()+10, direction, False, False)
                with patch.object(arena, '_movement_context', None):
                    python = planner._geometry(path, stats, time.perf_counter()+10, direction, False, False)
                self.assertEqual(native, python)

    def test_loaded_real_map_recorded_low_bridge_and_body_growth(self):
        arena = native_map.ArenaMap(ROOT/'arena', self.full_config)
        self.assertTrue(arena.available)
        self.assertEqual(len(arena.prisms), 259)
        self.assertEqual(arena.movement_kernel_status, 'loaded')
        start = (-117.66,-25.95,-4.87)
        self.parity(arena, start, (-116.84,-27.77,-4.87), 2.5, 9, True)
        self.parity(arena, start, (-116.84,-27.77,-4.87), 3.5, 12.6, False)
        self.parity(arena, start, (-118.48,-24.13,-4.87), 3.5, 12.6, True)
        rng = random.Random(32691)
        anchors = [(-68.49,74.28), (-173.47,76.06), (-20.42,-78.08),
                   (-117.66,-25.95), (7.93,-20.17), (-33.4,-301.67)]
        for x, y in anchors:
            for _ in range(16):
                angle, distance = rng.uniform(-math.pi, math.pi), rng.uniform(0, 12)
                start = (x,y,arena.ground_height(x,y))
                end = (x+math.cos(angle)*distance,y+math.sin(angle)*distance,start[2])
                radius, height = rng.choice(((2.5,9),(2.625,9.45),(3.5,12.6)))
                self.parity(arena, start, end, radius, height)
                self.parity(arena, end, start, radius, height)

    def fallback(self, arena, *, start=(17,20,0), end=(18,20,0)):
        with patch.object(native_map, '_clear', side_effect=AssertionError('native dispatch must be skipped')):
            self.assertEqual(arena.move_clear(start,end,1,9),
                             arena_map.ArenaMap.move_clear(arena,start,end,1,9))

    def test_replaced_geometry_methods_use_python_fallback(self):
        for name in native_map._methods:
            with self.subTest(method=name):
                arena = native_map.ArenaMap(self.root/'flat', self.config)
                original = getattr(arena, name)
                with patch.object(arena, name, wraps=original):
                    self.fallback(arena)

    def test_replaced_samples_bins_prisms_and_configuration_use_fallback(self):
        changes = [('samples', lambda a: array('h', a.samples)),
                   ('bins', lambda a: dict(a.bins)),
                   ('prisms', lambda a: list(a.prisms)),
                   ('step_up', lambda a: a.step_up+.1),
                   ('max_slope', lambda a: a.max_slope+.01),
                   ('arena_margin', lambda a: a.arena_margin+.5),
                   ('CONTACT_EPS', lambda a: a.CONTACT_EPS*.5)]
        for name, change in changes:
            with self.subTest(field=name):
                arena = native_map.ArenaMap(self.root/'flat', self.config)
                setattr(arena, name, change(arena))
                self.fallback(arena)
        for name, key, delta in [('terrain','scale',.001), ('bounds','maxX',1.)]:
            arena = native_map.ArenaMap(self.root/'flat', self.config)
            replacement = dict(getattr(arena,name))
            replacement[key] += delta
            setattr(arena,name,replacement)
            self.fallback(arena)

    def test_absent_context_or_unsupported_native_result_uses_python(self):
        with patch.object(native_map, '_create', None):
            arena = native_map.ArenaMap(self.root/'flat', self.config)
        self.assertIsNone(arena._movement_context)
        self.fallback(arena)
        arena = native_map.ArenaMap(self.root/'flat', self.config)
        with patch.object(native_map, '_clear', return_value=-1) as native:
            self.assertEqual(arena.move_clear((17,20,0),(18,20,0),1,9),
                             arena_map.ArenaMap.move_clear(arena,(17,20,0),(18,20,0),1,9))
        native.assert_called_once()


if __name__ == '__main__':
    unittest.main()
