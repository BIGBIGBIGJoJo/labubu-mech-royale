"""Permission for reactive defense and short, observed third-party finishes.

This module never emits weapon commands. Combat remains authoritative for actual
aim, readiness, shot paths, and shared-aim scheduling. Ownerless projectiles,
sounds, proximity, and HP loss alone never establish an attacker or a fight.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time

from combat import Combat, angle_delta, direction


@dataclass(frozen=True)
class Decision:
    mode: str
    target: dict | None
    allow_fire: bool
    reason: str
    confidence: str = "none"
    evidence_age: float | None = None
    finish_eta: float | None = None
    finish_budget_s: float = 0.0
    exclusions: tuple = ()
    authorized_ids: frozenset = frozenset()

    @property
    def finish_deadline(self):
        return None

    @property
    def entry_evidence_at(self):
        return None


@dataclass(frozen=True)
class CommittedDecision(Decision):
    finish_deadline: float | None = None
    entry_evidence_at: float | None = None


@dataclass(frozen=True)
class AggressiveDecision(Decision):
    finish_weapon: str | None = None


@dataclass(frozen=True)
class ExperimentalPolicy:
    """Explicit opt-in; this prototype is never selected by default."""
    continuation_seconds: float = 8.0
    facing_radians: float = 0.25
    approach_mps: float = 1.5
    fresh_attacker_collateral: bool = True
    direct_reachability: bool = True
    finish_commitment: bool = False

    def __post_init__(self):
        if not (math.isfinite(self.continuation_seconds) and 3 <= self.continuation_seconds <= 8):
            raise ValueError("continuation must be between three and eight seconds")
        if not (math.isfinite(self.facing_radians) and 0 <= self.facing_radians <= math.pi):
            raise ValueError("invalid facing threshold")
        if not (math.isfinite(self.approach_mps) and self.approach_mps >= 0):
            raise ValueError("invalid approach threshold")


@dataclass(frozen=True)
class Evidence:
    at: float
    kind: str
    peer: int | None = None
    source: int | None = None


@dataclass(frozen=True)
class FinishCommitment:
    target_id: int
    deadline: float
    evidence: Evidence
    hp: float
    used_evidence: tuple


class Engagement:
    # Policy settings, not protocol constants. No elapsed-match opening gate.
    DEFENSE_MEMORY = 3.0
    FIGHT_MEMORY = 2.0
    MAX_FINISH_BUDGET = 2.0
    FINISH_MARGIN = 0.1

    def __init__(self, config, line_of_fire=None, experimental_policy=None):
        self.config = config
        self.model = Combat(config, line_of_fire)
        self.attackers = {}
        self.participants = {}
        self._last_frame = None
        self._last_time = -1.0
        self.experimental = experimental_policy
        self.finish_commitment = None
        self.consumed_evidence = {}
        self.consumed_beams = {}

    @staticmethod
    def _known_hp(actor):
        hp = actor.get("hp")
        return isinstance(hp, (int, float)) and math.isfinite(hp) and hp > 0

    @staticmethod
    def _mech_id(actor_id):
        # The protocol assigns mechs 0..15; NPCs are 100+.
        return isinstance(actor_id, int) and not isinstance(actor_id, bool) and 0 <= actor_id < 16

    def _body_intersection(self, a, b, actor, age=0.0):
        """Intersect a beam segment with a velocity-rewound body cylinder."""
        radius, height = self.model._body(actor)
        velocity = actor.get("vel", (0, 0, 0))
        feet = [actor["pos"][i] - velocity[i] * age for i in range(3)]
        dx, dy, dz = (b[i] - a[i] for i in range(3))
        lo, hi = 0.0, 1.0
        if abs(dz) < 1e-10:
            if not feet[2] - 0.2 <= a[2] <= feet[2] + height + 0.2:
                return False
        else:
            enter, leave = sorted(((feet[2] - 0.2 - a[2]) / dz,
                                   (feet[2] + height + 0.2 - a[2]) / dz))
            lo, hi = max(lo, enter), min(hi, leave)
            if lo > hi:
                return False
        den = dx * dx + dy * dy
        fraction = max(lo, min(hi, ((feet[0] - a[0]) * dx + (feet[1] - a[1]) * dy) / den)) if den > 1e-12 else lo
        return ((a[0] + dx * fraction - feet[0]) ** 2
                + (a[1] + dy * fraction - feet[1]) ** 2 <= (radius + 0.2) ** 2)

    @staticmethod
    def _remember(memory, actor_id, evidence):
        prior = memory.get(actor_id)
        if prior is None or evidence.at > prior.at + 1e-8:
            memory[actor_id] = evidence

    def update(self, obs):
        now = float(obs.get("t", 0.0))
        frame = (obs.get("tick"), now)
        if frame == self._last_frame:
            return
        if now < self._last_time:
            self.attackers.clear()
            self.participants.clear()
            self.finish_commitment = None
            self.consumed_evidence.clear()
            self.consumed_beams.clear()
        self._last_frame, self._last_time = frame, now
        me = obs["self"]
        own_id = me["id"]
        killed = {event.get("target") for event in obs.get("events", ()) if event.get("type") == "kill"}
        actors = [a for a in obs.get("mechs", ()) if a.get("kind") == "mech"
                  and a.get("id") != own_id and a.get("id") not in killed and a.get("hp", 1) > 0]
        for event in obs.get("events", ()):
            by = event.get("by")
            if (event.get("type") == "damaged" and event.get("weapon") != "zone"
                    and self._mech_id(by) and by != own_id and by not in killed):
                self._remember(self.attackers, by, Evidence(now, "attributed_attack"))
        for beam in obs.get("beams", ())[:32]:
            by = beam.get("by")
            if (beam.get("kind") not in ("laser", "lightning")
                    or not self._mech_id(by) or by == own_id or by in killed):
                continue
            age = max(0.0, float(beam.get("age", 0.0)))
            if not math.isfinite(age) or age > self.FIGHT_MEMORY:
                continue
            path = beam.get("path", ())[:16]
            if len(path) < 2:
                continue
            when = now - age
            segments = list(zip(path, path[1:]))
            if any(self._body_intersection(a, b, me, age) for a, b in segments):
                self._remember(self.attackers, by, Evidence(when, "attributed_attack"))
            # Visibility of the shooter is not required: beam.by is explicit,
            # and the protocol can expose just a distant beam endpoint.
            for actor in actors:
                if actor["id"] == by:
                    continue
                if any(self._body_intersection(a, b, actor, age) for a, b in segments):
                    self._remember(self.participants, actor["id"], Evidence(when, "attributed_beam", by, by))
                    self._remember(self.participants, by, Evidence(when, "attributed_beam", actor["id"], by))
        retention = self.experimental.continuation_seconds if self.experimental else self.DEFENSE_MEMORY
        self.attackers = {key: value for key, value in self.attackers.items()
                          if key not in killed and now - value.at < retention}
        self.participants = {key: value for key, value in self.participants.items()
                             if key not in killed and now - value.at < self.FIGHT_MEMORY}

    def _round_time(self, seconds, quantum=None):
        quantum = self.model.sim_dt if quantum is None else quantum
        return max(0.0, math.ceil((seconds - 1e-9) / quantum) * quantum)

    def _aim_delay(self, me, aim, own):
        yaw = abs(angle_delta(aim[0], me.get("aim", (0, 0))[0]))
        pitch = abs(aim[1] - me.get("aim", (0, 0))[1])
        return max(yaw / max(1e-8, own.get("turn_rate", 4)),
                   pitch / max(1e-8, own.get("pitch_rate", 3)))

    def _solution(self, me, actor, kind, stats, when, own):
        _, height = self.model._body(actor)
        velocity = actor.get("vel", (0, 0, 0))
        center = [actor["pos"][i] + velocity[i] * when for i in range(3)]
        center[2] += height * 0.5
        # Finish eligibility is from the current firing position, without a
        # speculative chase. Include only the next held action's own motion.
        own_motion = min(self.model.action_dt, when)
        origin = [me["pos"][0] + me.get("vel", (0, 0, 0))[0] * own_motion,
                  me["pos"][1] + me.get("vel", (0, 0, 0))[1] * own_motion,
                  me["pos"][2] + own["muzzle_height"]]
        limits = (own.get("min_pitch", -0.7), own.get("max_pitch", 1.3))
        if kind == "mortar":
            origin[2] = me["pos"][2] + own["height"] + 0.5
            return self.model._mortar_solution(stats, origin, center, velocity, me, own, limits)
        return self.model._direct_solution(kind, stats, origin, center, velocity,
                                          own["radius"] + 0.5, limits, height)

    def _lightning_first_target(self, obs, actor, sol, stats, own):
        # A closer crate/NPC/mech can intercept lightning. Do not count its
        # weaker/uncertain chains as a guaranteed finishing hit on our target.
        origin = sol["origin"]
        cone = math.radians(stats.get("cone_deg", 30))
        others = list(obs.get("mechs", ())) + [{**c, "kind": "crate"} for c in obs.get("crates", ())]
        for other in others:
            if other.get("id") == actor["id"] or other.get("hp", 1) <= 0:
                continue
            _, height = self.model._body(other)
            center = [other["pos"][0], other["pos"][1], other["pos"][2] + height * 0.5]
            distance = math.dist(origin, center)
            yaw = math.atan2(center[1] - origin[1], center[0] - origin[0])
            if (distance < sol["distance"] - 1e-6 and distance <= stats.get("range", 45)
                    and abs(angle_delta(yaw, sol["aim"][0])) <= cone
                    and self.model._clear(origin, center)):
                return False
        return True

    def _fresh_authorized(self, obs, recovering):
        if not self.experimental or not self.experimental.fresh_attacker_collateral:
            return frozenset()
        window = self.DEFENSE_MEMORY
        if recovering:
            window = min(window, max(0.0, self.model._self_stats(obs["self"]).get("regen_delay", 5)))
        return frozenset(a["id"] for a in obs.get("mechs", ())
                         if a.get("kind") == "mech" and a.get("hp", 1) > 0
                         and a["id"] in self.attackers
                         and obs["t"] - self.attackers[a["id"]].at < window)

    def _continues_toward_us(self, obs, actor):
        """Weak corroboration only; it cannot create or refresh attribution."""
        policy = self.experimental
        if policy is None:
            return False
        dx = obs["self"]["pos"][0] - actor["pos"][0]
        dy = obs["self"]["pos"][1] - actor["pos"][1]
        distance = math.hypot(dx, dy)
        facing = abs(angle_delta(actor.get("aim", (0, 0))[0], math.atan2(dy, dx))) <= policy.facing_radians + 1e-9
        velocity = actor.get("vel", (0, 0, 0))
        # Enemy motion toward us, not relative closing caused by our own chase.
        approach = (velocity[0] * dx + velocity[1] * dy) / max(1e-8, distance)
        return facing or approach > policy.approach_mps

    def _direct_reachable(self, obs, actor, kind, stats, when, sol):
        """Permission to hit an interceptor does not make a farther shot hit.

        Gun and non-piercing laser estimates require the selected actor to be
        the first observed body. A laser can cross only its configured number
        of earlier bodies. Quiet-body permission is checked separately.
        """
        if not self.experimental or not self.experimental.direct_reachability or kind not in ("gun", "laser"):
            return True
        moving = kind == "gun"
        speed = stats.get("speed", 252) if moving else 1.0
        velocity = [v * speed for v in direction(sol["aim"])]
        duration = stats.get("range", 230 if moving else 280) / max(speed, 1e-8)
        padding = self.config.get("projectile", {}).get("gun_radius", 0.3) if moving else 0.0
        selected_hit = self.model._body_hit_time(sol["origin"], velocity, 0, duration, actor, when, padding, moving)
        if selected_hit is None:
            return False
        budget = max(0, int(stats.get("pierce", 0))) if kind == "laser" else 0
        entities = list(obs.get("mechs", ())) + [{**crate, "kind": "crate"} for crate in obs.get("crates", ())]
        for other in entities:
            if other.get("id") == actor["id"] or other.get("hp", 1) <= 0:
                continue
            hit = self.model._body_hit_time(sol["origin"], velocity, 0, selected_hit, other, when, padding, moving)
            if hit is not None and hit < selected_hit - 1e-6:
                budget -= 1
                if budget < 0:
                    return False
        return True

    def _collateral_clear(self, obs, actor, kind, stats, when, own, sol, authorized_ids=frozenset()):
        protected = {a["id"] for a in obs.get("mechs", ())
                     if a.get("kind") == "mech" and a["id"] != actor["id"] and a["id"] not in authorized_ids}
        me = obs["self"]
        if kind == "mortar":
            muzzle = sol["base_origin"]
        else:
            movement = min(self.model.action_dt, when)
            velocity = me.get("vel", (0, 0, 0))
            muzzle = [me["pos"][0] + velocity[0] * movement,
                      me["pos"][1] + velocity[1] * movement,
                      me["pos"][2] + own["muzzle_height"]]
        return self.model.collateral_clear(obs, actor, kind, stats, muzzle, sol["aim"], when, sol, protected)

    def _weapon_profile(self, obs, actor, remaining_defense=None, authorized_ids=frozenset()):
        """Usable wait and conditional single-weapon TTK; never sum shared aim."""
        me = obs["self"]
        own = self.model._self_stats(me)
        hp = actor.get("hp") if self._known_hp(actor) else None
        armor = actor.get("armor", actor.get("stats", {}).get("armor", self.model.max_enemy_armor))
        if not isinstance(armor, (int, float)) or not math.isfinite(armor):
            armor = self.model.max_enemy_armor
        armor = max(0.0, min(0.95, armor))
        cubes = self.config.get("cubes", {})
        multiplier = (1 + cubes.get("damage_per_cube", 0.04) * min(me.get("cubes", 0), cubes.get("stat_cap", 10))) * (1 - armor)
        waits, finishes = [], []
        for weapon in me.get("weapons", ())[:2]:
            if not weapon or weapon.get("kind") not in ("gun", "laser", "lightning", "mortar"):
                continue
            kind = weapon["kind"]
            # Mortar never contributes to the short finish estimate. Its arc
            # is needed for defense only if no already-tested weapon can fire
            # during the remaining authorization window.
            if kind == "mortar" and (remaining_defense is None
                    or any(wait < remaining_defense for wait in waits)):
                continue
            stats = self.model._stats(weapon)
            ready = max(0.0, weapon.get("cooldown", 0))
            ammo = max(0, int(weapon.get("ammo", stats.get("mag", 12))))
            if kind == "gun":
                reload = max(0.0, weapon.get("reload", 0))
                ready = max(ready, reload)
                if reload > 0:
                    ammo = max(1, int(stats.get("mag", 12)))
                elif ammo == 0:
                    ready = max(ready, stats.get("reload", 2.4))
                    ammo = max(1, int(stats.get("mag", 12)))
            elif kind == "laser" and weapon.get("charge", 0) > 0:
                ready = 0.0
            elif kind == "lightning" and me.get("energy", 0) < stats.get("energy", 3) + 8:
                continue
            first = self._round_time(max(self.model.sim_dt, ready))
            if first > self.DEFENSE_MEMORY:
                continue
            sol = self._solution(me, actor, kind, stats, first, own)
            if not sol or not sol["clear"]:
                continue
            if not self._direct_reachable(obs, actor, kind, stats, first, sol):
                continue
            if not self._collateral_clear(obs, actor, kind, stats, first, own, sol, authorized_ids):
                continue
            first = self._round_time(max(first, self._aim_delay(me, sol["aim"], own)))
            if first > self.DEFENSE_MEMORY:
                continue
            if kind == "lightning" and not self._lightning_first_target(obs, actor, sol, stats, own):
                continue
            waits.append(first)
            if hp is None or kind == "mortar":
                continue
            damage = max(0.0, stats.get("damage", 0) * multiplier)
            if damage <= 0:
                continue
            if kind == "laser":
                full = stats.get("charge", 0.75)
                maximum = self.model.laser_damage_bound(me, stats, actor, full)
                # A second beam needs charge + cooldown beyond the entry budget.
                if maximum + 1e-6 < hp:
                    continue
                fraction = stats.get("min_frac", 0.35)
                needed = max(stats.get("min_charge", 0.15), full * (hp / maximum - fraction) / max(1e-8, 1 - fraction))
                needed = min(full, needed)
                charge_left = max(0.0, needed - weapon.get("charge", 0))
                finish = self._round_time(ready + charge_left, self.model.action_dt) + self.model.sim_dt
                finish = max(first, finish)
            else:
                count = max(1, int(math.ceil(hp / damage - 1e-9)))
                if count > 128:
                    continue
                if kind == "lightning":
                    escape_reserve = max(35.0, own.get("boost_drain", 17) * 1.25 + 12)
                    if count * stats.get("energy", 3) + escape_reserve > me.get("energy", 0):
                        continue  # Do not spend projected future escape energy.
                    finish = first + (count - 1) * self._round_time(stats.get("cooldown", 0.25))
                else:
                    finish = first
                    remaining = ammo
                    for _ in range(1, count):
                        remaining -= 1
                        if remaining <= 0:
                            finish += self._round_time(stats.get("reload", 2.4))
                            remaining = max(1, int(stats.get("mag", 12)))
                        else:
                            finish += self._round_time(stats.get("cooldown", 0.24))
                if kind == "gun":
                    finish += sol["flight"]
            if finish > self.MAX_FINISH_BUDGET:
                continue
            # Target motion cannot grant a shot that leaves our current range
            # or goes behind cover before the modeled finishing attack.
            final = self._solution(me, actor, kind, stats, finish, own)
            if (final and final["clear"] and self._direct_reachable(obs, actor, kind, stats, finish, final)
                    and self._collateral_clear(obs, actor, kind, stats, finish, own, final, authorized_ids)):
                finishes.append(finish)
        return (min(waits) if waits else None, min(finishes) if finishes else None)

    def _cancel_finish_commitment(self):
        commitment = self.finish_commitment
        if commitment is None:
            return
        for actor_id, used in commitment.used_evidence:
            # Consume any newer proof already observed for the same selected
            # participants too; a repeated observation cannot restart a lease.
            current = self.participants.get(actor_id)
            for evidence in (used, current):
                if evidence is None:
                    continue
                self.consumed_evidence[actor_id] = max(evidence.at, self.consumed_evidence.get(actor_id, -math.inf))
                if evidence.source is not None:
                    # The other participant of this same beam cannot borrow it
                    # to start another commitment after cancellation/expiry.
                    self.consumed_beams[evidence.source] = max(evidence.at, self.consumed_beams.get(evidence.source, -math.inf))
        self.finish_commitment = None

    def _select_finish_commitment(self, obs, usable, safe_finish, budget, fresh_authorized, profiles, exclusions):
        """Entry needs fresh proof; completion has its own fixed safety budget."""
        now = float(obs["t"])
        commitment = self.finish_commitment
        deadline = commitment.deadline if commitment else now + budget
        effective = max(0.0, min(budget, deadline - now) - self.FINISH_MARGIN)
        by_id = {actor["id"]: actor for actor in usable}

        def observe(reason):
            return Decision("OBSERVE", None, False, reason, finish_budget_s=effective,
                            exclusions=tuple(exclusions), authorized_ids=fresh_authorized)

        def eligibility(actor):
            maximum = actor.get("max_hp")
            if (not self._known_hp(actor) or not isinstance(maximum, (int, float))
                    or not math.isfinite(maximum) or actor["hp"] >= maximum):
                return None, "not_observably_weakened"
            permitted = bool(safe_finish(actor)) if callable(safe_finish) else bool(safe_finish)
            if not permitted:
                return None, "unsafe_finish"
            profile = profiles.get(actor["id"])
            if profile is None:
                profile = profiles[actor["id"]] = self._weapon_profile(obs, actor, authorized_ids=fresh_authorized)
            eta = profile[1]
            if eta is None or eta > effective:
                return None, "finish_exceeds_remaining_budget"
            return eta, None

        choices = []
        if commitment is not None:
            current = by_id.get(commitment.target_id)
            if effective <= 0:
                reason = "finish_deadline_exhausted"
            elif current is None:
                reason = "committed_target_not_current_or_visible"
            elif not self._known_hp(current) or current["hp"] > commitment.hp + 1e-6:
                reason = "committed_target_health_increased_or_unknown"
            else:
                eta, reason = eligibility(current)
                if reason is None:
                    choices.append((current["hp"], eta, current["id"], current, commitment.evidence))
            if reason is not None:
                exclusions.append((commitment.target_id, reason))
                self._cancel_finish_commitment()
                # A canceled current target cannot be exchanged for a fresh
                # exposure window in the same decision.
                return observe(reason)
        elif effective <= 0:
            return observe("finish_budget_unavailable")

        for actor in usable:
            if commitment is not None and actor["id"] == commitment.target_id:
                continue
            if choices and self._known_hp(actor) and actor["hp"] > min(choice[0] for choice in choices):
                break
            evidence = self.participants.get(actor["id"])
            if evidence is None or now - evidence.at >= self.FIGHT_MEMORY:
                exclusions.append((actor["id"], "no_fresh_external_fight"))
                continue
            consumed = max(self.consumed_evidence.get(actor["id"], -math.inf),
                           self.consumed_beams.get(evidence.source, -math.inf))
            if evidence.at <= consumed + 1e-8:
                exclusions.append((actor["id"], "consumed_fight_evidence"))
                continue
            eta, reason = eligibility(actor)
            if reason is not None:
                exclusions.append((actor["id"], reason))
                continue
            choices.append((actor["hp"], eta, actor["id"], actor, evidence))
        if not choices:
            return observe("no_authorized_mech_target")
        _, eta, _, actor, evidence = min(choices, key=lambda choice: choice[:3])
        used = dict(commitment.used_evidence) if commitment else {}
        if actor["id"] not in used or evidence.at > used[actor["id"]].at:
            used[actor["id"]] = evidence
        self.finish_commitment = FinishCommitment(actor["id"], deadline, evidence, actor["hp"], tuple(sorted(used.items())))
        reason = "continue_fixed_finish" if commitment else "enter_fixed_finish"
        return CommittedDecision("FINISH", actor, True, reason, evidence.kind,
                                 max(0.0, now - evidence.at), eta, effective, tuple(exclusions),
                                 fresh_authorized | {actor["id"]}, deadline, evidence.at)

    def select(self, obs, candidates, *, safe_finish=False, finish_budget_s=2.0, recovering=False):
        self.update(obs)
        now = float(obs.get("t", 0.0))
        current = {actor["id"]: actor for actor in obs.get("mechs", ())
                   if actor.get("kind") == "mech" and actor.get("hp", 1) > 0}
        usable = []
        exclusions = []
        for item in candidates[:16]:
            actor_id = item["actor"].get("id")
            actor = current.get(actor_id)
            if actor is None:
                exclusions.append((actor_id, "not_current_mech"))
            elif not item.get("los", False):
                exclusions.append((actor_id, "no_visible_path"))
            else:
                usable.append(actor)
        usable.sort(key=lambda a: (a.get("hp") if self._known_hp(a) else float("inf"), a["id"]))
        budget = max(0.0, min(self.MAX_FINISH_BUDGET, float(finish_budget_s)))
        profiles = {}
        defensive = []
        defense_window = self.DEFENSE_MEMORY
        if recovering:
            defense_window = min(defense_window, max(0.0, self.model._self_stats(obs["self"]).get("regen_delay", 5.0)))
        fresh_authorized = self._fresh_authorized(obs, recovering)
        for actor in usable:
            hp_key = actor.get("hp") if self._known_hp(actor) else float("inf")
            if defensive and hp_key > defensive[0][0]:
                break
            evidence = self.attackers.get(actor["id"])
            if evidence is None:
                continue
            age = max(0.0, now - evidence.at)
            window = defense_window
            if (not recovering and self.experimental and self._continues_toward_us(obs, actor)):
                # Visibility was required above. No weak signal changes at.
                window = self.experimental.continuation_seconds
            if window - age <= self.model.sim_dt:
                exclusions.append((actor["id"], "defense_window_ending"))
                continue
            profile = profiles[actor["id"]] = self._weapon_profile(obs, actor, window - age, fresh_authorized)
            if profile[0] is None or profile[0] >= window - age:
                exclusions.append((actor["id"], "no_ready_defensive_weapon"))
                continue
            defensive.append((actor.get("hp") if self._known_hp(actor) else float("inf"),
                              profile[1] if profile[1] is not None else float("inf"), actor["id"], actor, evidence))
        if defensive:
            _, _, _, actor, evidence = min(defensive, key=lambda row: row[:3])
            age = max(0.0, now - evidence.at)
            reason = "continuing_attributed_attack" if age >= self.DEFENSE_MEMORY else "recent_attributed_attack"
            self._cancel_finish_commitment()
            return Decision("DEFEND", actor, True, reason, evidence.kind,
                            age, profiles[actor["id"]][1], budget, tuple(exclusions),
                            fresh_authorized | {actor["id"]})
        if recovering:
            self._cancel_finish_commitment()
            return Decision("OBSERVE", None, False, "quiet_recovery", exclusions=tuple(exclusions),
                            authorized_ids=fresh_authorized)
        if self.experimental and self.experimental.finish_commitment:
            return self._select_finish_commitment(obs, usable, safe_finish, budget,
                                                  fresh_authorized, profiles, exclusions)
        finishes = []
        for actor in usable:
            if finishes and self._known_hp(actor) and actor["hp"] > finishes[0][0]:
                break
            evidence = self.participants.get(actor["id"])
            if evidence is None:
                exclusions.append((actor["id"], "no_fresh_external_fight"))
                continue
            maximum = actor.get("max_hp")
            if (not self._known_hp(actor) or not isinstance(maximum, (int, float))
                    or not math.isfinite(maximum) or actor["hp"] >= maximum):
                exclusions.append((actor["id"], "not_observably_weakened"))
                continue
            age = max(0.0, now - evidence.at)
            effective = max(0.0, min(budget, self.FIGHT_MEMORY - age) - self.FINISH_MARGIN)
            permitted = bool(safe_finish(actor)) if callable(safe_finish) else bool(safe_finish)
            if not permitted:
                exclusions.append((actor["id"], "unsafe_finish"))
                continue
            profile = profiles.get(actor["id"])
            if profile is None:
                profile = profiles[actor["id"]] = self._weapon_profile(obs, actor, authorized_ids=fresh_authorized)
            eta = profile[1]
            if eta is None or eta > effective:
                exclusions.append((actor["id"], "finish_exceeds_budget"))
                continue
            finishes.append((actor["hp"], eta, actor["id"], actor, evidence, effective))
        if finishes:
            _, eta, _, actor, evidence, effective = min(finishes, key=lambda row: row[:3])
            return Decision("FINISH", actor, True, "safe_observed_finish", evidence.kind,
                            max(0.0, now - evidence.at), eta, effective, tuple(exclusions),
                            fresh_authorized | {actor["id"]})
        return Decision("OBSERVE", None, False, "no_authorized_mech_target", finish_budget_s=budget,
                        exclusions=tuple(exclusions), authorized_ids=fresh_authorized)


class AggressiveEngagement(Engagement):
    """Proactive target selection; movement owns recovery and pursuit decisions.

    All observed hostiles may take damage. Selection still distinguishes that
    permission from physically reaching the selected body. A short kill ETA is
    a conservative <=2s estimate, never a promise about an entire moving duel.
    """
    SCORING_SECONDS = .006
    MAX_SHORT_PROFILES = 6
    MAX_MORTAR_PROFILES = 2

    def __init__(self, config, line_of_fire=None):
        super().__init__(config, line_of_fire, ExperimentalPolicy(direct_reachability=True))
        self.target_id = None
        self._attack_at = {}
        self.last_scoring = {}
        self._world_line_of_fire = line_of_fire
        self._geometry_deadline = math.inf
        self._geometry_timeouts = 0
        self._solution_cache = None
        self.model.line_of_fire = self._budgeted_clear

    def _budgeted_clear(self, start, end):
        # A mortar arc contains many rays. Cooperate between those rays rather
        # than discovering an expired budget after the entire arc completes.
        if time.perf_counter() >= self._geometry_deadline:
            self._geometry_timeouts += 1
            return False
        return self._world_line_of_fire is None or bool(self._world_line_of_fire(start, end))

    def _solution(self, me, actor, kind, stats, when, own):
        # Seed and short proof often ask exactly the same first-shot geometry.
        # Cache only inside this observation, with weapon parameters included.
        if self._solution_cache is None:
            return super()._solution(me, actor, kind, stats, when, own)
        key = (actor["id"], kind, when, tuple(sorted(stats.items())))
        if key in self._solution_cache:
            return self._solution_cache[key]
        before = self._geometry_timeouts
        result = super()._solution(me, actor, kind, stats, when, own)
        if self._geometry_timeouts == before:
            self._solution_cache[key] = result
        return result

    def _cheap_weapons(self, obs, actor, own, *, mortar=False):
        """No geometry calls: reject unavailable or clearly distant weapons."""
        me = obs["self"]
        distance = math.dist(me["pos"][:2], actor["pos"][:2])
        target_radius, _ = self.model._body(actor)
        result = []
        for weapon in me.get("weapons", ())[:2]:
            if not weapon or weapon.get("kind") not in ("gun", "laser", "lightning", "mortar"):
                continue
            kind = weapon["kind"]
            if (kind == "mortar") != mortar:
                continue
            stats = self.model._stats(weapon)
            ready = max(0.0, weapon.get("cooldown", 0))
            if kind == "gun":
                ready = max(ready, weapon.get("reload", 0))
                if weapon.get("ammo", 0) <= 0 and weapon.get("reload", 0) <= 0:
                    ready = max(ready, stats.get("reload", 2.4))
            elif kind == "laser" and weapon.get("charge", 0) > 0:
                ready = 0.0
            elif kind == "lightning" and me.get("energy", 0) < stats.get("energy", 3) + 8:
                continue
            if ready > self.DEFENSE_MEMORY:
                continue
            # Actor motion can enter range before readiness; this bound only
            # rejects distances even that most favorable motion cannot cover.
            motion = math.hypot(*actor.get("vel", (0, 0, 0))[:2]) * self.DEFENSE_MEMORY
            if kind != "mortar" and distance > stats.get("range", 0) + own["radius"] + target_radius + motion + 1:
                continue
            result.append((weapon, stats, ready))
        return result

    def _short_bound(self, obs, actor, weapons):
        """Optimistic arithmetic bound only, used to budget exact short checks."""
        if not self._known_hp(actor):
            return math.inf
        me, hp = obs["self"], actor["hp"]
        cubes = self.config.get("cubes", {})
        scale = 1 + cubes.get("damage_per_cube", .04) * min(me.get("cubes", 0), cubes.get("stat_cap", 10))
        best = math.inf
        for weapon, stats, ready in weapons:
            kind = weapon["kind"]
            if kind == "laser":
                full = stats.get("charge", .75)
                maximum = self.model.laser_damage_bound(me, stats, actor, full)
                if maximum + 1e-6 < hp:
                    continue
                fraction = stats.get("min_frac", .35)
                needed = max(stats.get("min_charge", .15), full * (hp / maximum - fraction) / max(1e-8, 1-fraction))
                best = min(best, max(self.model.sim_dt, ready + max(0, needed-weapon.get("charge", 0))))
            else:
                damage = stats.get("damage", 0) * scale
                if damage <= 0:
                    continue
                shots = max(1, math.ceil(hp/damage-1e-9))
                first = max(self.model.sim_dt, ready)
                cycle = self._round_time(stats.get("cooldown", .25))
                if kind == "gun":
                    magazine = max(1, int(stats.get("mag", 12)))
                    ammo = magazine if weapon.get("reload", 0) > 0 or weapon.get("ammo", 0) <= 0 else weapon["ammo"]
                    reloads = 0 if shots <= ammo else 1 + (shots-ammo-1)//magazine
                    when = first + (shots-1-reloads)*cycle + reloads*self._round_time(stats.get("reload", 2.4))
                else:
                    when = first + (shots-1)*cycle
                best = min(best, when)
        return best

    def _usable_wait(self, obs, actor, own, weapons, deadline, with_completion=False):
        best, complete = None, True
        # Readiness is a lower bound, not the actual wait: aim and shot paths
        # still need checking. Prune only when this bound cannot improve best.
        for weapon, stats, ready in sorted(weapons, key=lambda row: row[2]):
            first = self._round_time(max(self.model.sim_dt, ready))
            if best is not None and first >= best - 1e-8:
                continue
            if time.perf_counter() >= deadline:
                complete = False
                break
            timeouts_before = self._geometry_timeouts
            kind = weapon["kind"]
            sol = self._solution(obs["self"], actor, kind, stats, first, own)
            if not sol or not sol["clear"]:
                if time.perf_counter() >= deadline:
                    complete = False
                    break
                continue
            aimed = self._round_time(max(first, self._aim_delay(obs["self"], sol["aim"], own)))
            if aimed > self.DEFENSE_MEMORY:
                continue
            changed = (any(actor.get("vel", (0, 0, 0)))
                       or (first < self.model.action_dt and any(obs["self"].get("vel", (0, 0, 0))[:2])))
            if aimed > first + 1e-8 and changed:
                if time.perf_counter() >= deadline:
                    complete = False
                    break
                sol = self._solution(obs["self"], actor, kind, stats, aimed, own)
                if not sol or not sol["clear"]:
                    if time.perf_counter() >= deadline:
                        complete = False
                        break
                    continue
            if not self._direct_reachable(obs, actor, kind, stats, aimed, sol):
                continue
            if kind == "lightning" and not self._lightning_first_target(obs, actor, sol, stats, own):
                continue
            if self._geometry_timeouts != timeouts_before:
                # A timed-out LOS callback is not proof that an intervening
                # lightning body is occluded or that a later weapon is worse.
                complete = False
                break
            best = min(best, aimed) if best is not None else aimed
        return (best, complete) if with_completion else best

    def select(self, obs, candidates, recovering=False, deadline=None):
        started = time.perf_counter()
        self._solution_cache = {}
        deadline = min(started + self.SCORING_SECONDS, deadline) if deadline is not None else started + self.SCORING_SECONDS
        now, me = float(obs.get("t", 0)), obs["self"]
        if now < self._last_time:
            self.target_id = None
            self._attack_at.clear()
        self._last_time = now
        killed = {e.get("target") for e in obs.get("events", ()) if e.get("type") == "kill"}
        current = {a["id"]: a for a in obs.get("mechs", ()) if a.get("kind") == "mech"
                   and a.get("id") != me["id"] and a.get("hp", 1) > 0 and a["id"] not in killed}
        authorized = frozenset(current)
        for event in obs.get("events", ()):
            if event.get("type") == "damaged" and event.get("weapon") != "zone" and event.get("by") in current:
                self._attack_at[event["by"]] = now
        self._attack_at = {key: at for key, at in self._attack_at.items() if now-at < 3 and key not in killed}
        if self.target_id not in current:
            self.target_id = None
        own = self.model._self_stats(me)
        scored, exclusions, profiles, checked = [], [], {}, set()
        seen = set()
        for item in candidates[:16]:
            actor_id = item["actor"].get("id")
            if actor_id in seen:
                continue
            seen.add(actor_id)
            actor = current.get(actor_id)
            if actor is None or not item.get("los", False) or item.get("remembered", False):
                exclusions.append((actor_id, "not_current_visible_mech"))
                continue
            distance = math.dist(me["pos"][:2], actor["pos"][:2])
            hp = actor.get("hp", actor.get("max_hp", 1400))
            wounded = max(0, min(1, 1-hp/max(1, actor.get("max_hp", 1400))))
            score = (2 + item.get("risk", 1) + 1.6*wounded
                     + (2.5 if hp < 200 and distance < 140 else 0)
                     + (.7 if actor_id in self._attack_at else 0)
                     + (.35 if actor_id == self.target_id else 0) - .006*distance)
            weapons = self._cheap_weapons(obs, actor, own)
            scored.append((score, actor, weapons, self._short_bound(obs, actor, weapons)))
        short = []
        checks = arcs = 0
        seed_actor, seed_value, seed_complete = None, -math.inf, True
        seed = None
        seed_candidates = [row for row in scored if row[2]]
        if seed_candidates and time.perf_counter() < deadline - .003:
            # Secure a cheap physically reachable incumbent/near interceptor
            # before weak enemies consume the short-kill geometry budget.
            seed = min(seed_candidates, key=lambda row:(row[1]["id"] != self.target_id,
                       math.dist(me["pos"][:2], row[1]["pos"][:2]), -row[0]))
            seed_deadline = min(deadline-.003, started+.0025)
            self._geometry_deadline = seed_deadline
            wait, seed_complete = self._usable_wait(obs, seed[1], own, seed[2], seed_deadline, with_completion=True)
            checked.add(seed[1]["id"])
            if wait is not None:
                seed_actor, seed_value = seed[1], seed[0]-.4*wait
                if seed_complete:
                    profiles[seed_actor["id"]] = (wait, None)
        charging = any(w and w["kind"] == "laser" and w.get("charge", 0) > 0 for w in me.get("weapons", ()))
        # Keep time for the healthy interceptor/fallback after tempting weak
        # targets fail their direct paths. One map query can finish past cutoff.
        short_deadline = min(deadline - .002, started + .0035)
        self._geometry_deadline = short_deadline
        # Lower bounds prune impossible kills without map ray calls. Keep this
        # shortlist separate from the broad ranking so full-health actors live.
        for score, actor, weapons, lower in sorted(scored, key=lambda r:(
                not (charging and r[1]["id"] == self.target_id and r[3] <= self.MAX_FINISH_BUDGET),
                r[3], r[1].get("hp", math.inf), -r[0], r[1]["id"])):
            if lower > self.MAX_FINISH_BUDGET or checks >= self.MAX_SHORT_PROFILES or time.perf_counter() >= short_deadline:
                break
            if short and lower > min(row[0] for row in short) + 1e-8:
                break
            tested, waits = set(), []
            possible = sorted(((self._short_bound(obs, actor, [row]), row) for row in weapons),
                              key=lambda row:(row[0], row[1][0]["kind"]))
            for weapon_lower, row in possible:
                if (weapon_lower > self.MAX_FINISH_BUDGET or checks >= self.MAX_SHORT_PROFILES
                        or time.perf_counter() >= short_deadline):
                    break
                if short and weapon_lower > min(result[0] for result in short) + 1e-8:
                    break
                weapon, stats, ready = row
                # A reloading gun that cannot finish in time must not consume
                # the laser's short-proof budget. Never sum shared-aim damage.
                shadow = {**obs, "self": {**me, "weapons": [weapon, None]}}
                checks += 1
                timeouts_before = self._geometry_timeouts
                profile = self._weapon_profile(shadow, actor, authorized_ids=authorized)
                checked.add(actor["id"])
                if self._geometry_timeouts != timeouts_before:
                    break  # An interrupted ray is neither a kill nor a miss.
                tested.add(weapon["kind"])
                if profile[0] is not None:
                    waits.append(profile[0])
                if profile[1] is not None:
                    short.append((profile[1], actor.get("hp", math.inf), actor["id"] != self.target_id,
                                  math.dist(me["pos"][:2], actor["pos"][:2]), actor["id"], actor, weapon["kind"]))
            if actor["id"] not in profiles:
                best_wait = min(waits) if waits else None
                untested = [row for row in weapons if row[0]["kind"] not in tested]
                bound = min((self._round_time(max(self.model.sim_dt, row[2])) for row in untested), default=math.inf)
                if not untested or (best_wait is not None and best_wait <= bound + 1e-8):
                    # Cache a complete minimum only, not a subset's upper bound.
                    profiles[actor["id"]] = (best_wait, None)
        best_actor, finish_eta, finish_weapon, reason = None, None, None, "no_usable_current_mech"
        self._geometry_deadline = deadline
        if short:
            weapon_order = {"gun": 0, "lightning": 1, "laser": 2}
            best = min(short, key=lambda r:r[:5] + (weapon_order.get(r[6], 3),))
            best_actor, finish_eta, finish_weapon, reason = best[5], best[0], best[6], "proactive_short_kill"
            incumbent = min((r for r in short if r[5]["id"] == self.target_id),
                            key=lambda r:(r[0], weapon_order.get(r[6], 3)), default=None)
            if charging and incumbent and incumbent[0] <= best[0] + .25:
                best_actor, finish_eta, finish_weapon = incumbent[5], incumbent[0], incumbent[6]
        else:
            if seed_actor is not None and not seed_complete:
                # A partial seed wait is only an upper bound. Complete it
                # before comparing readiness penalties against challengers.
                wait, seed_complete = self._usable_wait(obs, seed_actor, own, seed[2], deadline, with_completion=True)
                if seed_complete and wait is not None:
                    seed_value = seed[0]-.4*wait
                    profiles[seed_actor["id"]] = (wait, None)
            best_value, best_actor = seed_value, seed_actor
            if best_actor is not None:
                reason = "proactive_target_value"
            for score, actor, weapons, _ in sorted(scored, key=lambda r:(-r[0], r[1]["id"])):
                if (seed_actor is not None and not seed_complete) or score < best_value or time.perf_counter() >= deadline:
                    break
                if actor["id"] in profiles:
                    wait = profiles[actor["id"]][0]
                else:
                    wait = self._usable_wait(obs, actor, own, weapons, deadline)
                    checked.add(actor["id"])
                if wait is None:
                    exclusions.append((actor["id"], "no_usable_direct_weapon"))
                    continue
                value = score - .4*wait
                if value > best_value:
                    best_value, best_actor, reason = value, actor, "proactive_target_value"
            # Arcs are a bounded fallback, never a fifteen-target opening scan.
            if best_actor is None:
                for _, actor, _, _ in sorted(scored, key=lambda r:(-r[0], r[1]["id"])):
                    if arcs >= self.MAX_MORTAR_PROFILES or time.perf_counter() >= deadline:
                        break
                    weapons = self._cheap_weapons(obs, actor, own, mortar=True)
                    if not weapons:
                        continue
                    arcs += 1
                    if self._usable_wait(obs, actor, own, weapons, deadline) is not None:
                        best_actor, reason = actor, "proactive_mortar_path"
                        break
        elapsed = (time.perf_counter()-started)*1000
        self.last_scoring = dict(ms=elapsed, candidates=len(scored), checked=len(checked),
                                 short_profiles=checks, mortar_profiles=arcs,
                                 exhausted=time.perf_counter() >= deadline)
        self._geometry_deadline = math.inf
        self._solution_cache = None
        if best_actor is None:
            if self.last_scoring["exhausted"]:
                reason = "scoring_budget_exhausted"
            return Decision("OBSERVE", None, False, reason, exclusions=tuple(exclusions), authorized_ids=authorized)
        self.target_id = best_actor["id"]
        return AggressiveDecision("ATTACK", best_actor, True, reason, "current_visible_path", finish_eta=finish_eta,
                        finish_budget_s=self.MAX_FINISH_BUDGET if finish_eta is not None else 0,
                        exclusions=tuple(exclusions), authorized_ids=authorized, finish_weapon=finish_weapon)
