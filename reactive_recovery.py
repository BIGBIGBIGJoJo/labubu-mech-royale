"""A bounded relocation from a reached recovery goal after observed damage.

Damage bearings provide directions, not enemy positions or cover guarantees.
Every accepted route is a complete terrain-ground witness. Failed or incomplete
work leaves ordinary movement authority with the caller.
"""
import math
import time


def distance(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])


class ReactiveRecovery:
    ARRIVAL_RADIUS = 1.5  # Same stop radius as Bot.act.

    def __init__(self, arena, zone_routes):
        self.arena = arena
        self.zone_routes = zone_routes
        self.evidence = None
        self.unknown_damager_at = -math.inf
        self.consumed = None
        self.active = None
        self.last_report = {"reason": "none", "active": False}

    @property
    def goal(self):
        return self.active["goal"] if self.active is not None else None

    def observe(self, obs):
        for index, event in enumerate(obs.get("events", ())):
            amount = event.get("amount")
            if (event.get("type") != "damaged" or event.get("weapon") in (None, "zone")
                    or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0):
                continue
            attacker, bearing = event.get("by"), event.get("bearing")
            if attacker is None:
                self.unknown_damager_at = obs["t"]
            # A later bearing-less weapon event cannot revive an older bearing.
            self.evidence = None
            if attacker is not None and isinstance(bearing, (int, float)) and math.isfinite(bearing):
                self.evidence = {"key": (obs["tick"], index), "t": obs["t"],
                                 "attacker": attacker, "bearing": bearing}

    def _report(self, reason, **extra):
        self.last_report = {"reason": reason, "active": self.active is not None, **extra}

    def _context(self, obs, stats, attackers, allowed):
        me, now = obs["self"], obs["t"]
        window = min(3.0, stats["regen_delay"])  # Existing active-contact window.
        evidence = self.evidence
        if not allowed or obs.get("mechs"):
            return None, "priority_or_observed_actor"
        if evidence is None or not 0 <= now-evidence["t"] < window:
            return None, "no_fresh_bearing"
        if 0 <= now-self.unknown_damager_at < window:
            return None, "unknown_recent_damager"
        recent = {actor for actor, seen in attackers.items() if 0 <= now-seen < window}
        if recent != {evidence["attacker"]}:
            return None, "not_single_recent_attacker"
        if len(obs.get("cubes", ())) > 256:
            return None, "growth_scan_limit"
        if (not self.arena.available or not me.get("grounded") or not hasattr(self.arena, "step_up")
                or not self.zone_routes._ground_scope(me["pos"])):
            return None, "not_terrain_grounded"
        if any(w and w["kind"] == "laser" and w.get("charge", 0) > 0 for w in me["weapons"]):
            return None, "active_charge"
        return evidence, None

    @staticmethod
    def _toward(start, end, bearing):
        return ((end[0]-start[0])*math.cos(bearing)
                + (end[1]-start[1])*math.sin(bearing))

    def _prove(self, obs, stats, point, center, zone_radius, deadline):
        if time.perf_counter() >= deadline:
            return None
        # A visible incidental pickup can grow the body before the next decision.
        _, radius, height = self.zone_routes._growth(obs, point, point, stats)
        if distance(point, center)+radius+2 > zone_radius:
            return None  # Unchanged cover-candidate future-zone margin.
        if (not self.arena.point_clear(obs["self"]["pos"], radius, height)
                or time.perf_counter() >= deadline
                or not self.zone_routes._ground_scope(point)
                or not self.arena.point_clear(point, radius, height)
                or time.perf_counter() >= deadline
                or not self.zone_routes._ground_segment(obs["self"]["pos"], point, radius, deadline)
                or time.perf_counter() >= deadline
                or not self.arena.move_clear(obs["self"]["pos"], point, radius, height)
                or time.perf_counter() >= deadline):
            return None
        timeline = self.zone_routes._timeline(obs, [obs["self"]["pos"], point], [radius],
                                             stats["walk_speed"], stats["ground_accel"], deadline)
        if timeline is None or timeline[1] < 0 or time.perf_counter() >= deadline:
            return None
        return {"radius": radius, "height": height, "eta": timeline[0], "zone_margin": timeline[1]}

    def maintain(self, obs, stats, attackers, allowed, center, zone_radius, deadline):
        """Return keep/arrived/cancel; caller expires a canceled owned goal."""
        if self.active is None:
            return "none"
        active = self.active
        evidence, reason = self._context(obs, stats, attackers, allowed)
        if reason is None and (obs["t"] >= active["until"]
                               or (stats["radius"], stats["height"]) != active["body"]):
            reason = "expired_or_body_changed"
        if reason is None and self._toward(obs["self"]["pos"], active["goal"], evidence["bearing"]) > 1e-8:
            reason = "new_bearing_toward_goal"
        if reason is None and distance(obs["self"]["pos"], active["goal"]) < self.ARRIVAL_RADIUS:
            self.active = None
            self._report("arrived")
            return "arrived"
        if reason is None and self._prove(obs, stats, active["goal"], center, zone_radius, deadline) is None:
            reason = "route_zone_or_budget"
        if reason is not None:
            self.active = None
            self._report(reason)
            return "cancel"
        self._report("retained", goal=list(active["goal"]), event=active["event"])
        return "keep"

    def select(self, obs, stats, attackers, allowed, held_goal, last_move,
               center, zone_radius, horizon, position_cost, deadline):
        """Return (attempted, goal); failed work leaves ordinary refresh intact.

        A successful relocation consumes that actual hit. Budget failures may
        retry while its evidence is fresh; arriving does not rearm the same hit.
        """
        if self.active is not None:
            return False, None
        evidence, reason = self._context(obs, stats, attackers, allowed)
        if reason is not None:
            self._report(reason)
            return False, None
        if evidence["key"] == self.consumed:
            self._report("hit_already_used")
            return False, None
        p = obs["self"]["pos"]
        if (held_goal is None or distance(p, held_goal) >= self.ARRIVAL_RADIUS
                or math.hypot(*last_move) > 1e-8
                or math.hypot(*obs["self"]["vel"][:2]) > 1.0):
            self._report("not_stopped_at_goal")
            return False, None
        length = stats["walk_speed"]*horizon
        bearing = evidence["bearing"]
        cosine, sine = math.cos(bearing), math.sin(bearing)
        best = None
        for dx, dy in ((-cosine, -sine), (-sine, cosine), (sine, -cosine)):
            if time.perf_counter() >= deadline:
                break
            point = [p[0]+length*dx, p[1]+length*dy, 0.0]
            point[2] = self.arena.ground_height(*point[:2])
            if (distance(p, point) < self.ARRIVAL_RADIUS
                    or self._toward(p, point, bearing) > 1e-8):
                continue
            proof = self._prove(obs, stats, point, center, zone_radius, deadline)
            if proof is None:
                continue
            score = position_cost(point)+.22*distance(p, point)
            if best is None or score < best[0]:
                best = (score, point, proof)
        if best is None:
            self._report("no_complete_candidate")
            return True, None
        _, point, proof = best
        self.consumed = evidence["key"]
        self.active = {"goal": point, "event": evidence["key"],
                       "body": (stats["radius"], stats["height"]),
                       "until": min(obs["t"]+1.2, evidence["t"]+min(3.0, stats["regen_delay"]))}
        self._report("admitted", goal=list(point), event=evidence["key"], **proof)
        return True, point
