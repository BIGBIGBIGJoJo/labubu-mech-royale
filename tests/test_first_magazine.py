"""An isolated first-drum choice change on the accepted baseline controller."""
import copy
import unittest

import test_strategy as fixtures


class FirstMagazineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    setUp = fixtures.StrategyTests.setUp
    weapon = fixtures.StrategyTests.weapon

    def offer(self, *choices):
        self.obs['offer'] = {'id': 1, 'expires': self.obs['t'] + 5,
                             'choices': [{'id': kind} for kind in choices]}

    def selected(self):
        index = self.bot.choose_upgrade(self.obs)
        return self.obs['offer']['choices'][index]['id']

    def test_first_drum_wins_recorded_armor_offer(self):
        self.offer('jets', 'gun_mag', 'armor')
        self.assertEqual(self.selected(), 'gun_mag')

    def test_first_drum_wins_recorded_servos_offer(self):
        self.offer('armor', 'gun_mag', 'servos')
        self.assertEqual(self.selected(), 'gun_mag')

    def test_nanites_retain_priority_over_first_drum(self):
        self.offer('nanites', 'gun_mag', 'armor')
        self.assertEqual(self.selected(), 'nanites')

    def test_existing_low_health_plating_priority_is_preserved(self):
        self.obs['self']['hp'] = 500
        self.offer('gun_mag', 'plating', 'servos')
        self.assertEqual(self.selected(), 'plating')

    def test_second_drum_uses_observed_capacity_even_without_upgrade_history(self):
        self.obs['self']['weapons'][0]['stats']['mag'] = 20
        self.offer('gun_mag', 'armor', 'gun_damage')
        self.assertEqual(self.selected(), 'armor')

    def test_upgrade_history_prevents_reclassifying_a_second_drum(self):
        self.obs['self']['upgrades'] = ['gun_mag']
        self.offer('gun_mag', 'servos', 'gun_damage')
        self.assertEqual(self.selected(), 'servos')

    def test_second_drum_keeps_its_existing_rank_above_gun_damage(self):
        self.obs['self']['weapons'][0]['stats']['mag'] = 20
        self.obs['self']['upgrades'] = ['gun_mag']
        self.offer('gun_damage', 'gun_rate', 'gun_mag')
        self.assertEqual(self.selected(), 'gun_mag')

    def test_first_drum_detection_uses_configured_base_not_twelve(self):
        self.bot.config['weapons']['gun']['mag'] = 20
        self.obs['self']['weapons'][0]['stats']['mag'] = 20
        self.offer('armor', 'gun_mag', 'servos')
        self.assertEqual(self.selected(), 'gun_mag')
        self.obs['self']['weapons'][0]['stats']['mag'] = 28
        self.assertEqual(self.selected(), 'servos')

    def test_stale_weapon_offer_without_held_gun_does_not_receive_boost(self):
        self.obs['self']['weapons'] = [self.weapon('laser'), None]
        self.offer('gun_mag', 'armor', 'servos')
        self.assertEqual(self.selected(), 'servos')

    def test_actual_bot_emits_valid_pick_without_mutating_observation(self):
        self.offer('jets', 'gun_mag', 'armor')
        before = copy.deepcopy(self.obs)
        action = self.bot.act(self.obs)
        self.assertEqual(action['pick'], 1)
        self.assertEqual(self.obs, before)


if __name__ == '__main__':
    unittest.main()
