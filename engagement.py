"""Permission for reactive defense and short, observed third-party finishes.

This module never emits weapon commands. Combat remains authoritative for actual
aim, readiness, shot paths, and shared-aim scheduling. Ownerless projectiles,
sounds, proximity, and HP loss alone never establish an attacker or a fight.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from combat import Combat, angle_delta


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


@dataclass(frozen=True)
class Evidence:
    at: float
    kind: str
    peer: int | None = None


class Engagement:
    # Policy settings, not protocol constants. No elapsed-match opening gate.
    DEFENSE_MEMORY = 3.0
    FIGHT_MEMORY = 2.0
    MAX_FINISH_BUDGET = 2.0
    FINISH_MARGIN = 0.1

    def __init__(self, config, line_of_fire=None):
        self.config = config
        self.model = Combat(config, line_of_fire)
        self.attackers = {}
        self.participants = {}
        self._last_frame = None
        self._last_time = -1.0

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
                    self._remember(self.participants, actor["id"], Evidence(when, "attributed_beam", by))
                    self._remember(self.participants, by, Evidence(when, "attributed_beam", actor["id"]))
        self.attackers = {key: value for key, value in self.attackers.items()
                          if key not in killed and now - value.at < self.DEFENSE_MEMORY}
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

    def _collateral_clear(self, obs, actor, kind, stats, when, own, sol):
        protected = {a["id"] for a in obs.get("mechs", ())
                     if a.get("kind") == "mech" and a["id"] != actor["id"]}
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

    def _weapon_profile(self, obs, actor, remaining_defense=None):
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
            if not self._collateral_clear(obs, actor, kind, stats, first, own, sol):
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
            if final and final["clear"] and self._collateral_clear(obs, actor, kind, stats, finish, own, final):
                finishes.append(finish)
        return (min(waits) if waits else None, min(finishes) if finishes else None)

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
        for actor in usable:
            hp_key = actor.get("hp") if self._known_hp(actor) else float("inf")
            if defensive and hp_key > defensive[0][0]:
                break
            evidence = self.attackers.get(actor["id"])
            if evidence is None:
                continue
            age = max(0.0, now - evidence.at)
            if defense_window - age <= self.model.sim_dt:
                exclusions.append((actor["id"], "defense_window_ending"))
                continue
            profile = profiles[actor["id"]] = self._weapon_profile(obs, actor, defense_window - age)
            if profile[0] is None or profile[0] >= defense_window - age:
                exclusions.append((actor["id"], "no_ready_defensive_weapon"))
                continue
            defensive.append((actor.get("hp") if self._known_hp(actor) else float("inf"),
                              profile[1] if profile[1] is not None else float("inf"), actor["id"], actor, evidence))
        if defensive:
            _, _, _, actor, evidence = min(defensive, key=lambda row: row[:3])
            return Decision("DEFEND", actor, True, "recent_attributed_attack", evidence.kind,
                            max(0.0, now - evidence.at), profiles[actor["id"]][1], budget, tuple(exclusions))
        if recovering:
            return Decision("OBSERVE", None, False, "quiet_recovery", exclusions=tuple(exclusions))
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
                profile = profiles[actor["id"]] = self._weapon_profile(obs, actor)
            eta = profile[1]
            if eta is None or eta > effective:
                exclusions.append((actor["id"], "finish_exceeds_budget"))
                continue
            finishes.append((actor["hp"], eta, actor["id"], actor, evidence, effective))
        if finishes:
            _, eta, _, actor, evidence, effective = min(finishes, key=lambda row: row[:3])
            return Decision("FINISH", actor, True, "safe_observed_finish", evidence.kind,
                            max(0.0, now - evidence.at), eta, effective, tuple(exclusions))
        return Decision("OBSERVE", None, False, "no_authorized_mech_target", finish_budget_s=budget,
                        exclusions=tuple(exclusions))
