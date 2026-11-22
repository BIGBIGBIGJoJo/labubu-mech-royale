"""Damage-evidence lifecycle and real terrain route regressions.

Fixed clocks in policy fixtures remove host timing noise; Linux chronology owns
the real 32-ms budget test. These observations do not simulate changed futures.
"""
import copy
import json
import math
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bot as policy
import test_strategy as fixtures


class ReactiveRecoveryTests(unittest.TestCase):
    weapon = fixtures.StrategyTests.weapon
    enemy = fixtures.StrategyTests.enemy

    @classmethod
    def setUpClass(cls):
        cls.hello, cls.recorded = fixtures.official_fixture()

    def setUp(self):
        fixtures.StrategyTests.setUp(self)
        self.bot.map.step_up = 1.2
        self.bot.map.CONTACT_EPS = .001
        self.bot.map.prisms = []
        self.bot.map._candidates = lambda *args: ()
        self.obs['self']['hp'] = 500
        self.bot.recover = True
        self.bot.mode = self.bot.goal_kind = 'recover'
        self.bot.goal = [0, 0, 0]
        self.bot.goal_until = self.obs['t'] + 1
        self.bot.last_move = (0, 0)
        self.rx = self.bot.reactive_recovery

    def hit(self, **values):
        return {'type': 'damaged', 'amount': 45., 'weapon': 'gun', 'bearing': 0., 'by': 14, **values}

    def act(self):
        with patch('time.perf_counter', return_value=100.):
            return self.bot.act(self.obs)

    def advance(self, events=()):
        self.obs['t'] += .1
        self.obs['tick'] += 2
        self.obs['events'] = list(events)

    def start(self):
        self.obs['events'] = [self.hit()]
        action = self.act()
        self.assertEqual(self.rx.last_report['reason'], 'admitted')
        return action

    def select(self, deadline=math.inf):
        stats = self.bot.stats(self.obs['self'])
        center, radius = self.bot.zone_future(self.obs, 22)
        return self.rx.select(self.obs, stats, self.bot.recent_attackers, True,
                              self.bot.goal, self.bot.last_move, center, radius,
                              self.bot.tactical.horizon, lambda point: 0., deadline)

    def test_weapon_hit_replaces_reached_goal_with_route_and_one_combat_call(self):
        with patch.object(self.bot.combat, 'plan', wraps=self.bot.combat.plan) as combat:
            action = self.start()
        self.assertEqual(combat.call_count, 1)
        self.assertLess(action['move'][0], -.5)
        self.assertEqual(action['fire'], [False, False])
        self.assertEqual(action['aim'][0], 0.)
        self.assertGreater(math.dist(self.bot.goal[:2], [0, 0]), 1.5)
        self.assertLessEqual(self.bot.goal[0], 0.)
        self.assertEqual(self.rx.active['event'], (400, 0))

    def test_quiet_sound_and_zone_damage_do_not_interrupt_healing(self):
        for events in ([], [self.hit(weapon='zone')], [self.hit(amount=0)],
                       [self.hit(bearing=None)], [self.hit(weapon=None)]):
            with self.subTest(events=events):
                self.setUp()
                self.obs['events'] = events
                self.obs['sounds'] = [{'kind': 'gun', 'bearing': 1.}]
                action = self.act()
                self.assertIsNone(self.rx.active)
                self.assertEqual(action['move'], [0, 0])

    def test_bearingless_hit_cancels_owned_goal_and_refreshes_same_frame(self):
        self.start()
        rejected = list(self.bot.goal)
        self.advance([self.hit(bearing=None)])
        with patch.object(self.bot, 'safe_goal', return_value=[0, 20, 0]) as safe:
            self.act()
        self.assertEqual(safe.call_count, 1)
        self.assertIsNone(self.rx.active)
        self.assertNotEqual(self.bot.goal, rejected)
        self.assertEqual(self.bot.goal, [0, 20, 0])

    def test_second_recent_attacker_cancels_owned_goal(self):
        self.start()
        self.advance([self.hit(by=15, bearing=1.)])
        with patch.object(self.bot, 'safe_goal', return_value=[0, 20, 0]) as safe:
            self.act()
        self.assertEqual(safe.call_count, 1)
        self.assertIsNone(self.rx.active)
        self.assertEqual(self.rx.last_report['reason'], 'not_single_recent_attacker')

    def test_same_attacker_new_bearing_toward_goal_expires_owned_goal(self):
        self.start()
        rejected = list(self.bot.goal)
        self.advance([self.hit(bearing=math.pi)])
        with patch.object(self.bot, 'safe_goal', return_value=[0, 20, 0]) as safe:
            self.act()
        self.assertEqual(safe.call_count, 1)
        self.assertIsNone(self.rx.active)
        self.assertNotEqual(self.bot.goal, rejected)
        self.assertEqual(self.bot.goal, [0, 20, 0])

    def test_unknown_attacker_is_not_erased_by_next_known_hit(self):
        self.obs['events'] = [self.hit(by=None)]
        self.act()
        self.advance([self.hit()])
        self.act()
        self.assertIsNone(self.rx.active)
        self.assertEqual(self.rx.last_report['reason'], 'unknown_recent_damager')
        self.obs['t'] += 3.1
        self.obs['tick'] += 62
        self.obs['events'] = [self.hit()]
        self.bot.last_move = (0, 0)
        self.act()
        self.assertIsNotNone(self.rx.active)

    def test_later_zone_damage_does_not_refresh_weapon_bearing_timestamp(self):
        self.obs['events'] = [self.hit()]
        self.bot.update(self.obs)
        original = copy.deepcopy(self.rx.evidence)
        self.advance([self.hit(weapon='zone', bearing=2.)])
        self.bot.update(self.obs)
        self.assertEqual(self.rx.evidence, original)
        self.obs['t'] += 3.
        attempted, goal = self.select()
        self.assertFalse(attempted)
        self.assertIsNone(goal)

    def test_one_relocation_per_hit_and_new_hit_rearms_after_arrival(self):
        self.start()
        first = list(self.bot.goal)
        self.obs['self']['pos'] = list(first)
        self.bot.last_move = (0, 0)
        self.advance()
        self.act()
        self.assertIsNone(self.rx.active)
        self.assertEqual(self.bot.goal, first)
        self.assertEqual(self.rx.last_report['reason'], 'hit_already_used')
        self.advance([self.hit()])
        self.act()
        self.assertEqual(self.rx.last_report['reason'], 'admitted')
        self.assertNotEqual(self.bot.goal, first)

    def test_active_goal_is_retained_without_regenerating_candidates(self):
        self.start()
        first, consumed = list(self.bot.goal), self.rx.consumed
        self.advance()
        with patch.object(self.rx, 'select', wraps=self.rx.select) as select:
            self.act()
        self.assertEqual(select.call_count, 1)
        self.assertEqual(self.rx.last_report['reason'], 'retained')
        self.assertEqual(self.bot.goal, first)
        self.assertEqual(self.rx.consumed, consumed)

    def test_incomplete_budget_can_retry_same_hit_without_consuming_it(self):
        self.obs['events'] = [self.hit()]
        self.bot.update(self.obs)
        self.assertEqual(self.select(deadline=0.), (True, None))
        self.assertIsNone(self.rx.consumed)
        attempted, goal = self.select()
        self.assertTrue(attempted)
        self.assertIsNotNone(goal)

    def test_failed_proof_preserves_expired_or_zone_required_ordinary_refresh(self):
        for expired in (True, False):
            with self.subTest(expired=expired):
                self.setUp()
                self.obs['events'] = [self.hit()]
                if expired:
                    self.bot.goal_until = 0.
                else:
                    self.bot.goal = [1., 0., 0.]
                # The synthetic tiny future circle forces the existing zone
                # refresh independently of TTL; urgency is held false to isolate it.
                future = lambda obs, seconds: ([0, 0], .5 if seconds == 12 else 560.)
                contexts = [patch.object(self.rx, '_prove', return_value=None),
                            patch.object(self.bot, 'safe_goal', return_value=[0, 20, 0]),
                            patch.object(self.bot.zone_resources, 'rotation_required', return_value=False)]
                with contexts[0], contexts[1] as safe, contexts[2]:
                    if expired:
                        self.act()
                    else:
                        with patch.object(self.bot, 'zone_future', side_effect=future):
                            self.act()
                self.assertEqual(safe.call_count, 1)
                self.assertEqual(self.bot.goal, [0, 20, 0])
                self.assertIsNone(self.rx.consumed)

    def test_growth_scan_bound_rejects_before_growth(self):
        self.obs['events'] = [self.hit()]
        self.obs['cubes'] = [{'id': i, 'pos': [100, 100, 0]} for i in range(257)]
        self.bot.update(self.obs)
        with patch.object(self.bot.zone_resources, '_growth', side_effect=AssertionError('unbounded')):
            self.assertEqual(self.select(), (False, None))
        self.assertEqual(self.rx.last_report['reason'], 'growth_scan_limit')

    def test_conservative_grown_start_body_must_fit(self):
        self.obs['events'] = [self.hit()]
        self.obs['cubes'] = [{'id': 10, 'pos': [0, 0, 0]}]
        self.bot.update(self.obs)
        stats = self.bot.stats(self.obs['self'])
        def point_clear(point, radius, height):
            return point != self.obs['self']['pos'] or radius <= stats['radius']
        with patch.object(self.bot.map, 'point_clear', side_effect=point_clear):
            self.assertEqual(self.select(), (True, None))
        self.assertIsNone(self.rx.active)

    def test_inertia_prior_intent_charge_and_ground_scope_prevent_admission(self):
        changes = [lambda: setattr(self.bot, 'last_move', (1, 0)),
                   lambda: self.obs['self'].update(vel=[1.01, 0, 0]),
                   lambda: self.obs['self'].update(grounded=False),
                   lambda: self.obs['self'].update(pos=[0, 0, 4]),
                   lambda: self.obs['self'].update(weapons=[self.weapon('laser', charge=.1), None])]
        for change in changes:
            with self.subTest(change=change):
                self.setUp()
                self.obs['events'] = [self.hit()]
                change()
                self.act()
                self.assertIsNone(self.rx.active)

    def test_observed_actor_and_urgent_rotation_keep_ordinary_priority(self):
        for urgent in (False, True):
            with self.subTest(urgent=urgent):
                self.setUp()
                self.obs['events'] = [self.hit()]
                if not urgent:
                    self.obs['mechs'] = [self.enemy()]
                with patch.object(self.bot.zone_resources, 'rotation_required', return_value=urgent):
                    self.act()
                self.assertIsNone(self.rx.active)
                self.assertEqual(self.bot.mode, 'rotate' if urgent else 'recover')

    def test_body_growth_and_invalid_route_cancel_owned_goal(self):
        for growth in (False, True):
            with self.subTest(growth=growth):
                self.setUp()
                self.start()
                self.advance()
                if growth:
                    self.obs['self']['cubes'] += 1
                with patch.object(self.bot, 'safe_goal', return_value=[0, 20, 0]) as safe:
                    with patch.object(self.bot.map, 'move_clear', return_value=growth):
                        self.act()
                self.assertEqual(safe.call_count, 1)
                self.assertIsNone(self.rx.active)
                self.assertEqual(self.bot.goal, [0, 20, 0])


class CapturedReactiveRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'tests/fixtures/reactive-recovery.json').read_text())
        cls.hello = copy.deepcopy(cls.data['hello'])
        cls.hello['map']['dir'] = str(ROOT / 'arena')
        cls.arena = policy.ArenaMap(ROOT / 'arena', cls.hello['config'])
        assert cls.arena.available and len(cls.arena.prisms) == 259

    def test_captured_unseen_hit_selects_grounded_lateral_route(self):
        obs = copy.deepcopy(next(o for o in self.data['observations'] if o['t'] == 164.3))
        with patch.object(policy, 'ArenaMap', return_value=self.arena):
            bot = policy.Bot(copy.deepcopy(self.hello))
        bot.recover = True
        bot.goal_kind = bot.mode = 'recover'
        bot.goal = list(obs['self']['pos'])
        bot.goal_until = obs['t'] + .5
        bot.last_move = (0, 0)
        with patch('time.perf_counter', return_value=100.):
            action = bot.act(obs)
        self.assertEqual(bot.reactive_recovery.last_report['reason'], 'admitted')
        self.assertAlmostEqual(bot.goal[0], 56.1466246193, places=6)
        self.assertAlmostEqual(bot.goal[1], -157.9541809045, places=6)
        self.assertGreater(math.hypot(*action['move']), .9)
        bearing = bot.reactive_recovery.evidence['bearing']
        self.assertLessEqual(action['move'][0]*math.cos(bearing)+action['move'][1]*math.sin(bearing), 1e-8)
        stats = bot.stats(obs['self'])
        self.assertTrue(bot.zone_resources._ground_segment(obs['self']['pos'], bot.goal, stats['radius'], math.inf))
        self.assertTrue(bot.map.move_clear(obs['self']['pos'], bot.goal, stats['radius'], stats['height']))


if __name__ == '__main__':
    unittest.main()
