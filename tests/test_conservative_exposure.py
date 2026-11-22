"""Binary recovery scoring may skip rays which cannot reduce its risk."""
import copy
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exposure import ExposureModel, ExposureResult
import bot as policy
from test_strategy import FlatArena, official_fixture


class ConservativeExposureTests(unittest.TestCase):
    def setUp(self):
        hello, self.obs = official_fixture()
        self.config = hello['config']
        self.me = self.obs['self']
        self.actor = dict(id=1, kind='mech', pos=[100., 0., 0.], cubes=0, weapons=['gun', 'mortar'])
        with patch.object(policy, 'ArenaMap', FlatArena):
            self.bot = policy.Bot(hello)

    def test_binary_risk_matches_full_query_for_mortar_and_unknown_loadouts(self):
        for kinds in (['gun', 'mortar'], ['mortar'], ['future'], ['gun', 'future'], None):
            for clear in (False, True):
                with self.subTest(kinds=kinds, clear=clear):
                    actor = dict(self.actor, weapons=kinds)
                    calls = []
                    model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or clear)
                    normal = model.incoming(self.me, actor, include_width=True, max_rays=4)
                    before = len(calls)
                    fast = model.incoming(self.me, actor, include_width=True, max_rays=4, conservative_only=True)
                    self.assertEqual(normal.conservative_fraction, fast.conservative_fraction)
                    self.assertEqual(len(calls), before)
                    self.assertIsNone(fast.visible)
                    self.assertEqual(fast.rays, 0)
                    self.assertEqual(fast.reasons, ('unmodeled_weapon_path',))

    def test_default_keeps_direct_visibility_detail_for_mixed_mortar(self):
        calls = []
        model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or True)
        self.assertTrue(model.incoming(self.me, self.actor).visible)
        self.assertEqual(len(calls), 1)

    def test_known_direct_weapons_and_npc_still_cast_rays(self):
        for actor in (dict(self.actor, weapons=['gun']), dict(self.actor, kind='npc', weapons=None)):
            with self.subTest(kind=actor['kind']):
                calls = []
                model = ExposureModel(self.config, lambda a, b: calls.append((a, b)) or False)
                result = model.incoming(self.me, actor, conservative_only=True)
                self.assertFalse(result.visible)
                self.assertEqual(len(calls), 2)

    def test_empty_weapons_remain_no_threat_and_missing_weapons_remain_unknown(self):
        model = ExposureModel(self.config, lambda a, b: self.fail('Unexpected ray'))
        self.assertFalse(model.incoming(self.me, dict(self.actor, weapons=[]), conservative_only=True).visible)
        missing = dict(self.actor); del missing['weapons']
        self.assertIsNone(model.incoming(self.me, missing, conservative_only=True).visible)

    def test_no_ray_budget_or_expired_deadline_does_not_fake_incomplete_indirect_query(self):
        model = ExposureModel(self.config, lambda a, b: self.fail('Unexpected ray'))
        model.begin_frame(1, ray_budget=0)
        result = model.incoming(self.me, self.actor, deadline=0, max_rays=0, conservative_only=True)
        self.assertEqual(result.conservative_fraction, 1.)
        self.assertEqual(result.reasons, ('unmodeled_weapon_path',))
        direct = model.incoming(self.me, dict(self.actor, weapons=['gun']), conservative_only=True)
        self.assertIsNone(direct.visible)
        self.assertIn('ray_budget', direct.reasons)

    def test_recovery_scalar_cost_matches_detailed_query_without_changing_other_modes(self):
        bot = self.bot; stats = bot.stats(self.me)
        for clear in (False, True):
            for kinds in (['gun', 'mortar'], ['unknown'], ['gun']):
                with self.subTest(clear=clear, kinds=kinds):
                    actor = dict(self.actor, weapons=kinds)
                    threats = [dict(actor=actor, d=100, los=True, risk=1.)]
                    bot.recovery_exposure.clear_cache()
                    args = (self.me['pos'], threats, [0, 0], 500, stats['radius'], True, stats['muzzle_height'])
                    kwargs = dict(me=self.me, effective_stats=stats)
                    with patch.object(bot.map, 'line_of_fire', return_value=clear):
                        fast = bot.position_cost(*args, **kwargs)
                        actual = bot.recovery_exposure.incoming
                        def detailed(*a, **kw):
                            kw['conservative_only'] = False
                            return actual(*a, **kw)
                        with patch.object(bot.recovery_exposure, 'incoming', side_effect=detailed):
                            detailed_score = bot.position_cost(*args, **kwargs)
                        self.assertEqual(fast, detailed_score)
                        with patch.object(bot.recovery_exposure, 'incoming', side_effect=AssertionError('Nonrecovery must not opt in')):
                            bot.position_cost(*args[:5], False, *args[6:], **kwargs)

    def test_mixed_direct_deadline_keeps_scan_candidate_unresolved(self):
        bot = self.bot; bot.recover = True; bot.mode = 'recover'
        self.me['pos'] = [0., 0., 0.]
        stats = bot.stats(self.me)
        direct = dict(self.actor, id=2, weapons=['gun'])
        threats = [dict(actor=a, d=100, los=True, risk=1.) for a in (self.actor, direct)]
        original = bot.recovery_exposure.incoming
        def query(me, actor, **kw):
            if actor['id'] == 1:
                return original(me, actor, **kw)
            if kw['position'][0] == 20:
                return ExposureResult(0, 0, 4, reasons=('deadline',))
            return ExposureResult(1, 0, 3, rays=1)
        with patch.object(bot.map, 'cover_candidates', return_value=[[20., 0., 0.], [40., 0., 0.]]), \
                patch.object(bot.recovery_exposure, 'incoming', side_effect=query):
            bot.safe_goal(self.obs, threats, stats, time.perf_counter()+1)
        self.assertEqual(bot.recovery_cover_report['scanned'], 0)
        self.assertEqual(bot._recovery_scan_cursor, 0)
        self.assertEqual(bot.recovery_cover_report['evaluated'], 2)

    def test_indirect_only_zero_budget_still_advances_completed_scan(self):
        bot = self.bot; bot.recover = True; bot.mode = 'recover'
        self.me['pos'] = [0., 0., 0.]
        stats = bot.stats(self.me)
        bot.recovery_exposure.begin_frame(1, ray_budget=0)
        threats = [dict(actor=self.actor, d=100, los=True, risk=1.)]
        with patch.object(bot.map, 'cover_candidates', return_value=[[20., 0., 0.], [40., 0., 0.]]):
            bot.safe_goal(self.obs, threats, stats, time.perf_counter()+1)
        report = bot.recovery_cover_report
        self.assertGreater(report['scanned'], 0)
        self.assertEqual(report['scanned'], report['scan_size'])
        self.assertEqual(report['rays'], 0)


if __name__ == '__main__':
    unittest.main()
