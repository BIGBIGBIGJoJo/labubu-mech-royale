"""Evidence, authorization, and resource-aware finish-policy regressions."""
import copy
from dataclasses import FrozenInstanceError
import gzip
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engagement import Engagement

with gzip.open(ROOT / "check/stream.jsonl.gz", "rt") as stream:
    CONFIG = json.loads(next(stream))["config"]


def weapon(kind="gun", **changes):
    result = {"kind": kind, "stats": dict(CONFIG["weapons"][kind]), "cooldown": 0}
    if kind == "gun":
        result.update(ammo=12, reload=0)
    if kind == "laser":
        result["charge"] = 0
    result.update(changes)
    return result


def actor(actor_id=1, x=100, y=0, hp=100, max_hp=1400, **changes):
    result = {"id": actor_id, "kind": "mech", "pos": [x, y, 0], "vel": [0, 0, 0],
              "hp": hp, "max_hp": max_hp, "cubes": 0, "aim": [0, 0], "weapons": ["gun"]}
    result.update(changes)
    return result


def observation(*actors, weapons=None, t=5.0):
    return {"tick": round(t * 20), "t": t, "self": {
        "id": 0, "pos": [0, 0, 0], "vel": [0, 0, 0], "aim": [0, -0.025],
        "hp": 1400, "max_hp": 1400, "energy": 100, "cubes": 0,
        "stats": dict(CONFIG["mech"]), "weapons": weapons or [weapon(), None]},
        "mechs": list(actors), "beams": [], "events": [], "projectiles": [],
        "sounds": [], "crates": [], "zone": {"center": [0, 0], "radius": 500}}


def threats(obs):
    return [{"actor": a, "d": math.dist(obs["self"]["pos"], a["pos"]), "los": True, "risk": 1}
            for a in obs["mechs"]]


def hit_beam(target, by=2, kind="laser", age=0.1):
    x, y, z = target["pos"]
    return {"by": by, "kind": kind, "age": age, "path": [[x + 30, y + 10, z + 7], [x, y, z + 4.5]]}


def advance(obs, seconds, *, clear=True):
    obs = copy.deepcopy(obs)
    obs["t"] += seconds
    obs["tick"] = round(obs["t"] * 20)
    if clear:
        obs["beams"] = []
        obs["events"] = []
    return obs


class EngagementTests(unittest.TestCase):
    def test_idle_enemy_is_never_authorized_by_health_proximity_or_time(self):
        for t in (0.1, 30, 120, 400):
            for hp in (1, 1400):
                with self.subTest(t=t, hp=hp):
                    obs = observation(actor(x=12, hp=hp), t=t)
                    decision = Engagement(CONFIG).select(obs, threats(obs), safe_finish=True)
                    self.assertEqual(decision.mode, "OBSERVE")
                    self.assertFalse(decision.allow_fire)

    def test_known_recent_attacker_authorizes_defense_during_recovery(self):
        obs = observation(actor(hp=1400))
        obs["events"] = [{"type": "damaged", "by": 1, "weapon": "gun", "amount": 45}]
        decision = Engagement(CONFIG).select(obs, threats(obs), recovering=True)
        self.assertEqual(decision.mode, "DEFEND")
        self.assertEqual(decision.target["id"], 1)
        self.assertTrue(decision.allow_fire)

    def test_zone_unknown_or_npc_damage_does_not_authorize_unrelated_mech(self):
        for by, kind in ((None, "zone"), (1, "zone"), (None, "gun"), (102, "npc")):
            with self.subTest(by=by, kind=kind):
                obs = observation(actor(hp=1))
                obs["events"] = [{"type": "damaged", "by": by, "weapon": kind, "amount": 25}]
                self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)

    def test_defense_expires_and_own_hits_do_not_refresh_it(self):
        controller = Engagement(CONFIG)
        obs = observation(actor())
        obs["events"] = [{"type": "damaged", "by": 1, "weapon": "gun", "amount": 45}]
        self.assertTrue(controller.select(obs, threats(obs)).allow_fire)
        later = advance(obs, 3.1)
        later["events"] = [{"type": "hit", "target": 1, "weapon": "gun", "amount": 45}]
        self.assertFalse(controller.select(later, threats(later)).allow_fire)

    def test_recovery_defense_window_respects_current_nanite_regen_delay(self):
        controller = Engagement(CONFIG)
        obs = observation(actor())
        obs["self"]["stats"]["regen_delay"] = 2
        obs["events"] = [{"type": "damaged", "by": 1, "weapon": "gun", "amount": 45}]
        controller.select(obs, threats(obs), recovering=True)
        later = advance(obs, 2.1)
        self.assertFalse(controller.select(later, threats(later), recovering=True).allow_fire)
        self.assertTrue(controller.select(later, threats(later), recovering=False).allow_fire)

    def test_attributed_beam_at_us_authorizes_defense_not_third_party_fight(self):
        obs = observation(actor(hp=1400))
        obs["beams"] = [{"by": 1, "kind": "laser", "age": 0.1, "path": [[100, 0, 7], [0, 0, 4.5]]}]
        controller = Engagement(CONFIG)
        decision = controller.select(obs, threats(obs), safe_finish=True)
        self.assertEqual(decision.mode, "DEFEND")
        self.assertFalse(controller.participants)

    def test_beam_passes_over_us_without_authorizing_defense(self):
        obs = observation(actor())
        obs["beams"] = [{"by": 1, "kind": "laser", "age": 0.1, "path": [[100, 0, 20], [0, 0, 20]]}]
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs)).allow_fire)

    def test_unseen_shooter_can_establish_visible_victim_fight(self):
        target = actor(4, hp=90)
        obs = observation(target)
        obs["beams"] = [hit_beam(target, by=10, kind="lightning")]
        controller = Engagement(CONFIG)
        decision = controller.select(obs, threats(obs), safe_finish=True)
        self.assertEqual(decision.mode, "FINISH")
        self.assertEqual(decision.target["id"], 4)
        self.assertEqual(decision.confidence, "attributed_beam")
        self.assertIn(10, controller.participants)
        self.assertLessEqual(decision.finish_eta, decision.finish_budget_s)

    def test_explicit_safety_is_required_and_can_veto_individual_targets(self):
        a, b = actor(1, hp=50), actor(3, x=110, y=10, hp=90)
        obs = observation(a, b)
        obs["beams"] = [hit_beam(a), hit_beam(b)]
        controller = Engagement(CONFIG)
        self.assertFalse(controller.select(obs, threats(obs)).allow_fire)
        calls = []
        def safe(target):
            calls.append(target["id"])
            return target["id"] == 3
        decision = controller.select(obs, threats(obs), safe_finish=safe)
        self.assertEqual(decision.target["id"], 3)
        self.assertIn((1, "unsafe_finish"), decision.exclusions)
        self.assertEqual(set(calls), {1, 3})

    def test_lowest_absolute_hp_wins_over_percentage_health(self):
        lower_absolute = actor(1, hp=160, max_hp=400)
        lower_fraction = actor(3, x=105, hp=180, max_hp=1400)
        obs = observation(lower_absolute, lower_fraction)
        obs["beams"] = [hit_beam(lower_absolute), hit_beam(lower_fraction)]
        decision = Engagement(CONFIG).select(obs, threats(obs), safe_finish=True)
        self.assertEqual(decision.target["id"], 1)

    def test_lowest_hp_attacker_wins_over_unrelated_wounded_enemy(self):
        obs = observation(actor(1, y=-20, hp=300), actor(2, hp=200), actor(3, y=20, hp=1))
        obs["events"] = [{"type": "damaged", "by": by, "weapon": "gun", "amount": 45} for by in (1, 2)]
        decision = Engagement(CONFIG).select(obs, threats(obs), safe_finish=True)
        self.assertEqual(decision.mode, "DEFEND")
        self.assertEqual(decision.target["id"], 2)

    def test_missing_or_occluded_actor_is_not_a_firing_target(self):
        controller = Engagement(CONFIG)
        obs = observation(actor())
        obs["events"] = [{"type": "damaged", "by": 1, "weapon": "gun", "amount": 45}]
        candidates = threats(obs)
        candidates[0]["los"] = False
        self.assertFalse(controller.select(obs, candidates).allow_fire)
        later = advance(obs, 0.1)
        later["mechs"] = []
        candidates[0]["los"] = True
        self.assertFalse(controller.select(later, candidates).allow_fire)

    def test_missing_or_full_hp_never_qualifies_as_elective_finish(self):
        for missing in (True, False):
            target = actor(hp=1400)
            if missing:
                target.pop("hp")
            obs = observation(target)
            obs["beams"] = [hit_beam(target)]
            self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)

    def test_beam_at_npc_crate_or_far_away_is_not_a_mech_fight(self):
        target = actor(hp=50)
        for endpoint in ([50, 30, 1.75], [50, 30, 1.2], [100, 10, 4.5]):
            obs = observation(target, actor(102, x=50, y=30, kind="npc", hp=350, max_hp=350))
            obs["crates"] = [{"id": 1001, "pos": [50, 30, 0], "hp": 300}]
            obs["beams"] = [{"by": 2, "kind": "laser", "age": 0.1, "path": [[50, 60, 7], endpoint]}]
            self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)

    def test_ownerless_projectiles_sounds_hp_loss_and_own_hits_are_not_evidence(self):
        controller = Engagement(CONFIG)
        obs = observation(actor(hp=300))
        controller.select(obs, threats(obs), safe_finish=True)
        later = advance(obs, 0.1)
        later["mechs"][0]["hp"] = 50
        later["events"] = [{"type": "hit", "target": 1, "weapon": "gun", "amount": 45}]
        later["projectiles"] = [{"id": 90, "kind": "gun", "pos": [95, 0, 4.5], "vel": [252, 0, 0]}]
        later["sounds"] = [{"kind": "gun", "bearing": 0, "dist": "near", "age": 0.05}]
        self.assertFalse(controller.select(later, threats(later), safe_finish=True).allow_fire)

    def test_own_beam_and_non_beam_weapon_cannot_create_fight(self):
        for by, kind in ((0, "laser"), (102, "laser"), (2, "gun")):
            obs = observation(actor())
            obs["beams"] = [hit_beam(obs["mechs"][0], by=by, kind=kind)]
            self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)

    def test_repeated_beam_uses_emission_time_and_expires(self):
        controller = Engagement(CONFIG)
        obs = observation(actor(hp=20))
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        self.assertTrue(controller.select(obs, threats(obs), safe_finish=True).allow_fire)
        duplicate = advance(obs, 0.5, clear=False)
        duplicate["beams"][0]["age"] = 0.6
        controller.select(duplicate, threats(duplicate), safe_finish=True)
        self.assertAlmostEqual(controller.participants[1].at, 4.9)
        later = advance(obs, 2.1)
        later["events"] = [{"type": "hit", "target": 1, "amount": 45, "weapon": "gun"}]
        self.assertFalse(controller.select(later, threats(later), safe_finish=True).allow_fire)

    def test_kill_event_clears_defense_and_participation(self):
        controller = Engagement(CONFIG)
        obs = observation(actor())
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        obs["events"] = [{"type": "damaged", "by": 1, "weapon": "gun", "amount": 45}]
        controller.select(obs, threats(obs))
        later = advance(obs, 0.1)
        later["events"] = [{"type": "kill", "target": 1}]
        self.assertFalse(controller.select(later, threats(later), safe_finish=True).allow_fire)
        self.assertNotIn(1, controller.attackers)
        self.assertNotIn(1, controller.participants)

    def test_quiet_recovery_vetoes_elective_finish(self):
        obs = observation(actor(hp=1))
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        decision = Engagement(CONFIG).select(obs, threats(obs), safe_finish=True, recovering=True)
        self.assertFalse(decision.allow_fire)
        self.assertEqual(decision.reason, "quiet_recovery")

    def test_low_hp_behind_geometry_is_skipped_for_reachable_participant(self):
        a, b = actor(1, x=80, hp=30), actor(3, x=110, y=20, hp=90)
        obs = observation(a, b)
        obs["beams"] = [hit_beam(a), hit_beam(b)]
        controller = Engagement(CONFIG, lambda start, end: end[0] > 90)
        decision = controller.select(obs, threats(obs), safe_finish=True)
        self.assertEqual(decision.target["id"], 3)

    def test_range_readiness_and_ammunition_limit_finish(self):
        for distance, changes in ((400, {}), (100, {"ammo": 0}),
                                  (100, {"ammo": 0, "reload": 2.4}),
                                  (100, {"cooldown": 2.1})):
            with self.subTest(distance=distance, changes=changes):
                obs = observation(actor(x=distance, hp=20), weapons=[weapon(**changes), None])
                obs["beams"] = [hit_beam(obs["mechs"][0])]
                self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)

    def test_budget_includes_gun_flight_and_aim_slew(self):
        obs = observation(actor(x=200, hp=20))
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True, finish_budget_s=0.5).allow_fire)
        obs["self"]["aim"] = [math.pi, 0]
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True, finish_budget_s=1.2).allow_fire)
        self.assertTrue(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True, finish_budget_s=2).allow_fire)

    def test_laser_estimate_respects_armor_cubes_current_charge_and_cooldown(self):
        obs = observation(actor(hp=300), weapons=[weapon("laser"), None])
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)
        obs["self"]["cubes"] = 10
        obs["self"]["stats"].update(muzzle_height=10.5, eye_height=12)
        fresh = Engagement(CONFIG).select(obs, threats(obs), safe_finish=True)
        self.assertTrue(fresh.allow_fire)
        obs["self"]["weapons"][0]["charge"] = 0.75
        charged = Engagement(CONFIG).select(obs, threats(obs), safe_finish=True)
        self.assertLess(charged.finish_eta, fresh.finish_eta)
        obs["self"]["weapons"][0].update(charge=0, cooldown=2)
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)

    def test_lightning_finish_retains_energy_and_rejects_closer_interceptor(self):
        obs = observation(actor(x=30, hp=30), weapons=[weapon("lightning"), None])
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        self.assertTrue(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)
        obs["self"]["energy"] = 10
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)
        obs["self"]["energy"] = 100
        obs["crates"] = [{"id": 1001, "pos": [10, 0, 0], "hp": 300}]
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)

    def test_two_weapons_do_not_sum_incompatible_optimistic_damage(self):
        obs = observation(actor(hp=400), weapons=[weapon(), weapon("laser")])
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)

    def test_unknown_health_can_be_defended_against_but_not_finished(self):
        target = actor()
        target.pop("hp")
        obs = observation(target)
        obs["events"] = [{"type": "damaged", "by": 1, "weapon": "gun", "amount": 45}]
        self.assertTrue(Engagement(CONFIG).select(obs, threats(obs), recovering=True).allow_fire)

    def test_no_usable_weapon_path_does_not_authorize_a_remote_attacker(self):
        obs = observation(actor(x=400))
        obs["events"] = [{"type": "damaged", "by": 1, "weapon": "gun", "amount": 45}]
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs)).allow_fire)

    def test_input_and_decision_are_not_mutated(self):
        obs = observation(actor())
        original = copy.deepcopy(obs)
        decision = Engagement(CONFIG).select(obs, threats(obs))
        self.assertEqual(obs, original)
        with self.assertRaises(FrozenInstanceError):
            decision.mode = "DEFEND"

    def test_higher_hp_attackers_do_not_trigger_redundant_profiles(self):
        obs = observation(*(actor(i, x=100 * math.cos((i - 1) * math.tau / 15),
                                  y=100 * math.sin((i - 1) * math.tau / 15), hp=100 + i)
                            for i in range(1, 16)), weapons=[weapon(), weapon("mortar")])
        obs["events"] = [{"type": "damaged", "by": i, "weapon": "gun", "amount": 45} for i in range(1, 16)]
        controller = Engagement(CONFIG)
        calls = []
        original = controller._weapon_profile
        def profile(*args):
            calls.append(args[1]["id"])
            return original(*args)
        controller._weapon_profile = profile
        def no_arc(*args):
            self.fail("An already-usable gun makes a defensive mortar arc unnecessary")
        controller.model._mortar_solution = no_arc
        self.assertEqual(controller.select(obs, threats(obs)).target["id"], 1)
        self.assertEqual(calls, [1])

    def test_unsafe_finish_rejects_before_expensive_weapon_geometry(self):
        obs = observation(actor())
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        controller = Engagement(CONFIG)
        def no_profile(*args):
            self.fail("Unsafe finish must be rejected before computing weapon paths")
        controller._weapon_profile = no_profile
        self.assertFalse(controller.select(obs, threats(obs), safe_finish=lambda target: False).allow_fire)

    def test_lightning_preserves_finish_escape_reserve_without_blocking_defense(self):
        obs = observation(actor(x=30, hp=30), weapons=[weapon("lightning"), None])
        obs["self"]["energy"] = 36
        obs["beams"] = [hit_beam(obs["mechs"][0])]
        self.assertFalse(Engagement(CONFIG).select(obs, threats(obs), safe_finish=True).allow_fire)
        obs["events"] = [{"type": "damaged", "by": 1, "weapon": "gun", "amount": 45}]
        self.assertEqual(Engagement(CONFIG).select(obs, threats(obs)).mode, "DEFEND")

    def test_protected_interceptor_does_not_starve_another_finish(self):
        blocked, reachable, quiet = actor(1, hp=30), actor(3, x=90, y=40, hp=60), actor(4, x=50, hp=1400)
        obs = observation(blocked, reachable, quiet)
        obs["beams"] = [hit_beam(blocked), hit_beam(reachable)]
        decision = Engagement(CONFIG).select(obs, threats(obs), safe_finish=True)
        self.assertEqual(decision.mode, "FINISH")
        self.assertEqual(decision.target["id"], 3)


if __name__ == "__main__":
    unittest.main()
