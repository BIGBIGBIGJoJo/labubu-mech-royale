"""Bounded movement permission for a finish from the current firing position.

This module neither identifies fights nor selects a target. It provides a
conservative, observed-state safety gate; permission is valid for this tick only.
Thresholds are strategy parameters, not guarantees about future enemy actions.
"""
import math
import time


class FinishAssessment:
    __slots__ = ("allowed_ids", "reasons", "budget_s", "escape_anchor", "elapsed_ms")

    def __init__(self, allowed_ids, reasons, budget_s, escape_anchor, elapsed_ms):
        self.allowed_ids = frozenset(allowed_ids)
        self.reasons = reasons
        self.budget_s = min(2.0, max(0.0, budget_s)) if self.allowed_ids else 0.0
        self.escape_anchor = escape_anchor
        self.elapsed_ms = elapsed_ms

    def allows(self, actor):
        return bool(actor and actor.get("kind") == "mech" and actor.get("id") in self.allowed_ids)


class FinishSafety:
    """Use cube-scaled ``stats`` and current ``Bot.threats`` observations.

    Optional ``repair_before_finish(actor)`` returns True to veto that actor.
    It must be a bounded callback. Unknown geometry, missing threat information,
    an expired local budget, or callback failure never authorize a finish.
    """
    def __init__(self, config, arena):
        self.config = config
        self.map = arena
        # Bound hidden weapon upgrades rather than assuming every opponent has
        # base damage/range. Attention weights below remain policy estimates.
        self.weapons = {kind: dict(stats) for kind, stats in config["weapons"].items()}
        for upgrade in config.get("upgrades", []):
            for effect in upgrade.get("effects", []):
                path = effect.get("path", "").split(".")
                if len(path) != 3 or path[0] != "weapons" or path[1] not in self.weapons:
                    continue
                weapon, key = self.weapons[path[1]], path[2]
                if key not in weapon:
                    continue
                for _ in range(int(upgrade.get("max", 1))):
                    weapon[key] = (weapon[key] + effect.get("add", 0)) * effect.get("mul", 1)

    @staticmethod
    def _circle(obs, seconds):
        z = obs["zone"]
        active = max(0.0, obs["t"] + seconds - max(obs["t"], z["shrink_start"]))
        remaining = z["shrink_end"] - max(obs["t"], z["shrink_start"])
        fraction = min(1.0, active / max(remaining, .001))
        return ([z["center"][i] + fraction * (z["next_center"][i] - z["center"][i]) for i in range(2)],
                z["radius"] + fraction * (z["next_radius"] - z["radius"]))

    @staticmethod
    def _inside(point, circles, margin):
        return all(math.dist(point[:2], center) + margin <= radius for center, radius in circles)

    def _pressure(self, me, visible):
        """Conservative exposure score, with explicit near/aimed beam vetoes."""
        total = 0.0
        for actor, distance in visible:
            if actor.get("kind") == "npc":
                if distance < 55:
                    total += 75.0
                continue
            if "aim" not in actor or "weapons" not in actor:
                return 0.0, "unknown_pressure"
            bearing = math.atan2(me["pos"][1] - actor["pos"][1], me["pos"][0] - actor["pos"][0])
            error = abs((bearing - actor["aim"][0] + math.pi) % math.tau - math.pi)
            attention = .75 if error < .30 else (.40 if error < .85 else .14)
            damage_scale = 1 + self.config["cubes"]["damage_per_cube"] * min(
                self.config["cubes"]["stat_cap"], actor.get("cubes", 0))
            for kind in actor["weapons"]:
                if kind not in self.weapons:
                    return 0.0, "unknown_pressure"
                weapon = self.weapons[kind]
                reach = weapon.get("range", weapon.get("speed", 72) * weapon.get("ttl", 7))
                if distance > reach + 15:
                    continue
                if kind == "lightning" and distance < reach + 12:
                    return 0.0, "near_lightning"
                if actor.get("charging") and kind == "laser" and error < .30:
                    return 0.0, "aimed_charge"
                if distance < 55:
                    return 0.0, "near_threat"
                damage = weapon["damage"] + (weapon.get("splash", 0) if kind == "mortar" else 0)
                cycle = weapon.get("cooldown", 1) + (weapon.get("charge", 0) if kind == "laser" else 0)
                total += damage / max(.1, cycle) * damage_scale * attention
        return total, None

    def _projectile_danger(self, obs, stats, deadline):
        """Do not commit while a visible shot already intersects our hold area."""
        projectiles = obs.get("projectiles", [])
        if len(projectiles) > 32:
            return "projectile_load"
        p = obs["self"]["pos"]
        for shot in projectiles:
            if time.perf_counter() >= deadline:
                return "budget_exhausted"
            kind = shot.get("kind")
            if kind not in ("gun", "mortar") or "pos" not in shot or "vel" not in shot:
                return "unknown_projectile"
            start, velocity = shot["pos"], shot["vel"]
            if kind == "gun":
                vx, vy = velocity[:2]
                length2 = vx * vx + vy * vy
                at = min(.6, max(0.0, ((p[0]-start[0])*vx+(p[1]-start[1])*vy)/max(length2,1e-9)))
                x, y, z = (start[i] + velocity[i] * at for i in range(3))
                if math.hypot(x-p[0], y-p[1]) < stats["radius"] + .5 and p[2]-.5 <= z <= p[2]+stats["height"]+.5:
                    return "incoming_projectile"
            else:
                gravity = self.config["weapons"]["mortar"]["gravity"]
                splash = self.weapons["mortar"]["splash_radius"] + stats["radius"] + 2
                for step in range(1, 9):
                    at = step * .25
                    x, y = start[0] + velocity[0]*at, start[1] + velocity[1]*at
                    z = start[2] + velocity[2]*at - .5*gravity*at*at
                    if math.hypot(x-p[0], y-p[1]) < splash and z <= p[2]+stats["height"]:
                        return "incoming_mortar"
        return None

    def _escape(self, me, stats, visible, circles, deadline):
        p = list(me["pos"])
        speed = math.hypot(*me["vel"][:2])
        if speed > .5:
            # Analytic stopping distance is conservative versus semi-implicit
            # 20 Hz braking, and prevents approving an exit through inertia.
            stop_time = speed / max(stats["ground_accel"], .001)
            braking = [p[0]+me["vel"][0]*stop_time*.5, p[1]+me["vel"][1]*stop_time*.5, p[2]]
            if not self.map.move_clear(p, braking, stats["radius"], stats["height"]):
                return None, "inertial_collision"
            if not self._inside(braking, circles, stats["radius"]+8):
                return None, "zone_slack"
            p = braking
            p[2] = self.map.support_height(p[0], p[1], me["pos"][2])
            if me["pos"][2]-p[2] > stats["step_up"]+.02:
                return None, "inertial_drop"
        rx = sum((p[0]-a["pos"][0])/max(d*d, 100) for a,d in visible)
        ry = sum((p[1]-a["pos"][1])/max(d*d, 100) for a,d in visible)
        angle = math.atan2(ry, rx)
        length = max(10.0, min(16.0, stats["walk_speed"]))
        margin = stats["radius"] + 8
        for offset in (0, .65, -.65, 1.3, -1.3, math.pi):
            if time.perf_counter() >= deadline:
                return None, "budget_exhausted"
            endpoint = [p[0]+math.cos(angle+offset)*length, p[1]+math.sin(angle+offset)*length, p[2]]
            if not self._inside(endpoint, circles, margin):
                continue
            # A corridor that approaches a nearby pursuer is not an escape.
            if any(d < 110 and math.dist(endpoint[:2], a["pos"][:2]) < d-1 for a,d in visible):
                continue
            if not self.map.move_clear(p, endpoint, stats["radius"], stats["height"]):
                continue
            previous = p[2]
            supported = True
            for step in range(1, 7):
                if time.perf_counter() >= deadline:
                    return None, "budget_exhausted"
                x, y = p[0]+(endpoint[0]-p[0])*step/6, p[1]+(endpoint[1]-p[1])*step/6
                z = self.map.support_height(x, y, previous)
                if previous-z > stats["step_up"]+.02:
                    supported = False
                    break
                previous = z
            if supported:
                endpoint[2] = previous
                return endpoint, None
        return None, "no_escape_corridor"

    def evaluate(self, obs, threats, stats, *, recovering=False, urgent=False, repair_before_finish=None):
        begin = time.perf_counter()
        deadline = begin + .0017
        actors = [a for a in obs.get("mechs", []) if a.get("kind") == "mech"]
        reasons = {a["id"]: "not_visible" for a in actors}
        allowed, escape, budget = [], None, 2.0

        def finish(reason=None):
            if reason:
                for actor in actors:
                    if reasons[actor["id"]] == "pending":
                        reasons[actor["id"]] = reason
            return FinishAssessment(allowed, reasons, budget, escape, (time.perf_counter()-begin)*1000)

        by_id = {q["actor"]["id"]: q for q in threats}
        candidates = []
        for actor in actors:
            q = by_id.get(actor["id"])
            if (actor.get("hp", 0) > 0 and q is not None and q.get("los") is True
                    and not q.get("remembered") and q["actor"]["pos"] == actor["pos"]):
                reasons[actor["id"]] = "pending"
                candidates.append(actor)
        if not candidates:
            return finish()
        me = obs["self"]
        if recovering or urgent:
            return finish("recovering" if recovering else "urgent_rotation")
        if not getattr(self.map, "available", False):
            return finish("map_unavailable")
        if not me.get("grounded", False):
            return finish("airborne")
        if me["hp"] < .72 * me["max_hp"]:
            return finish("health_reserve")
        if me["energy"] < max(35.0, stats["boost_drain"]*1.25+12):
            return finish("energy_reserve")
        if any(a["id"] not in by_id or not isinstance(by_id[a["id"]].get("los"), bool)
               or by_id[a["id"]].get("remembered") or by_id[a["id"]]["actor"]["pos"] != a["pos"] for a in actors):
            return finish("unknown_pressure")
        if not self.map.point_clear(me["pos"], stats["radius"], stats["height"]):
            return finish("body_blocked")
        circles = [self._circle(obs, seconds) for seconds in (0, 2, 3.5)]
        if not me.get("in_zone", False) or not self._inside(me["pos"], circles, stats["radius"]+8):
            return finish("zone_slack")
        visible = [(q["actor"], math.dist(q["actor"]["pos"][:2], me["pos"][:2]))
                   for q in threats if q.get("los") is True and not q.get("remembered")]
        incoming, reason = self._pressure(me, visible)
        if reason:
            return finish(reason)
        if incoming > 0:
            # Keep at least 70% of current HP against this policy risk estimate.
            budget = min(2.0, me["hp"]*.30/incoming)
        if budget < .8:
            return finish("concentrated_pressure")
        reason = self._projectile_danger(obs, stats, deadline)
        if reason:
            return finish(reason)
        # Occluded but currently observed opponents still constrain the exit;
        # crossing their corner must not turn a safe firing pose into a chase.
        hazards = [(q["actor"], math.dist(q["actor"]["pos"][:2], me["pos"][:2]))
                   for q in threats if not q.get("remembered")]
        escape, reason = self._escape(me, stats, hazards, circles, deadline)
        if reason:
            return finish(reason)
        for actor in candidates:
            if time.perf_counter() >= deadline:
                reasons[actor["id"]] = "budget_exhausted"
                continue
            if math.dist(actor["pos"][:2], me["pos"][:2]) < 60:
                reasons[actor["id"]] = "target_too_close"
                continue
            if repair_before_finish is not None:
                try:
                    repair = repair_before_finish(actor)
                except Exception:
                    reasons[actor["id"]] = "repair_unknown"
                    continue
                if time.perf_counter() >= deadline:
                    reasons[actor["id"]] = "budget_exhausted"
                    continue
                if repair is not False:
                    reasons[actor["id"]] = "opponent_repair" if repair is True else "repair_unknown"
                    continue
            reasons[actor["id"]] = "safe_current_position"
            allowed.append(actor["id"])
        return finish()
