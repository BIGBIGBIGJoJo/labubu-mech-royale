"""Conditional policy checks on captured observations, not match outcomes."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from duel import DuelController
from combat import Combat


class CapturedDuelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads((Path(__file__).parent/'data/duel-captured-regressions.json').read_text())
        cls.cases = {case['name']: case for case in data['cases']}

    def replay(self, name, *, remove_hits=False):
        case = self.cases[name]
        controller = DuelController(case['config'])
        decisions = []
        for frame in case['frames']:
            obs = copy.deepcopy(frame['obs'])
            if remove_hits and obs['t'] > 14.1:
                obs['events'] = [e for e in obs['events'] if e['type'] != 'hit']
            decision = copy.deepcopy(controller.decide(obs, frame['threats'], frame['target'], frame['stats']))
            decisions.append((obs['t'], decision))
        return decisions

    def test_documented_cheap_seventeen_second_duel_is_retained(self):
        decisions = self.replay('favorable_final')
        self.assertEqual(len(decisions), 168)
        self.assertFalse(any(d['retreat'] for _, d in decisions))
        self.assertTrue(any(d.get('observed_remaining_s', 0) is not None and
                            d.get('observed_remaining_s', 0) > 8 for _, d in decisions))

    def test_expensive_trade_exits_despite_own_hits(self):
        decisions = self.replay('costly_final')
        t, report = next((t,d) for t,d in decisions if d['retreat'])
        self.assertEqual(t, 123.2)
        self.assertEqual(report['reason'], 'health_cost')
        self.assertGreater(report['recent_dealt'], 0)

    def test_pending_gun_arrival_preserves_observed_progress(self):
        decisions = dict(self.replay('evasion_burst_gap'))
        self.assertFalse(decisions[16.1]['retreat'])
        self.assertFalse(decisions[16.8]['retreat'])
        self.assertIsNone(decisions[16.8]['pending_hit_until'])

    def test_removing_hits_does_not_let_next_reload_renew_pending_deadline(self):
        decisions = dict(self.replay('evasion_burst_gap', remove_hits=True))
        deadline = decisions[16.1]['pending_hit_until']
        self.assertLessEqual(deadline-16.1, 1.)
        t, report = next((t,d) for t,d in decisions.items() if d['retreat'])
        self.assertGreaterEqual(t, deadline)
        self.assertLessEqual(t, deadline+.101)
        self.assertEqual(report['reason'], 'no_effective_progress')

    def test_recorded_near_full_laser_gets_release_command(self):
        case = self.cases['evasion_burst_gap']
        frame = next(f for f in case['frames'] if f['obs']['t'] == 16.6)
        controller = Combat(case['config'])
        action = controller.plan(frame['obs'], frame['target'])
        laser = next(i for i,w in enumerate(frame['obs']['self']['weapons']) if w and w['kind']=='laser')
        self.assertTrue(frame['recorded_action']['fire'][laser])
        self.assertFalse(action['fire'][laser])


if __name__ == '__main__':
    unittest.main()
