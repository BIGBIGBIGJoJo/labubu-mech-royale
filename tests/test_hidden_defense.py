"""Recorded regression for the final reload-facing override."""
import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from test_strategy import FlatArena, official_fixture
import bot as policy

ROOT=Path(__file__).resolve().parents[1]


class HiddenDefenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello,cls.recorded=official_fixture()

    def setUp(self):
        self.obs=copy.deepcopy(self.recorded)
        self.obs.update(t=20.,tick=400,alive=16,offer=None)
        for key in ('mechs','projectiles','crates','cubes','pickups','sounds','beams','events','drops'):
            self.obs[key]=[]
        self.obs['self'].update(pos=[0,0,0],vel=[0,0,0],aim=[1.2,0],hp=500,max_hp=1400,
            energy=100,max_energy=100,cubes=0,grounded=True,in_zone=True,upgrades=[],
            stats=copy.deepcopy(self.hello['config']['mech']),
            weapons=[self.weapon('gun',ammo=0,reload=1.2),None])
        self.obs['zone']={'center':[0,0],'radius':560,'next_center':[0,0],
                         'next_radius':380,'shrink_start':60,'shrink_end':110,'dps':20}
        with patch.object(policy,'ArenaMap',FlatArena):self.bot=policy.Bot(copy.deepcopy(self.hello))

    def weapon(self,kind,**values):
        result={'kind':kind,'cooldown':0,'stats':copy.deepcopy(self.hello['config']['weapons'][kind])}
        if kind=='gun':result.update(ammo=12,reload=0)
        if kind=='laser':result['charge']=0
        result.update(values)
        return result

    @staticmethod
    def enemy(x=-100,y=0,**values):
        result={'id':5,'kind':'mech','pos':[x,y,0],'vel':[0,0,0],'aim':[0,0],
                'hp':1400,'max_hp':1400,'cubes':0,'weapons':['gun'],'charging':False}
        result.update(values)
        return result

    def hurt(self,bearing=0.,who=6):
        self.obs['events']=[{'type':'damaged','weapon':'gun','by':who,'amount':45,'bearing':bearing}]

    def test_captured_21_frame_reload_sequence_preserves_damage_bearing(self):
        data=json.loads((ROOT/'tests/fixtures/hidden_reload_bearing.json').read_text())
        with patch.object(policy,'ArenaMap',FlatArena):bot=policy.Bot(data['hello'])
        bot.last_hurt=bot.last_weapon_hurt=data['initial_last_hurt']
        bot.damage_bearing=data['initial_damage_bearing']
        bot.recent_attackers[6]=data['initial_last_hurt']
        self.assertEqual(len(data['frames']),21)
        for frame in data['frames']:
            obs=copy.deepcopy(frame['obs'])
            with self.subTest(t=obs['t']):
                self.assertEqual(obs['mechs'],[])
                self.assertEqual(frame['recorded_action']['aim'][0],obs['self']['aim'][0])
                action=bot.act(obs)
                self.assertEqual(action['fire'],[False,False])
                self.assertTrue(bot.recover)
                self.assertAlmostEqual(action['aim'][0],frame['expected_bearing'])

    def test_zero_radian_bearing_is_preserved_with_no_visible_threat(self):
        self.hurt(0.)
        self.assertEqual(self.bot.act(self.obs)['aim'][0],0.)

    def test_occluded_threats_are_not_optimizer_inputs(self):
        self.hurt(-.7)
        actor=self.enemy()
        self.obs['mechs']=[actor]
        with patch.object(self.bot,'threats',return_value=[{'actor':actor,'d':100.,'los':False,'risk':1.}]):
            self.assertEqual(self.bot.act(self.obs)['aim'][0],-.7)

    def test_stale_or_missing_damage_bearing_keeps_old_reload_fallback(self):
        for age,bearing in ((3.,-.7),(4.,-.7),(.1,None)):
            with self.subTest(age=age,bearing=bearing):
                self.bot.last_hurt=self.obs['t']-age
                self.bot.damage_bearing=bearing
                action=self.bot.act(self.obs)
                self.assertEqual(action['aim'][0],self.obs['self']['aim'][0])

    def test_visible_optimizer_ignores_hidden_bearing_for_mech_and_npc(self):
        for kind,ident in (('mech',5),('npc',105)):
            with self.subTest(kind=kind):
                self.hurt(0.,who=6)
                actor=self.enemy(-40,kind=kind,id=ident)
                self.obs['mechs']=[actor]
                action=self.bot.act(self.obs)
                self.assertAlmostEqual(abs(action['aim'][0]),math.pi)

    def test_active_fire_keeps_defensive_optimizer_excluded(self):
        self.hurt(math.pi,who=5)
        self.obs['self']['weapons'][1]=self.weapon('lightning')
        self.obs['self']['aim']=[math.pi,0]
        self.obs['mechs']=[self.enemy(-20)]
        with patch.object(self.bot,'defensive_yaw',wraps=self.bot.defensive_yaw) as optimizer:
            action=self.bot.act(self.obs)
            self.assertTrue(action['fire'][1])
            optimizer.assert_not_called()

    def test_existing_laser_charge_keeps_defensive_optimizer_excluded(self):
        self.hurt(-.7)
        self.obs['self']['weapons'][1]=self.weapon('laser',charge=.2)
        with patch.object(self.bot,'defensive_yaw',wraps=self.bot.defensive_yaw) as optimizer:
            action=self.bot.act(self.obs)
            self.assertEqual(action['fire'],[False,False])
            self.assertEqual(action['aim'][0],-.7)
            optimizer.assert_not_called()

    def test_reload_boundary_keeps_defensive_optimizer_excluded(self):
        self.hurt(-.7)
        self.obs['self']['weapons'][0]['reload']=.3
        with patch.object(self.bot,'defensive_yaw',wraps=self.bot.defensive_yaw) as optimizer:
            self.assertEqual(self.bot.act(self.obs)['aim'][0],-.7)
            optimizer.assert_not_called()


if __name__=='__main__':unittest.main()
