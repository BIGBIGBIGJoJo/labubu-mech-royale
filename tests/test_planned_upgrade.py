"""Upgrade eligibility follows retained held weapons; ranks remain unchanged."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot import Bot
from arena_map import ArenaMap

FIXTURE=json.loads((ROOT/'tests/fixtures/planned-weapon-upgrade.json').read_text(encoding='utf-8'))


class PlannedUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arena=ArenaMap(str(ROOT/'arena'),FIXTURE['config'])
        assert cls.arena.available and len(cls.arena.prisms)==259

    def setUp(self):
        self.obs=copy.deepcopy(FIXTURE['obs'])
        with patch('bot.ArenaMap',return_value=self.arena):
            self.bot=Bot({'config':copy.deepcopy(FIXTURE['config']),
                          'slot':FIXTURE['slot'],'map':{'dir':str(ROOT/'arena')}})

    def offer(self,*ids):
        self.obs['offer']['choices']=[{'id':key} for key in ids]

    def test_captured_simultaneous_swap_chooses_general_upgrade(self):
        self.assertEqual(FIXTURE['recorded_action']['pick'],0)
        planned=self.bot.take_weapon(self.obs)
        self.assertEqual(planned,{'take':8040,'drop':1})
        self.assertEqual(self.bot.choose_upgrade(self.obs),0)
        self.assertEqual(self.bot.choose_upgrade(self.obs,planned),1)  # jets

    def test_captured_bot_action_keeps_swap_but_cannot_upgrade_removed_lightning(self):
        before=copy.deepcopy(self.obs)
        action=self.bot.act(self.obs)
        self.assertEqual({k:action[k] for k in ('pick','take','drop')},
                         {'pick':1,'take':8040,'drop':1})
        self.assertEqual(self.obs,before)

    def test_gun_upgrade_remains_supported_when_other_weapon_is_replaced(self):
        self.offer('lightning_efficiency','gun_mag','gyros')
        self.assertEqual(self.bot.choose_upgrade(self.obs,self.bot.take_weapon(self.obs)),1)

    def test_retained_second_slot_weapon_is_not_globally_disabled(self):
        lightning=self.obs['self']['weapons'][1]
        mortar={'kind':'mortar','cooldown':0,'stats':copy.deepcopy(FIXTURE['config']['weapons']['mortar'])}
        self.obs['self']['weapons']=[lightning,mortar]
        self.offer('lightning_efficiency','mortar_splash','gyros')
        self.assertEqual(self.bot.choose_upgrade(self.obs,{'take':8040,'drop':0}),1)

    def test_incoming_unheld_weapon_is_not_eligible_before_acknowledgement(self):
        self.offer('laser_damage','gun_mag','gyros')
        self.assertEqual(self.bot.choose_upgrade(self.obs,self.bot.take_weapon(self.obs)),1)
        self.obs['self']['weapons'][1]={'kind':'laser','charge':0,'cooldown':1.65,
            'stats':copy.deepcopy(FIXTURE['config']['weapons']['laser'])}
        self.assertEqual(self.bot.choose_upgrade(self.obs),0)

    def test_failed_take_next_observation_keeps_old_weapon_eligible(self):
        planned=self.bot.take_weapon(self.obs)
        self.assertEqual(self.bot.choose_upgrade(self.obs,planned),1)
        self.obs['tick']+=2
        self.obs['t']+=.1
        self.obs['events']=[{'type':'take_failed','id':8040,'reason':'gone'}]
        self.obs['pickups']=[]
        self.assertEqual(self.bot.take_weapon(self.obs),{})
        self.assertEqual(self.bot.choose_upgrade(self.obs,{}),0)

    def test_all_removed_weapon_choices_defer_until_observed_state_supports_one(self):
        self.offer('lightning_efficiency','lightning_range','lightning_chain')
        self.assertIsNone(self.bot.choose_upgrade(self.obs,self.bot.take_weapon(self.obs)))
        self.obs['self']['weapons'][1]={'kind':'laser','charge':0,'cooldown':0,
            'stats':copy.deepcopy(FIXTURE['config']['weapons']['laser'])}
        self.obs['pickups']=[]
        self.assertIsNone(self.bot.choose_upgrade(self.obs,{}))
        # A later acknowledged return of lightning supports the persistent offer.
        self.obs['self']['weapons'][1]={'kind':'lightning','cooldown':0,
            'stats':copy.deepcopy(FIXTURE['config']['weapons']['lightning'])}
        self.assertEqual(self.bot.choose_upgrade(self.obs,{}),1)

    def test_absent_offer_never_invents_pick(self):
        self.obs['offer']=None
        self.assertIsNone(self.bot.choose_upgrade(self.obs,{'take':8040,'drop':1}))

    def test_empty_slot_pickup_does_not_exclude_current_gun(self):
        self.obs['self']['weapons'][1]=None
        self.offer('gun_mag','laser_damage','gyros')
        self.assertEqual(self.bot.choose_upgrade(self.obs,{'take':8040}),0)

    def test_existing_rank_adjustments_and_tie_order_remain(self):
        self.offer('gun_mag','armor','nanites')
        self.assertEqual(self.bot.choose_upgrade(self.obs,{}),2)
        self.obs['self']['hp']=400
        self.offer('plating','nanites','armor')
        self.assertEqual(self.bot.choose_upgrade(self.obs,{}),0)
        self.obs['self']['hp']=self.obs['self']['max_hp']
        self.obs['zone']['next_radius']=20
        self.assertEqual(self.bot.choose_upgrade(self.obs,{}),0)

    def test_requirements_come_from_config_instead_of_id_prefix(self):
        self.bot.config['upgrades'].append({'id':'test_retained','requires':'gun'})
        self.bot.config['upgrades'].append({'id':'test_removed','requires':'lightning'})
        self.offer('test_removed','test_retained')
        self.assertEqual(self.bot.choose_upgrade(self.obs,{'take':8040,'drop':1}),1)


if __name__=='__main__': unittest.main()
