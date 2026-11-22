"""Near-full laser timing regression independent of strategy changes."""
import math
import unittest
import test_combat as fixtures

combat, CONFIG = fixtures.combat, fixtures.CONFIG
observation, weapon, enemy = fixtures.observation, fixtures.weapon, fixtures.enemy


class LaserChargeToleranceTests(unittest.TestCase):
    def test_observed_rounded_full_laser_releases_when_aligned(self):
        for observed, full in ((.56, .563), (.42, .422), (.75, .75)):
            with self.subTest(observed=observed, full=full):
                obs = observation(weapon('laser', charge=observed))
                obs['self']['weapons'][0]['stats']['charge'] = full
                self.assertFalse(combat.Combat(CONFIG).plan(obs, enemy())['fire'][0])

    def test_near_full_laser_starts_bounded_hold_and_resets_new_cycle(self):
        controller = combat.Combat(CONFIG)
        obs = observation(weapon('laser', charge=.56))
        obs['self']['weapons'][0]['stats']['charge'] = .563
        obs['self']['aim'] = [math.pi, 0]
        self.assertTrue(controller.plan(obs, enemy())['fire'][0])
        obs['t'] += .4
        self.assertFalse(controller.plan(obs, enemy())['fire'][0])
        obs['self']['weapons'][0]['charge'] = 0
        controller.plan(obs, enemy())
        self.assertNotIn(0, controller._full_since)
        obs['t'] += .1
        obs['self']['weapons'][0]['charge'] = .56
        self.assertTrue(controller.plan(obs, enemy())['fire'][0])
        self.assertEqual(controller._full_since[0], obs['t'])

    def test_near_full_tolerance_does_not_release_undercharged_or_below_minimum(self):
        obs = observation(weapon('laser', charge=.55))
        obs['self']['weapons'][0]['stats']['charge'] = .563
        controller = combat.Combat(CONFIG)
        self.assertTrue(controller.plan(obs, enemy())['fire'][0])
        self.assertNotIn(0, controller._full_since)
        obs['self']['weapons'][0]['charge'] = .149
        obs['self']['weapons'][0]['stats']['charge'] = .15
        self.assertTrue(controller.plan(obs, enemy())['fire'][0])
        self.assertNotIn(0, controller._full_since)

