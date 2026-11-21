"""Observed vertical motion and supporting-surface regressions."""
from array import array
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from arena_map import ArenaMap
from target_motion import TargetMotion

with gzip.open(ROOT/'check/stream.jsonl.gz','rt') as stream:
    CONFIG=json.loads(next(stream))['config']


class Ground:
    available=True
    def support_height(self,x,y,previous_z):
        return 0.0


def actor(z=100,vz=-3.2,ident=7):
    return {'id':ident,'kind':'mech','pos':[10.,20.,z],'vel':[2.,3.,vz],'cubes':0}


class TargetMotionTests(unittest.TestCase):
    def setUp(self):
        self.motion=TargetMotion(CONFIG,Ground())
        self.previous=actor(100,-1)
        self.current=actor(99.735,-3.2)
        self.current['pos'][:2]=[10.2,20.3]

    def observe(self,tick,target):
        self.motion.update({'tick':tick,'mechs':[target]})

    def falling(self):
        self.observe(100,self.previous)
        self.observe(102,self.current)

    def test_confirmed_freefall_preserves_horizontal_constant_velocity(self):
        self.falling()
        predicted=self.motion.forecast(self.current,.4)
        self.assertEqual(predicted[:2],[11.,21.5])
        self.assertAlmostEqual(predicted[2],99.735-3.2*.4-.5*22*.4**2)

    def test_no_history_uses_supported_constant_velocity(self):
        self.observe(102,self.current)
        self.assertAlmostEqual(self.motion.forecast(self.current,.4)[2],99.735-3.2*.4)

    def test_observation_gap_and_absence_do_not_confirm_gravity(self):
        for missing in (False,True):
            with self.subTest(missing=missing):
                self.motion=TargetMotion(CONFIG,Ground())
                self.observe(100,self.previous)
                if missing:
                    self.motion.update({'tick':102,'mechs':[]})
                self.observe(104,self.current)
                self.assertAlmostEqual(self.motion.forecast(self.current,.4)[2],99.735-3.2*.4)

    def test_tick_reset_and_reused_id_do_not_inherit_gravity(self):
        self.falling()
        self.observe(2,self.current)
        self.assertAlmostEqual(self.motion.forecast(self.current,.4)[2],99.735-3.2*.4)
        self.observe(4,actor(200,-5.4))
        self.assertAlmostEqual(self.motion.forecast(actor(200,-5.4),.4)[2],200-5.4*.4)

    def test_duplicate_observation_does_not_replace_previous_evidence(self):
        self.falling()
        before=self.motion.forecast(self.current,.4)
        self.observe(102,copy.deepcopy(self.current))
        self.assertEqual(self.motion.forecast(self.current,.4),before)

    def test_stale_actor_snapshot_cannot_use_newer_velocity_evidence(self):
        self.falling()
        self.assertAlmostEqual(self.motion.forecast(self.previous,.4)[2],100-.4)

    def test_rising_jump_is_also_gravity_when_observed(self):
        previous=actor(100,11)
        current=actor(100.935,8.8)
        self.observe(100,previous)
        self.observe(102,current)
        self.assertAlmostEqual(self.motion.forecast(current,.4)[2],100.935+8.8*.4-1.76)

    def test_jet_acceleration_is_not_assumed_to_be_freefall(self):
        self.observe(100,actor(100,1))
        current=actor(100.19,2.2)
        self.observe(102,current)
        self.assertAlmostEqual(self.motion.forecast(current,.4)[2],100.19+2.2*.4)

    def test_configured_tick_rate_and_gravity_drive_confirmation(self):
        config=copy.deepcopy(CONFIG)
        config['match'].update(tick_hz=40,decide_every=4)
        config['mech']['gravity']=30
        self.motion=TargetMotion(config,Ground())
        self.observe(100,actor(100,0))
        target=actor(99.8125,-3)
        self.observe(104,target)
        self.assertAlmostEqual(self.motion.forecast(target,.4)[2],99.8125-3*.4-.5*30*.4**2)

    def test_state_is_bounded_and_unseen_actors_are_removed(self):
        self.motion.update({'tick':100,'mechs':[actor(ident=i) for i in range(128)]})
        self.assertLessEqual(len(self.motion._actors),64)
        self.motion.update({'tick':102,'mechs':[actor(ident=80)]})
        self.assertEqual(set(self.motion._actors),{80})

    def test_input_is_unchanged_and_nonmechs_keep_constant_velocity(self):
        self.falling()
        original=copy.deepcopy(self.current)
        self.motion.forecast(self.current,.4)
        self.assertEqual(self.current,original)
        npc=actor(-1,-3)
        npc['kind']='npc'
        self.assertAlmostEqual(self.motion.forecast(npc,.4)[2],-2.2)


class SupportingGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix='mech-target-support-')
        root=Path(cls.directory.name)/'v2'
        root.mkdir()
        world={'bounds':{'minX':0,'maxX':60,'minY':0,'maxY':60},
               'terrain':{'file':'terrain.i16','minX':0,'minY':0,'step':1,'nx':61,'ny':61,'scale':.01},
               'prisms':[{'kind':'building','base':0,'top':14,'ring':[20,20,30,20,30,30,20,30],'holes':[]},
                         {'kind':'bridge','base':12,'top':14,'ring':[35,20,45,20,45,30,35,30],'holes':[]}]}
        (root/'world.json').write_text(json.dumps(world),encoding='utf-8')
        (root/'terrain.i16').write_bytes(array('h',[0]*(61*61)).tobytes())
        cls.arena=ArenaMap(root.parent,CONFIG)
        assert cls.arena.available,cls.arena.error

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_landing_clamps_to_ground_or_roof_without_teleporting_onto_bridge(self):
        for x,z,expected in ((10,3,0),(25,20,14),(40,20,14),(40,3,0)):
            with self.subTest(x=x,z=z):
                target={'id':7,'kind':'mech','pos':[x,25,z],'vel':[0,0,-20]}
                motion=TargetMotion(CONFIG,self.arena)
                motion.update({'tick':100,'mechs':[target]})
                self.assertAlmostEqual(motion.forecast(target,.6)[2],expected)

    def test_future_horizontal_position_determines_support(self):
        target={'id':7,'kind':'mech','pos':[29,25,14],'vel':[10,0,-20]}
        motion=TargetMotion(CONFIG,self.arena)
        self.assertEqual(motion.forecast(target,.4),[33,25,6])

    def test_recorded_freefall_reduces_held_out_vertical_error(self):
        if not (ROOT/'arena/v2/world.json').exists():
            self.skipTest('Official arena unavailable')
        arena=ArenaMap(ROOT/'arena',CONFIG)
        motion=TargetMotion(CONFIG,arena)
        # Baseline trace, actor8, ticks856->858; truth at tick866 is held out.
        before={'id':8,'kind':'mech','pos':[-215.55,11.69,.27],'vel':[3.31,-19.22,.6]}
        current={'id':8,'kind':'mech','pos':[-215.24,9.86,.17],'vel':[3,-18.06,-1.6]}
        truth_z=-2.45
        motion.update({'tick':856,'mechs':[before]})
        motion.update({'tick':858,'mechs':[current]})
        forecast=motion.forecast(current,.4)
        self.assertAlmostEqual(forecast[2],-2.23)
        self.assertLess(abs(forecast[2]-truth_z),.3)
        self.assertGreater(abs(current['pos'][2]+current['vel'][2]*.4-truth_z),1.9)


if __name__=='__main__':
    unittest.main()
