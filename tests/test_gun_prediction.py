"""Gun-only prediction integration and flight/body geometry consistency."""
import copy
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from combat import Combat
from target_motion import TargetMotion
from test_combat import CONFIG,observation,weapon,enemy


class Ground:
    available=True
    def support_height(self,x,y,previous_z):
        return 0.0


class GunPredictionTests(unittest.TestCase):
    def controller(self,target,clear=None):
        motion=TargetMotion(CONFIG,Ground())
        previous=copy.deepcopy(target)
        previous['vel'][2]+=CONFIG['mech']['gravity']*.1
        for axis in range(3):
            previous['pos'][axis]-=target['vel'][axis]*.1
        previous['pos'][2]-=.5*CONFIG['mech']['gravity']*.1**2
        motion.update({'tick':98,'mechs':[previous]})
        motion.update({'tick':100,'mechs':[target]})
        controller=Combat(CONFIG,clear,motion.forecast)
        captured={}
        original=controller._direct_solution
        def capture(*args,**kwargs):
            solution=original(*args,**kwargs)
            captured[args[0]]=solution
            return solution
        controller._direct_solution=capture
        return controller,motion,captured

    def test_flight_delay_and_body_center_share_one_forecast_horizon(self):
        target=enemy(100,20,[0,3,-12])
        target['pos'][2]=40
        target['cubes']=4
        controller,motion,captured=self.controller(target)
        controller.plan(observation(weapon('gun',cooldown=.09)),target)
        solution=captured['gun']
        self.assertIsNotNone(solution)
        feet=motion.forecast(target,.1+solution['flight'])
        self.assertAlmostEqual(solution['center_z'],feet[2]+5.4)
        self.assertAlmostEqual(solution['point'][2],feet[2]+5.4)
        self.assertEqual(solution['point'][:2],feet[:2])
        self.assertAlmostEqual(solution['flight'],solution['distance']/CONFIG['weapons']['gun']['speed'],delta=.0001)

    def test_later_launch_uses_additional_vertical_gravity_once(self):
        target=enemy(100,0,[0,0,-12])
        target['pos'][2]=40
        controller,motion,captured=self.controller(target)
        controller.plan(observation(weapon('gun')),target)
        immediate=captured['gun']['center_z']
        controller.plan(observation(weapon('gun',cooldown=.09)),target)
        delayed=captured['gun']['center_z']
        self.assertLess(delayed,immediate-.7)

    def test_pitch_clipping_preserves_predicted_center_for_alignment(self):
        target=enemy(6.5)
        controller,motion,captured=self.controller(target)
        obs=observation(weapon('gun'))
        obs['self']['cubes']=10
        obs['self']['stats'].update(radius=2.5,height=9,muzzle_height=10.5)
        obs['self']['aim']=[0,-.7]
        action=controller.plan(obs,target)
        solution=captured['gun']
        self.assertTrue(action['fire'][0])
        self.assertAlmostEqual(solution['center_z'],4.5)
        self.assertGreater(solution['point'][2],solution['center_z'])
        self.assertGreaterEqual(solution['aim'][1],-.7)

    def test_upper_body_alternate_uses_predicted_vertical_center(self):
        target=enemy(100,0,[0,0,-10])
        target['pos'][2]=30
        rays=[]
        def clear(start,end):
            rays.append((list(start),list(end)))
            return end[2]>=30
        controller,motion,captured=self.controller(target,clear)
        controller.plan(observation(weapon('gun')),target)
        solution=captured['gun']
        self.assertTrue(solution['clear'])
        self.assertAlmostEqual(solution['center_z'],motion.forecast(target,.05+solution['flight'])[2]+4.5)
        self.assertAlmostEqual(solution['point'][2],solution['center_z']+9*.39)
        # Preserve baseline barrel/ray construction; prediction changes target
        # motion, not the separate question of authoritative weapon origin.
        self.assertTrue(all(start==[0,0,7] for start,end in rays))
        self.assertAlmostEqual(math.dist([0,0,7],solution['origin']),3.0)

    def test_non_gun_and_nonmech_solutions_do_not_call_predictor(self):
        def forbidden(*args):
            self.fail('Predictor must only be called for mech gun solutions')
        for kind in ('laser','lightning','mortar'):
            with self.subTest(kind=kind):
                obs=observation(weapon(kind))
                target=enemy(40,0,[0,0,-1])
                expected=Combat(CONFIG).plan(copy.deepcopy(obs),copy.deepcopy(target))
                self.assertEqual(Combat(CONFIG,target_predictor=forbidden).plan(obs,target),expected)
        target=enemy(40)
        target['kind']='npc'
        self.assertEqual(Combat(CONFIG,target_predictor=forbidden).plan(observation(weapon('gun')),target),
                         Combat(CONFIG).plan(observation(weapon('gun')),target))

    def test_predictor_work_is_bounded_per_gun_solution(self):
        calls=[]
        def forecast(target,seconds):
            calls.append(seconds)
            return [target['pos'][i]+target['vel'][i]*seconds for i in range(3)]
        Combat(CONFIG,target_predictor=forecast).plan(observation(weapon('gun')),enemy(100))
        self.assertGreater(len(calls),0)
        self.assertLessEqual(len(calls),8)


if __name__=='__main__':
    unittest.main()
