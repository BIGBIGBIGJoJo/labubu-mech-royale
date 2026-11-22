"""Opt-in emergency laser admission; preserves retreat and ordinary weapon rules."""
import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import test_strategy as fixtures
import test_combat as weapons
from combat import Combat
from arena_map import ArenaMap

ROOT = Path(__file__).resolve().parents[1]


def low_wall(a, b):
    if min(a[0], b[0]) <= 95 <= max(a[0], b[0]) and a[0] != b[0]:
        fraction = (95-a[0])/(b[0]-a[0])
        return a[2]+fraction*(b[2]-a[2]) > 7.9
    return True


class DefensiveWeaponTests(unittest.TestCase):
    def setUp(self):
        self.obs = weapons.observation(weapons.weapon('gun', ammo=0, reload=2), weapons.weapon('laser'))
        self.target = weapons.enemy()
        self.target.update(weapons=['gun'], hp=90)

    def plan(self, *, ray=lambda a,b: True, **kwargs):
        controller = Combat(weapons.CONFIG, ray)
        return controller, controller.plan(self.obs, self.target, emergency=True, defensive_finisher=True, **kwargs)

    def test_ready_bounded_target_can_start_while_default_emergency_cannot(self):
        original = Combat(weapons.CONFIG, lambda a,b: True).plan(self.obs, self.target, emergency=True)
        self.assertFalse(original['fire'][1])
        controller, action = self.plan()
        self.assertTrue(action['fire'][1])
        self.assertTrue(controller.defensive_laser_start)
        self.assertFalse(action['fire'][0])

    def test_finite_known_hp_and_max_legal_armor_bound_are_required(self):
        controller = Combat(weapons.CONFIG)
        stats = self.obs['self']['weapons'][1]['stats']
        bound = controller.laser_damage_bound(self.obs['self'], stats,
                    {**self.target, 'armor':controller.max_enemy_armor}, stats['min_charge'])
        for hp in (bound+.01, None, float('nan'), float('inf'), 0, -1):
            with self.subTest(hp=hp):
                self.target.update(hp=hp, armor=0)
                self.assertFalse(self.plan()[1]['fire'][1])
        self.target.pop('hp')
        self.assertFalse(self.plan()[1]['fire'][1])

    def test_npc_and_unready_laser_and_no_fire_permission_are_excluded(self):
        self.target['kind'] = 'npc'
        self.assertFalse(self.plan()[1]['fire'][1])
        self.target['kind'] = 'mech'
        self.obs['self']['weapons'][1]['cooldown'] = .01
        self.assertFalse(self.plan()[1]['fire'][1])
        self.obs['self']['weapons'][1]['cooldown'] = 0
        self.assertFalse(self.plan(allow_fire=False)[1]['fire'][1])

    def test_missing_geometry_range_pitch_and_actual_alignment_fail_closed(self):
        self.assertFalse(self.plan(ray=None)[1]['fire'][1])
        self.target['pos'][0] = 400
        self.assertFalse(self.plan()[1]['fire'][1])
        self.target['pos'] = [1,0,-100]
        self.assertFalse(self.plan()[1]['fire'][1])
        self.target['pos'] = [100,0,0]
        self.obs['self']['aim'] = [math.pi,0]
        self.assertFalse(self.plan()[1]['fire'][1])

    def test_planned_upper_body_clear_does_not_certify_actual_slewed_ray(self):
        self.obs['self']['aim'] = [0,-.2]
        controller, action = self.plan(ray=low_wall)
        self.assertGreater(action['aim'][1], 0)
        self.assertFalse(action['fire'][1])
        self.assertFalse(controller.defensive_laser_start)
        self.obs['self']['aim'] = action['aim']
        self.assertTrue(self.plan(ray=low_wall)[1]['fire'][1])

    def test_final_shared_gun_aim_must_also_intersect_laser_body(self):
        self.obs['self']['weapons'][0].update(ammo=12, reload=0)
        self.target.update(pos=[200,0,0], vel=[0,20,0])
        controller, action = self.plan()
        self.assertGreater(action['aim'][0], .05)
        self.assertFalse(action['fire'][1])

    def test_wall_inside_barrel_is_checked_and_wall_behind_hit_is_ignored(self):
        controller = Combat(weapons.CONFIG, lambda a,b: not (min(a[0],b[0])<1<max(a[0],b[0])))
        sol = {'point':[100,0,4.5], 'center_z':4.5}
        args = ([0,-.025],sol,[0,0,7],3,2.5,9,280)
        self.assertFalse(controller._defensive_laser_ray_clear(*args))
        controller.line_of_fire = lambda a,b: max(a[0],b[0]) < 101
        self.assertTrue(controller._defensive_laser_ray_clear(*args))

    def test_positive_charge_releases_and_clears_new_start_telemetry(self):
        controller, action = self.plan()
        self.assertTrue(action['fire'][1])
        self.obs['self']['weapons'][1]['charge'] = .1
        action = controller.plan(self.obs,self.target,emergency=True,defensive_finisher=True)
        self.assertFalse(action['fire'][1])
        self.assertFalse(controller.defensive_laser_start)


class DefensiveIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.StrategyTests.setUpClass.__func__)
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    def setUp(self):
        fixtures.StrategyTests.setUp(self)
        self.obs['self']['hp'] = 500
        self.obs['self']['weapons'] = [self.weapon('gun',ammo=0,reload=2),self.weapon('laser')]
        self.obs['mechs'] = [self.enemy(100,hp=90)]
        self.bot.last_weapon_hurt = self.obs['t']

    def test_start_preserves_run_goal_latch_and_uses_charging_motion(self):
        with patch.object(self.bot,'movement',return_value=((-1,0),False)) as movement:
            action = self.bot.act(self.obs)
        self.assertTrue(action['fire'][1])
        self.assertTrue(self.bot.recover)
        self.assertTrue(self.bot.duel.health_recover)
        self.assertEqual(self.bot.mode,'recover')
        self.assertEqual(action['move'],[-1,0])
        self.assertGreater(movement.call_args.args[0]['self']['weapons'][1]['charge'],0)
        self.obs.update(t=20.1,tick=402,events=[])
        self.obs['self']['weapons'][1]['charge'] = .1
        with patch.object(self.bot,'movement',return_value=((-1,0),False)) as movement:
            released = self.bot.act(self.obs)
        self.assertFalse(released['fire'][1])
        self.assertEqual(movement.call_args.args[0]['self']['weapons'][1]['charge'],.1)
        self.assertTrue(self.bot.recover)

    def test_outside_zone_multiple_opponents_quiet_and_mismatched_id_deny(self):
        for case in ('outside','multiple','quiet','mismatch','no_permission'):
            with self.subTest(case=case):
                self.setUp()
                if case=='outside':self.obs['self']['in_zone']=False
                if case=='multiple':self.obs['mechs'].append(self.enemy(100,20,id=6))
                if case=='no_permission':self.bot.last_weapon_hurt=-100
                if case=='quiet':
                    self.bot.duel.quiet_healing=lambda *args:True
                if case=='mismatch':
                    self.bot.duel.decide=lambda *args,**kwargs:dict(retreat=True,phase='retreat',opponents=[6],reason='test')
                self.assertFalse(self.bot.act(self.obs)['fire'][1])

    def test_predictive_rotation_does_not_veto_current_inside_zone(self):
        self.obs['zone'].update(radius=500,next_radius=1,shrink_start=10,shrink_end=21)
        action=self.bot.act(self.obs)
        self.assertEqual(self.bot.mode,'rotate')
        self.assertTrue(self.bot.recover)
        self.assertTrue(action['fire'][1])


class CapturedDefensiveFinishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((ROOT/'tests/data/defensive-finish-terminal.json').read_text())
        cls.arena=ArenaMap(str(ROOT/'arena'),cls.data['config'])
        assert cls.arena.available, cls.arena.error

    def test_actual_terminal_states_have_two_inside_positives_and_outside_negative(self):
        for frame in self.data['frames']:
            obs=copy.deepcopy(frame['obs'])
            with self.subTest(t=obs['t']),patch.object(fixtures.policy,'ArenaMap',return_value=self.arena):
                bot=fixtures.policy.Bot(copy.deepcopy(self.data['hello']))
                bot.last_weapon_hurt=frame['previous_last_weapon_hurt']
                bot.last_combat=frame['previous_last_combat']
                bot.recent_attackers={int(k):v for k,v in frame['previous_recent_attackers'].items()}
                with patch.object(bot,'movement',return_value=((-1,0),False)):
                    action=bot.act(obs)
                expected=obs['t'] in (182.,184.)
                self.assertEqual(action['fire'][1],expected)
                self.assertEqual(bot.combat.defensive_laser_start,expected)
                self.assertEqual(bot.mode,'rotate')
                self.assertTrue(bot.recover)
                self.assertEqual(action['move'],[-1,0])
                self.assertFalse(frame['recorded_action']['fire'][1])


if __name__=='__main__':unittest.main()
