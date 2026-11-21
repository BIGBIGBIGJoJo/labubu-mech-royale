"""Compiled terrain parity; requires the library in the Linux validation image."""
from array import array
import os
from pathlib import Path
import random
import unittest

from arena_map import ArenaMap
from terrain_kernel import make_kernel, _line

if os.environ.get('MECH_REQUIRE_NATIVE') and _line is None:
    raise RuntimeError('Native terrain kernel is required for this test run')


@unittest.skipIf(_line is None,'compiled terrain library unavailable on this host')
class TerrainKernelTests(unittest.TestCase):
    def synthetic(self,values,nx,ny,step=1,minimum=(-7.25,-4.5)):
        arena=ArenaMap.__new__(ArenaMap)
        arena.available=True;arena.prisms=[];arena.bins={}
        arena.nx=nx;arena.ny=ny;arena.samples=array('h',values)
        arena.terrain=dict(minX=minimum[0],minY=minimum[1],step=step,scale=.01)
        arena._terrain_kernel=make_kernel(arena)
        self.assertIsNotNone(arena._terrain_kernel)
        return arena

    def parity(self,arena,start,end):
        native=arena.line_of_fire(start,end)
        saved=arena._terrain_kernel;arena._terrain_kernel=None
        try: original=arena.line_of_fire(start,end)
        finally:arena._terrain_kernel=saved
        self.assertEqual(original,native,(start,end))

    def test_clearance_threshold_vertical_degenerate_and_grid_boundaries(self):
        arena=self.synthetic([0]*25,5,5)
        for z in (-1,0,.049999999,.05,.050000001,1,100):
            for start,end in [((-7.25,-4.5,z),(-3.25,-.5,z)),
                              ((-7.25,-4.5,z),(-7.25,-4.5,z+1)),
                              ((-5.25,-2.5,z),(-5.25,-2.5,z)),
                              ((-10,-10,z),(1,1,z))]:
                self.parity(arena,start,end)
                self.parity(arena,end,start)

    def test_saddle_interior_extremum(self):
        arena=self.synthetic([0,1000,1000,0],2,2,minimum=(0,0))
        for z in (4.99,5,5.049999,5.05,5.050001,5.2,10):
            self.parity(arena,(0,0,z),(1,1,z))

    def test_random_signed_height_fields_and_rays(self):
        rng=random.Random(79138)
        arena=self.synthetic([rng.randrange(-700,1000) for _ in range(23*19)],23,19,step=1.25)
        for _ in range(1200):
            start=(rng.uniform(-10,24),rng.uniform(-8,24),rng.uniform(-8,20))
            end=(rng.uniform(-10,24),rng.uniform(-8,24),rng.uniform(-8,20))
            self.parity(arena,start,end)

    def test_replaced_samples_or_geometry_configuration_falls_back(self):
        arena=self.synthetic([0]*9,3,3)
        old=arena._terrain_kernel
        arena.samples=array('h',[100]*9)
        self.assertIsNone(old.line_clear(arena,(0,0,2),(1,1,2)))
        self.parity(arena,(0,0,.5),(1,1,.5))
        arena.samples=old.samples;arena.terrain['scale']=.02
        self.assertIsNone(old.line_clear(arena,(0,0,2),(1,1,2)))

    def test_existing_buffer_mutation_is_observed(self):
        arena=self.synthetic([0]*9,3,3)
        self.assertTrue(arena.line_of_fire((-7,-4,.5),(-6,-3,.5)))
        for i in range(9):arena.samples[i]=100
        self.assertFalse(arena.line_of_fire((-7,-4,.5),(-6,-3,.5)))
        self.parity(arena,(-7,-4,.5),(-6,-3,.5))

    def test_official_map_full_ray_parity(self):
        root=Path(__file__).resolve().parents[1]/'arena'
        if not (root/'v2/world.json').exists():self.skipTest('official arena not mounted')
        arena=ArenaMap(root,{'mech':{'step_up':1.2,'max_slope_deg':50}})
        self.assertTrue(arena.available,arena.error)
        self.assertIsNotNone(arena._terrain_kernel)
        rng=random.Random(56324);b=arena.bounds
        for _ in range(800):
            x=rng.uniform(b['minX'],b['maxX']);y=rng.uniform(b['minY'],b['maxY'])
            ex=rng.uniform(b['minX'],b['maxX']);ey=rng.uniform(b['minY'],b['maxY'])
            start=(x,y,arena.ground_height(x,y)+rng.uniform(-.1,70))
            end=(ex,ey,arena.ground_height(ex,ey)+rng.uniform(-.1,70))
            self.parity(arena,start,end)


if __name__=='__main__':unittest.main()
