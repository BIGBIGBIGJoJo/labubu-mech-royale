"""Recorded launch geometry plus explicitly conditional moving-pose checks."""
import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from arena_map import ArenaMap
from combat import Combat, angle_delta, direction, point_aim
import test_combat as base

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT/'tests/fixtures/horizontal-barrel.json').read_text())


def ray_to_body(arena, muzzle, aim, solution, radius, height, offset, bullet=0.):
    """Test-only near-body central ray; it is not a production firing gate."""
    origin = Combat._barrel_origin(muzzle, aim, offset)
    vec = direction(aim)
    dx, dy = origin[0]-solution['point'][0], origin[1]-solution['point'][1]
    aa = vec[0]**2+vec[1]**2
    bb = 2*(dx*vec[0]+dy*vec[1])
    cc = dx*dx+dy*dy-(radius+bullet)**2
    disc = bb*bb-4*aa*cc
    if aa < 1e-12 or disc < 0:
        return False
    enter, leave = max(0., (-bb-math.sqrt(disc))/(2*aa)), (-bb+math.sqrt(disc))/(2*aa)
    low, high = solution['center_z']-height*.5-bullet, solution['center_z']+height*.5+bullet
    if abs(vec[2]) < 1e-12:
        if not low <= origin[2] <= high:
            return False
    else:
        z_enter, z_leave = sorted(((low-origin[2])/vec[2], (high-origin[2])/vec[2]))
        enter, leave = max(enter, z_enter), min(leave, z_leave)
    if enter > leave or leave < 0:
        return False
    end = [origin[i]+enter*vec[i] for i in range(3)]
    return arena.line_of_fire(muzzle, origin) and arena.line_of_fire(origin, end)


class HorizontalBarrelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arena = ArenaMap(ROOT/'arena', DATA['gun_moving']['config'])
        assert cls.arena.available and len(cls.arena.prisms) == 259

    def load(self, name, kind):
        case = copy.deepcopy(DATA[name])
        obs, target = case['obs'], case['target']
        controller = Combat(case['config'], self.arena.line_of_fire)
        me = obs['self']; own = controller._self_stats(me)
        slot, weapon = next((i, w) for i, w in enumerate(me['weapons']) if w and w['kind'] == kind)
        radius, height = controller._body(target)
        ready = max(weapon.get('cooldown', 0), weapon.get('reload', 0) if kind == 'gun' else 0)
        delay = controller.sim_dt if kind == 'laser' else min(controller.action_dt,
            max(controller.sim_dt, math.ceil((ready-1e-8)/controller.sim_dt)*controller.sim_dt))
        center = [target['pos'][i]+target['vel'][i]*delay for i in range(3)]; center[2] += height*.5
        muzzle = [*me['pos'][:2], me['pos'][2]+own['muzzle_height']]
        solution = controller._direct_solution(kind, controller._stats(weapon), muzzle, center,
            target['vel'], own['radius']+.5, (own['min_pitch'], own['max_pitch']), height)
        self.assertIsNotNone(solution)
        action = controller.plan(obs, target)
        aim = controller._slewed(me['aim'], action['aim'], own, delay)
        bullet = case['config']['projectile']['gun_radius'] if kind == 'gun' else 0.
        return case, controller, action, solution, aim, (radius, height, own['radius']+.5, bullet)

    def test_barrel_extension_includes_cos_pitch_but_never_changes_height(self):
        origin = Combat._barrel_origin([2., 3., 7.], [math.pi/3, .6], 3.)
        self.assertAlmostEqual(origin[0], 2+3*math.cos(.6)*math.cos(math.pi/3))
        self.assertAlmostEqual(origin[1], 3+3*math.cos(.6)*math.sin(math.pi/3))
        self.assertEqual(origin[2], 7.)

    def test_bounded_solver_returns_forward_ray_through_its_chosen_point(self):
        for point in ([100., 30., 45.], [6.5, 0., 4.5], [100., 0., -30.]):
            with self.subTest(point=point):
                muzzle = [0., 0., 7.]
                aim = Combat._barrel_aim(muzzle, point, 3.)
                self.assertIsNotNone(aim)
                launch = Combat._barrel_origin(muzzle, aim, 3.)
                measured = point_aim(launch, point)
                self.assertLess(abs(angle_delta(measured[0], aim[0])), 1e-6)
                self.assertLess(abs(measured[1]-aim[1]), 1e-6)
                self.assertGreater(sum((point[i]-launch[i])*direction(aim)[i] for i in range(3)), 0)

    def test_nonfinite_behind_origin_overlap_and_unresolved_roots_rejected(self):
        for point in ([1., 0., 7.], [3., 0., 7.], [0., 0., 7.], [math.nan, 0., 7.], [0., 0., math.inf]):
            with self.subTest(point=point):
                self.assertIsNone(Combat._barrel_aim([0., 0., 7.], point, 3.))
        controller = Combat(base.CONFIG)
        for velocity in ([math.inf, 0, 0], [0, math.nan, 0]):
            self.assertIsNone(controller._direct_solution('gun', base.CONFIG['weapons']['gun'],
                [0, 0, 7], [100, 0, 4.5], velocity, 3., (-.7, 1.3), 9.))
        with patch.object(Combat, '_barrel_origin', return_value=[0., 0., 100.]):
            self.assertIsNone(Combat._barrel_aim([0., 0., 7.], [100., 0., 4.5], 3.))

    def test_barrel_prefix_blocks_shot_and_wall_behind_target_does_not(self):
        args = ('laser', base.CONFIG['weapons']['laser'], [0, 0, 7], [100, 0, 4.5], [0, 0, 0], 3., (-.7, 1.3), 9.)
        blocked = Combat(base.CONFIG, lambda a, b: not(min(a[0], b[0]) <= 1 <= max(a[0], b[0])))
        self.assertFalse(blocked._direct_solution(*args)['clear'])
        behind = Combat(base.CONFIG, lambda a, b: max(a[0], b[0]) < 101)
        self.assertTrue(behind._direct_solution(*args)['clear'])

    def test_range_is_from_actual_barrel_and_pitch_limits_still_reject(self):
        controller = Combat(base.CONFIG)
        stats = {**base.CONFIG['weapons']['laser'], 'range': 10.}
        args = (stats, [0, 0, 7], [12.5, 0, 7], [0, 0, 0], 3., (-.7, 1.3), 9.)
        solution = controller._direct_solution('laser', *args)
        self.assertAlmostEqual(solution['distance'], 9.5)
        self.assertIsNone(controller._direct_solution('laser', stats, [0, 0, 7], [13.1, 0, 7],
                                                      [0, 0, 0], 3., (-.7, 1.3), 9.))
        self.assertIsNone(controller._direct_solution('laser', {**stats, 'range': 280},
            [0, 0, 7], [10, 0, 100], [0, 0, 0], 3., (-.1, .1), 9.))

    def test_1124_corrects_current_ray_but_does_not_claim_moving_pose_success(self):
        case, controller, action, solution, aim, body = self.load('gun_moving', 'gun')
        self.assertTrue(action['fire'][0])
        self.assertAlmostEqual(solution['aim'][1], .04252233175557599, places=8)
        self.assertAlmostEqual(solution['point'][2], 8.7)
        for pose in case['poses']:
            clear = ray_to_body(self.arena, pose['muzzle'], aim, solution, *body)
            self.assertEqual(clear, pose['seconds'] == 0, pose)

    def test_806_lower_laser_ray_survives_both_conditional_movement_orders(self):
        case, controller, action, solution, aim, body = self.load('laser_bridge', 'laser')
        self.assertTrue(solution['clear'])
        self.assertAlmostEqual(solution['point'][2], 12.405)
        self.assertAlmostEqual(solution['center_z'], 15.915)
        self.assertAlmostEqual(solution['aim'][1], .14646678791560827, places=8)
        self.assertLess(solution['point'][2], solution['center_z'])
        self.assertEqual(action['fire'][1], case['baseline_action']['fire'][1])  # Both release.
        self.assertTrue(case['baseline_action']['fire'][0])
        self.assertFalse(action['fire'][0])  # Explicit shared-aim offense tradeoff.
        self.assertEqual(len(case['poses']), 5)
        for pose in case['poses']:
            self.assertTrue(ray_to_body(self.arena, pose['muzzle'], aim, solution, *body), pose)

    def test_1274_transient_slew_limitation_is_preserved_without_new_fire_gate(self):
        case, controller, action, solution, aim, body = self.load('gun_slew', 'gun')
        own = controller._self_stats(case['obs']['self'])
        muzzle = [*case['obs']['self']['pos'][:2], case['obs']['self']['pos'][2]+own['muzzle_height']]
        self.assertTrue(action['fire'][0])
        self.assertTrue(controller._aligned(aim, solution, body[0], body[1], body[3]))
        self.assertFalse(ray_to_body(self.arena, muzzle, aim, solution, *body))
        self.assertTrue(ray_to_body(self.arena, muzzle, solution['aim'], solution, *body))

    def test_lightning_and_mortar_never_enter_horizontal_solver(self):
        controller = Combat(base.CONFIG, lambda a,b: True)
        with patch.object(controller, '_horizontal_solution', side_effect=AssertionError('out of scope')):
            lightning = controller.plan(base.observation(base.weapon('lightning')), base.enemy(30))
            self.assertTrue(lightning['fire'][0])
            mortar = controller.plan(base.observation(base.weapon('mortar')), base.enemy(50))
            self.assertEqual(len(mortar['fire']), 2)

    def test_lightning_mortar_full_actions_match_frozen_base_across_permissions(self):
        for case in DATA['legacy_actions']:
            with self.subTest(case=case):
                action = Combat(base.CONFIG, lambda a,b: True).plan(
                    case['obs'], case['target'], allow_fire=case['allow_fire'], emergency=case['emergency'])
                self.assertEqual(set(action), set(case['action']))
                self.assertEqual(action['fire'], case['action']['fire'])
                self.assertEqual(action['reload'], case['action']['reload'])
                for actual, expected in zip(action['aim'], case['action']['aim']):
                    self.assertAlmostEqual(actual, expected, places=12)


if __name__ == '__main__':
    unittest.main()
