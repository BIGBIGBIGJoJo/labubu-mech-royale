"""Opt-in defense and finish policy regressions; no private trace dependency."""
import copy
import gzip
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena_map import ArenaMap
from combat import Combat
from engagement import Engagement, ExperimentalPolicy

with gzip.open(ROOT / "check/stream.jsonl.gz", "rt") as stream:
    CONFIG = json.loads(next(stream))["config"]

def weapon(kind='gun', **changes):
    result = {'kind': kind, 'stats': dict(CONFIG['weapons'][kind]), 'cooldown': 0}
    if kind == 'gun':
        result.update(ammo=12, reload=0)
    if kind == 'laser':
        result['charge'] = 0
    result.update(changes)
    return result

def actor(actor_id=1, x=100, y=0, hp=100, **changes):
    result = {'id': actor_id, 'kind': 'mech', 'pos': [x, y, 0], 'vel': [0, 0, 0], 'aim': [math.pi, 0], 'hp': hp, 'max_hp': 1400, 'cubes': 0, 'weapons': ['gun']}
    result.update(changes)
    return result

def observation(*actors, weapons=None, t=5):
    return {'tick': round(t * 20), 't': t, 'self': {'id': 0, 'pos': [0, 0, 0], 'vel': [0, 0, 0], 'aim': [0, -0.025], 'hp': 1400, 'max_hp': 1400, 'energy': 100, 'cubes': 0, 'stats': dict(CONFIG['mech']), 'weapons': weapons or [weapon(), None]}, 'mechs': list(actors), 'beams': [], 'events': [], 'projectiles': [], 'sounds': [], 'crates': []}

def candidates(obs, los=True):
    return [{'actor': a, 'd': math.dist(obs['self']['pos'], a['pos']), 'los': los, 'risk': 1} for a in obs['mechs']]

def attack(obs, *ids):
    obs['events'] = [{'type': 'damaged', 'by': i, 'weapon': 'gun', 'amount': 45} for i in ids]
    return obs

def advance(obs, seconds):
    result = copy.deepcopy(obs)
    result['t'] += seconds
    result['tick'] = round(result['t'] * 20)
    result['events'] = []
    result['beams'] = []
    return result

def prototype(**changes):
    return Engagement(CONFIG, lambda a, b: True, experimental_policy=ExperimentalPolicy(**changes))

def fire_for(obs, decision):
    protected = {a['id'] for a in obs['mechs'] if a['kind'] == 'mech'} - decision.authorized_ids
    return Combat(CONFIG, lambda a, b: True).plan(obs, decision.target, decision.allow_fire, protected_ids=protected)

class DefenseContinuationTests(unittest.TestCase):

    def test_never_attributed_mech_cannot_be_admitted_by_weak_signals(self):
        for t in (0.1, 60, 300):
            obs = observation(actor(x=20, hp=1, vel=[-15, 0, 0]), t=t)
            obs['sounds'] = [{'kind': 'gun', 'bearing': 0, 'age': 0}]
            obs['projectiles'] = [{'id': 20, 'kind': 'gun', 'pos': [15, 0, 5], 'vel': [-252, 0, 0]}]
            result = prototype().select(obs, candidates(obs), safe_finish=True)
            self.assertFalse(result.allow_fire)
            self.assertEqual(result.authorized_ids, frozenset())

    def test_facing_known_attacker_can_continue_after_three_seconds(self):
        controller = prototype()
        first = attack(observation(actor()), 1)
        controller.select(first, candidates(first))
        later = advance(first, 4)
        result = controller.select(later, candidates(later))
        self.assertEqual(result.mode, 'DEFEND')
        self.assertEqual(result.reason, 'continuing_attributed_attack')
        self.assertEqual(result.evidence_age, 4)
        self.assertEqual(result.authorized_ids, frozenset({1}))

    def test_pursuit_can_corroborate_when_facing_is_temporarily_away(self):
        controller = prototype()
        first = attack(observation(actor(aim=[0, 0], vel=[-2, 0, 0])), 1)
        controller.select(first, candidates(first))
        later = advance(first, 4)
        self.assertEqual(controller.select(later, candidates(later)).mode, 'DEFEND')

    def test_retreating_and_facing_away_attacker_is_not_continued(self):
        controller = prototype()
        first = attack(observation(actor(aim=[0, 0], vel=[2, 0, 0])), 1)
        controller.select(first, candidates(first))
        later = advance(first, 4)
        self.assertFalse(controller.select(later, candidates(later)).allow_fire)

    def test_our_motion_cannot_create_pursuit_corroboration(self):
        controller = prototype()
        first = attack(observation(actor(aim=[0, 0])), 1)
        first['self']['vel'] = [12, 0, 0]
        controller.select(first, candidates(first))
        later = advance(first, 4)
        self.assertFalse(controller.select(later, candidates(later)).allow_fire)

    def test_continuation_thresholds_are_explicit(self):
        for yaw_error, approach, expected in ((0.25, 0, True), (0.251, 0, False), (1, 1.5, False), (1, 1.501, True)):
            with self.subTest(yaw_error=yaw_error, approach=approach):
                controller = prototype()
                first = attack(observation(actor(aim=[math.pi - yaw_error, 0], vel=[-approach, 0, 0])), 1)
                controller.select(first, candidates(first))
                later = advance(first, 4)
                self.assertEqual(controller.select(later, candidates(later)).allow_fire, expected)

    def test_current_los_is_required_even_with_both_corroborating_signals(self):
        controller = prototype()
        first = attack(observation(actor(vel=[-5, 0, 0])), 1)
        controller.select(first, candidates(first))
        later = advance(first, 4)
        self.assertFalse(controller.select(later, candidates(later, los=False)).allow_fire)
        stale_candidates = candidates(later)
        later['mechs'] = []
        self.assertFalse(controller.select(later, stale_candidates).allow_fire)

    def test_hard_eight_second_expiry_is_not_refreshed_by_hits_aim_or_pursuit(self):
        controller = prototype()
        first = attack(observation(actor(vel=[-3, 0, 0])), 1)
        controller.select(first, candidates(first))
        for elapsed in (4, 5, 6, 7):
            obs = advance(first, elapsed)
            obs['events'] = [{'type': 'hit', 'target': 1, 'amount': 45, 'weapon': 'gun'}]
            self.assertTrue(controller.select(obs, candidates(obs)).allow_fire)
            self.assertEqual(controller.attackers[1].at, first['t'])
        expired = advance(first, 8)
        self.assertFalse(controller.select(expired, candidates(expired)).allow_fire)
        self.assertNotIn(1, controller.attackers)

    def test_new_strong_attack_can_renew_attribution(self):
        controller = prototype()
        first = attack(observation(actor()), 1)
        controller.select(first, candidates(first))
        renewed = attack(advance(first, 7), 1)
        controller.select(renewed, candidates(renewed))
        later = advance(first, 9)
        self.assertTrue(controller.select(later, candidates(later)).allow_fire)
        self.assertEqual(controller.attackers[1].at, renewed['t'])

    def test_recovery_uses_original_quiet_window(self):
        controller = prototype()
        first = attack(observation(actor()), 1)
        controller.select(first, candidates(first))
        later = advance(first, 3.1)
        result = controller.select(later, candidates(later), recovering=True)
        self.assertFalse(result.allow_fire)
        self.assertEqual(result.authorized_ids, frozenset())
        self.assertTrue(controller.select(later, candidates(later), recovering=False).allow_fire)

    def test_nanite_window_also_expires_collateral_permission(self):
        controller = prototype()
        first = attack(observation(actor()), 1)
        first['self']['stats']['regen_delay'] = 2
        controller.select(first, candidates(first), recovering=True)
        later = advance(first, 2.1)
        result = controller.select(later, candidates(later), recovering=True)
        self.assertFalse(result.allow_fire)
        self.assertEqual(result.authorized_ids, frozenset())

    def test_two_fresh_attackers_can_receive_defensive_lightning_chain(self):
        obs = attack(observation(actor(1, x=30, hp=30), actor(2, x=40, hp=300), weapons=[weapon('lightning'), None]), 1, 2)
        result = prototype().select(obs, candidates(obs))
        self.assertEqual(result.target['id'], 1)
        self.assertEqual(result.authorized_ids, frozenset({1, 2}))
        self.assertTrue(fire_for(obs, result)['fire'][0])
        nominal = Engagement(CONFIG, lambda a, b: True).select(obs, candidates(obs))
        self.assertFalse(nominal.allow_fire)

    def test_quiet_chain_recipient_remains_protected(self):
        obs = attack(observation(actor(1, x=30, hp=30), actor(2, x=40, hp=300), actor(3, x=35, y=5, hp=1), weapons=[weapon('lightning'), None]), 1, 2)
        result = prototype().select(obs, candidates(obs))
        self.assertFalse(result.allow_fire)
        self.assertEqual(result.authorized_ids, frozenset({1, 2}))
        self.assertNotIn(3, result.authorized_ids)
        protected = {3}
        self.assertFalse(Combat(CONFIG).plan(obs, obs['mechs'][0], protected_ids=protected)['fire'][0])

    def test_second_attackers_old_evidence_is_not_a_collateral_exemption(self):
        controller = prototype()
        first = attack(observation(actor(1, x=30, hp=30), actor(2, x=40, hp=300), weapons=[weapon('lightning'), None]), 1, 2)
        controller.select(first, candidates(first))
        later = attack(advance(first, 3.1), 1)
        result = controller.select(later, candidates(later))
        self.assertEqual(result.authorized_ids, frozenset({1}))
        self.assertFalse(result.allow_fire)

    def test_selected_older_continuer_and_other_fresh_attacker_are_authorized(self):
        controller = prototype()
        first = attack(observation(actor(1, hp=30), actor(2, y=30, hp=300), actor(3, y=-30, hp=1)), 1)
        controller.select(first, candidates(first))
        later = attack(advance(first, 4), 2)
        result = controller.select(later, candidates(later))
        self.assertEqual(result.target['id'], 1)
        self.assertEqual(result.authorized_ids, frozenset({1, 2}))

    def test_invisible_attacker_is_not_in_current_authorization_set(self):
        obs = attack(observation(actor()), 1, 2)
        result = prototype().select(obs, candidates(obs))
        self.assertEqual(result.authorized_ids, frozenset({1}))

    def test_gun_cannot_claim_farther_low_hp_target_through_authorized_body(self):
        obs = attack(observation(actor(1, x=100, hp=30), actor(2, x=50, hp=300)), 1, 2)
        controller = prototype()
        result = controller.select(obs, candidates(obs))
        self.assertEqual(result.target['id'], 2)
        self.assertEqual(result.authorized_ids, frozenset({1, 2}))
        profile = controller._weapon_profile(obs, obs['mechs'][0], 3, frozenset({1, 2}))
        self.assertEqual(profile, (None, None))
        self.assertTrue(fire_for(obs, result)['fire'][0])

    def test_moving_authorized_body_can_intercept_before_selected_target(self):
        obs = attack(observation(actor(1, x=100, hp=30), actor(2, x=50, y=15, hp=300, vel=[0, -60, 0])), 1, 2)
        controller = prototype()
        controller.update(obs)
        profile = controller._weapon_profile(obs, obs['mechs'][0], 3, frozenset({1, 2}))
        self.assertEqual(profile, (None, None))

    def test_growing_body_changes_direct_reachability_even_when_authorized(self):
        obs = attack(observation(actor(1, x=100, hp=30), actor(2, x=50, y=4, hp=300)), 1, 2)
        controller = prototype()
        self.assertEqual(controller.select(obs, candidates(obs)).target['id'], 1)
        obs['mechs'][1]['cubes'] = 20
        self.assertIsNone(controller._weapon_profile(obs, obs['mechs'][0], 3, frozenset({1, 2}))[0])

    def test_laser_pierce_budget_controls_target_reachability(self):
        obs = attack(observation(actor(1, x=100, hp=30), actor(2, x=50, hp=300), weapons=[weapon('laser'), None]), 1, 2)
        self.assertEqual(prototype().select(obs, candidates(obs)).target['id'], 2)
        obs['self']['weapons'][0]['stats']['pierce'] = 1
        result = prototype().select(obs, candidates(obs))
        self.assertEqual(result.target['id'], 1)
        self.assertTrue(fire_for(obs, result)['fire'][0])
        obs['mechs'].append(actor(3, x=70, hp=400))
        obs['events'].append({'type': 'damaged', 'by': 3, 'weapon': 'gun', 'amount': 45})
        controller = prototype()
        controller.update(obs)
        self.assertIsNone(controller._weapon_profile(obs, obs['mechs'][0], 3, frozenset({1, 2, 3}))[0])

    def test_pierce_does_not_authorize_a_quiet_interceptor(self):
        laser = weapon('laser')
        laser['stats']['pierce'] = 1
        obs = attack(observation(actor(1, x=100, hp=30), actor(2, x=50, hp=300), weapons=[laser, None]), 1)
        result = prototype().select(obs, candidates(obs))
        self.assertFalse(result.allow_fire)
        self.assertEqual(result.authorized_ids, frozenset({1}))

    def test_lightning_does_not_claim_direct_damage_through_an_authorized_primary(self):
        obs = attack(observation(actor(1, x=40, hp=30), actor(2, x=30, hp=300), weapons=[weapon('lightning'), None]), 1, 2)
        controller = prototype()
        result = controller.select(obs, candidates(obs))
        self.assertEqual(result.target['id'], 2)
        self.assertIsNone(controller._weapon_profile(obs, obs['mechs'][0], 3, frozenset({1, 2}))[0])

    def test_only_selected_fight_participant_is_authorized_without_defensive_proof(self):
        obs = observation(actor(1, x=100, hp=30), actor(2, x=100, y=30, hp=300))
        obs['beams'] = [{'by': 2, 'kind': 'laser', 'age': 0.1, 'path': [[100, 30, 7], [100, 0, 4.5]]}]
        result = prototype().select(obs, candidates(obs), safe_finish=True)
        self.assertEqual(result.mode, 'FINISH')
        self.assertEqual(result.authorized_ids, frozenset({1}))

    def test_external_fight_ttl_is_unchanged_by_defense_experiment(self):
        controller = prototype()
        first = observation(actor(hp=30))
        first['beams'] = [{'by': 2, 'kind': 'laser', 'age': 0.1, 'path': [[100, 30, 7], [100, 0, 4.5]]}]
        controller.select(first, candidates(first), safe_finish=True)
        later = advance(first, 2.1)
        self.assertFalse(controller.select(later, candidates(later), safe_finish=True).allow_fire)

    def test_old_beam_repetition_does_not_refresh_defensive_proof(self):
        controller = prototype()
        first = observation(actor())
        first['beams'] = [{'by': 1, 'kind': 'laser', 'age': 0.1, 'path': [[100, 0, 7], [0, 0, 4.5]]}]
        controller.select(first, candidates(first))
        repeat = advance(first, 0.5)
        repeat['beams'] = [dict(first['beams'][0], age=0.6)]
        controller.select(repeat, candidates(repeat))
        self.assertAlmostEqual(controller.attackers[1].at, 4.9)
        expired = advance(first, 8.1)
        self.assertFalse(controller.select(expired, candidates(expired)).allow_fire)

    def test_snapshot_inputs_are_not_mutated(self):
        obs = attack(observation(actor()), 1)
        before = copy.deepcopy(obs)
        result = prototype().select(obs, candidates(obs))
        self.assertEqual(obs, before)
        self.assertIsInstance(result.authorized_ids, frozenset)

    def test_configuration_cannot_remove_hard_eight_second_cap(self):
        with self.assertRaises(ValueError):
            ExperimentalPolicy(continuation_seconds=9)

def beam(target, by=9, age=0.1):
    x, y, z = target['pos']
    return {'by': by, 'kind': 'lightning', 'age': age, 'path': [[x + 30, y + 10, z + 7], [x, y, z + 4.5]]}

class FinishCommitmentTests(unittest.TestCase):

    def controller(self, config=None, line_of_fire=None):
        return Engagement(config or CONFIG, line_of_fire or (lambda a, b: True), experimental_policy=ExperimentalPolicy(finish_commitment=True))

    def first(self, hp=60, age=0.1):
        target = actor(1, x=100, hp=hp)
        obs = observation(target, t=5)
        obs['beams'] = [beam(target, age=age)]
        return obs

    def select(self, controller, obs, *, safe=True, budget=2, los=True, recovering=False):
        return controller.select(obs, candidates(obs, los=los), safe_finish=safe, finish_budget_s=budget, recovering=recovering)

    def assert_observe(self, decision):
        self.assertEqual(decision.mode, 'OBSERVE')
        self.assertIsNone(decision.target)
        self.assertFalse(decision.allow_fire)

    def test_recorded_entry_survives_original_evidence_expiry(self):
        fixture = json.loads((ROOT / 'tests/fixtures/finish_commitment.json').read_text(encoding='utf-8'))
        config = fixture['config']
        arena = ArenaMap(ROOT / 'arena', config)
        self.assertTrue(arena.available, arena.error)
        controller = self.controller(config, arena.line_of_fire)
        controller.update(fixture['evidence'])

        def select_recorded(obs):
            safety = fixture['safety'][format(obs['t'], '.1f')]
            me = obs['self']
            origin = [me['pos'][0], me['pos'][1], me['pos'][2] + me['stats']['muzzle_height']]
            visible = []
            for target in obs['mechs']:
                if target['kind'] != 'mech':
                    continue
                height = config['mech']['height'] * (1 + config['cubes']['size_per_cube'] * target['cubes'])
                los = any((arena.line_of_fire(origin, [target['pos'][0], target['pos'][1], target['pos'][2] + height * fraction]) for fraction in (0.5, 0.9)))
                visible.append({'actor': target, 'los': los, 'risk': 1, 'd': math.dist(me['pos'][:2], target['pos'][:2])})
            return controller.select(obs, visible, safe_finish=lambda target: target['id'] in safety['allowed_ids'], finish_budget_s=safety['budget_s'])
        entry = fixture['entry']
        before = copy.deepcopy(entry)
        decision = select_recorded(entry)
        self.assertEqual(decision.mode, 'FINISH')
        self.assertEqual(decision.target['id'], 8)
        self.assertEqual(decision.target['hp'], 255)
        self.assertAlmostEqual(decision.finish_eta, 0.75)
        self.assertAlmostEqual(decision.entry_evidence_at, 50)
        self.assertAlmostEqual(decision.finish_deadline, 53.7)
        self.assertEqual(entry, before)
        later = select_recorded(fixture['continuation'])
        self.assertEqual(later.mode, 'FINISH')
        self.assertEqual(later.target['id'], 8)
        self.assertAlmostEqual(later.finish_deadline, decision.finish_deadline)
        self.assertAlmostEqual(later.entry_evidence_at, 50)

    def test_quiet_weak_target_never_starts_commitment(self):
        obs = observation(actor(hp=1))
        self.assert_observe(self.select(self.controller(), obs))

    def test_own_hit_cannot_establish_entry(self):
        obs = observation(actor(hp=1))
        obs['events'] = [{'type': 'hit', 'target': 1, 'weapon': 'gun', 'amount': 45}]
        self.assert_observe(self.select(self.controller(), obs))

    def test_expired_initial_evidence_cannot_start_commitment(self):
        self.assert_observe(self.select(self.controller(), self.first(hp=10, age=2.1)))

    def test_caller_budget_bounds_entry_and_fixed_deadline(self):
        controller = self.controller()
        obs = self.first(hp=10)
        self.assert_observe(self.select(controller, obs, budget=0.1))
        controller = self.controller()
        result = self.select(controller, obs, budget=1)
        self.assertEqual(result.mode, 'FINISH')
        self.assertAlmostEqual(result.finish_deadline, 6)
        self.assertLessEqual(result.finish_budget_s, 0.9 + 1e-08)

    def test_healing_cancels_and_consumes_old_evidence(self):
        controller = self.controller()
        obs = self.first()
        self.assertEqual(self.select(controller, obs).mode, 'FINISH')
        healed = advance(obs, 0.2)
        healed['mechs'][0]['hp'] += 1
        self.assert_observe(self.select(controller, healed))
        again = advance(healed, 0.1)
        again['mechs'][0]['hp'] = 60
        again['events'] = [{'type': 'hit', 'target': 1, 'weapon': 'gun', 'amount': 1}]
        again['beams'] = [beam(again['mechs'][0], age=0.4)]
        self.assert_observe(self.select(controller, again))

    def test_lost_los_cancels_and_old_evidence_cannot_restart(self):
        controller = self.controller()
        obs = self.first()
        self.assertEqual(self.select(controller, obs).mode, 'FINISH')
        hidden = advance(obs, 0.2)
        self.assert_observe(self.select(controller, hidden, los=False))
        self.assert_observe(self.select(controller, advance(hidden, 0.1)))

    def test_safety_withdrawal_cancels_and_consumes_old_evidence(self):
        controller = self.controller()
        obs = self.first()
        self.assertEqual(self.select(controller, obs).mode, 'FINISH')
        vetoed = advance(obs, 0.2)
        self.assert_observe(self.select(controller, vetoed, safe=False))
        self.assert_observe(self.select(controller, advance(vetoed, 0.1), safe=True))

    def test_recovery_cancels_commitment(self):
        controller = self.controller()
        obs = self.first()
        self.select(controller, obs)
        later = advance(obs, 0.2)
        self.assert_observe(self.select(controller, later, recovering=True))
        self.assert_observe(self.select(controller, advance(later, 0.1)))

    def test_fresh_self_defense_cancels_and_consumes_finish_evidence(self):
        controller = self.controller()
        obs = self.first()
        self.assertEqual(self.select(controller, obs).mode, 'FINISH')
        attacked = advance(obs, 0.2)
        attacked['mechs'].append(actor(3, x=100, y=30, hp=1400))
        attack(attacked, 3)
        defense = self.select(controller, attacked)
        self.assertEqual(defense.mode, 'DEFEND')
        self.assertEqual(defense.target['id'], 3)
        quiet = advance(attacked, 0.1)
        quiet['mechs'] = [quiet['mechs'][0]]
        self.assert_observe(self.select(controller, quiet))

    def test_safety_abort_releases_held_laser_without_new_aim(self):
        controller = self.controller()
        obs = self.first(hp=150)
        obs['self']['weapons'] = [weapon(), weapon('laser')]
        self.assertEqual(self.select(controller, obs).mode, 'FINISH')
        later = advance(obs, 0.2)
        later['self']['weapons'][1]['charge'] = 0.3
        decision = self.select(controller, later, safe=False)
        self.assert_observe(decision)
        action = fire_for(later, decision)
        self.assertEqual(action['aim'], later['self']['aim'])
        self.assertEqual(action['fire'], [False, False])
        self.assertGreater(later['self']['weapons'][1]['charge'], 0)

    def test_exhausted_remaining_budget_cancels_without_restart(self):
        controller = self.controller()
        obs = self.first(hp=10)
        first = self.select(controller, obs)
        self.assertEqual(first.mode, 'FINISH')
        late = advance(obs, 1.8)
        late['events'] = [{'type': 'hit', 'target': 1, 'weapon': 'gun', 'amount': 1}]
        late['mechs'][0]['hp'] = 9
        self.assert_observe(self.select(controller, late))
        self.assert_observe(self.select(controller, advance(late, 0.1)))

    def test_expiry_and_own_hits_cannot_renew_commitment(self):
        controller = self.controller()
        obs = self.first(hp=10)
        entry = self.select(controller, obs)
        self.assertAlmostEqual(entry.finish_deadline, 7)
        expired = advance(obs, 2.01)
        expired['events'] = [{'type': 'hit', 'target': 1, 'weapon': 'gun', 'amount': 1}]
        self.assert_observe(self.select(controller, expired))

    def test_new_external_evidence_after_cancel_can_authorize_new_entry(self):
        controller = self.controller()
        obs = self.first()
        self.select(controller, obs)
        canceled = advance(obs, 0.2)
        self.select(controller, canceled, safe=False)
        fresh = advance(canceled, 0.2)
        fresh['beams'] = [beam(fresh['mechs'][0], age=0.1)]
        decision = self.select(controller, fresh)
        self.assertEqual(decision.mode, 'FINISH')
        self.assertAlmostEqual(decision.entry_evidence_at, 5.3)
        self.assertAlmostEqual(decision.finish_deadline, 7.4)

    def test_consumed_beam_cannot_restart_against_its_other_participant(self):
        controller = self.controller()
        obs = self.first()
        self.assertEqual(self.select(controller, obs).target['id'], 1)
        canceled = advance(obs, 0.2)
        self.assert_observe(self.select(controller, canceled, safe=False))
        other = advance(canceled, 0.1)
        other['mechs'].append(actor(9, x=130, y=10, hp=10))
        other['beams'] = [beam(other['mechs'][0], by=9, age=0.4)]
        self.assert_observe(self.select(controller, other))
        fresh = advance(other, 0.2)
        fresh['beams'] = [beam(fresh['mechs'][0], by=9, age=0.1)]
        decision = self.select(controller, fresh)
        self.assertEqual(decision.mode, 'FINISH')
        self.assertEqual(decision.target['id'], 9)
        self.assertAlmostEqual(decision.entry_evidence_at, 5.4)

    def test_lower_hp_fresh_participant_retargets_without_deadline_reset(self):
        controller = self.controller()
        obs = self.first()
        initial = self.select(controller, obs)
        later = advance(obs, 0.3)
        weaker = actor(3, x=100, y=30, hp=10)
        later['mechs'].append(weaker)
        later['beams'] = [beam(weaker, age=0.1)]
        result = self.select(controller, later)
        self.assertEqual(result.mode, 'FINISH')
        self.assertEqual(result.target['id'], 3)
        self.assertAlmostEqual(result.finish_deadline, initial.finish_deadline)
        self.assertLessEqual(result.finish_budget_s, 1.6 + 1e-08)
        expired = advance(later, 1.75)
        self.assert_observe(self.select(controller, expired))

    def test_lower_hp_quiet_mech_cannot_borrow_commitment(self):
        controller = self.controller()
        obs = self.first()
        initial = self.select(controller, obs)
        later = advance(obs, 0.3)
        later['mechs'].append(actor(3, x=100, y=30, hp=1))
        result = self.select(controller, later)
        self.assertEqual(result.mode, 'FINISH')
        self.assertEqual(result.target['id'], 1)
        self.assertAlmostEqual(result.finish_deadline, initial.finish_deadline)

if __name__ == "__main__":
    unittest.main()
