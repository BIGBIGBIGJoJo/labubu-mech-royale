"""Labubu's adaptive survival controller for the official mechfight/1 protocol."""
from __future__ import annotations

import math
import time
from collections import deque

import mechfight as mf
from arena_map import ArenaMap
from combat import Combat
from engagement import Engagement
from positioning import FinishSafety
from tactical import TacticalPlanner


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(x, y):
    n = math.hypot(x, y)
    return (x / n, y / n) if n > 1e-8 else (0.0, 0.0)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class Bot:
    name = "labubu-bastion"

    def __init__(self, hello):
        self.config = hello["config"]
        self.map = ArenaMap(hello["map"]["dir"], self.config)
        self.combat = Combat(self.config, self.map.line_of_fire)
        self.engagement = Engagement(self.config, self.map.line_of_fire)
        self.finish_safety = FinishSafety(self.config, self.map)
        self.tactical = TacticalPlanner(self.config, self.map)
        self.slot = hello["slot"]
        self.recover = False
        self.mode = "explore"
        self.state = "OPENING"
        self.goal = None
        self.goal_until = -1.0
        self.goal_kind = ""
        self.last_hurt = -100.0
        self.last_weapon_hurt = -100.0
        self.last_combat = -100.0
        self.damage_bearing = None
        self.last_jump = -100.0
        self.history = deque()
        self.loot = {}
        self.blacklist = {}
        self.last_move = (0.0, 0.0)
        self.strafe = 1 if self.slot % 2 else -1
        self.last_strafe = 0.0
        self.telemetry = {}
        self.visited = {}
        self.visit_t = -1
        self.spacing_boost = False
        self.recent_attackers = {}
        self.resource_key = None
        self.target_id = None
        self.failed_goals = []
        self.goal_progress = None
        self.actor_memory = {}

    def stats(self, me):
        stats = {**self.config["mech"], **me.get("stats", {})}
        scale = 1 + self.config["cubes"]["size_per_cube"] * me.get("cubes", 0)
        # The protocol pre-scales eye/muzzle only; collision dimensions remain
        # upgraded base values in self.stats and need the uncapped cube scale.
        stats["radius"] *= scale
        stats["height"] *= scale
        for key in ("eye_height", "muzzle_height"):
            if key not in me.get("stats", {}):
                stats[key] *= scale
        return stats

    def zone_future(self, obs, seconds):
        z = obs["zone"]
        if obs["t"] + seconds <= z["shrink_start"]:
            return z["center"], z["radius"]
        # The supplied current circle already includes shrink elapsed so far.
        remaining = z["shrink_end"] - max(obs["t"], z["shrink_start"])
        active = max(0.0, obs["t"] + seconds - max(obs["t"], z["shrink_start"]))
        fraction = clamp(active / max(remaining, 0.001), 0.0, 1.0)
        center = [z["center"][i] + fraction * (z["next_center"][i] - z["center"][i]) for i in range(2)]
        radius = z["radius"] + fraction * (z["next_radius"] - z["radius"])
        return center, radius

    def update(self, obs):
        t, me = obs["t"], obs["self"]
        for actor in obs.get("mechs", []):
            if actor.get("hp", 1) > 0:
                snapshot = {**actor, "pos": list(actor["pos"]),
                            "vel": list(actor.get("vel", (0, 0, 0))),
                            "weapons": list(actor.get("weapons", []))}
                self.actor_memory[actor["id"]] = (snapshot, t)
        if t >= self.visit_t + 1:
            cell = (int(me["pos"][0] // 35), int(me["pos"][1] // 35))
            self.visited[cell] = self.visited.get(cell, 0) + 1
            self.visit_t = t
        for event in obs.get("events", []):
            if event["type"] == "kill":
                self.actor_memory.pop(event.get("target"), None)
            if event["type"] in ("hit", "damaged"):
                self.last_combat = t
            if event["type"] == "damaged":
                self.last_hurt = t
                if event.get("weapon") != "zone":
                    self.last_weapon_hurt = t
                    if event.get("by") is not None:
                        self.recent_attackers[event["by"]] = t
                if event.get("bearing") is not None:
                    self.damage_bearing = event["bearing"]
            if event["type"] in ("took", "take_failed"):
                self.loot.pop(("pickups", event.get("id")), None)
        self.history.append((t, tuple(me["pos"]), math.hypot(*self.last_move)))
        while self.history and self.history[0][0] < t - 2.0:
            self.history.popleft()
        for category in ("cubes", "pickups", "crates"):
            current = {item["id"] for item in obs.get(category, [])}
            for item in obs.get(category, []):
                self.loot[(category, item["id"])] = (item, t)
            for key, (item, seen) in list(self.loot.items()):
                if key[0] != category:
                    continue
                absent_near = False
                near_range = self.config["vision"]["near_range"] + me.get("stats", {}).get("near_range_bonus", 0)
                if item["id"] not in current and distance(item["pos"], me["pos"]) < near_range:
                    eye_h = me.get("stats", {}).get("eye_height", self.config["mech"]["eye_height"])
                    absent_near = self.map.line_of_fire([me["pos"][0], me["pos"][1], me["pos"][2] + eye_h], [item["pos"][0], item["pos"][1], item["pos"][2] + .8])
                if t - seen > 45 or absent_near:
                    self.loot.pop(key, None)
        self.blacklist = {k: until for k, until in self.blacklist.items() if until > t}
        self.recent_attackers = {k: seen for k, seen in self.recent_attackers.items() if t - seen < 5}
        self.failed_goals = [(point, until) for point, until in self.failed_goals if until > t]
        self.actor_memory = {actor_id: value for actor_id, value in self.actor_memory.items() if t - value[1] < 8}

    def actor_center(self, actor):
        if actor.get("kind") == "npc":
            h = self.config["npc"].get("height", 3.5)
        else:
            h = self.config["mech"]["height"] * (1 + self.config["cubes"].get("size_per_cube", 0) * actor.get("cubes", 0))
        return [actor["pos"][0], actor["pos"][1], actor["pos"][2] + h * 0.5]

    def threats(self, obs, s):
        p = obs["self"]["pos"]
        eye = [p[0], p[1], p[2] + s["muzzle_height"]]
        result = []
        for actor in sorted(obs.get("mechs", []), key=lambda a: distance(a["pos"], p))[:16]:
            d = distance(actor["pos"], p)
            if actor.get("kind") == "npc" and d > self.config["npc"]["aggro_range"] + 15:
                continue
            center = self.actor_center(actor)
            visible = self.map.line_of_fire(eye, center)
            if not visible:
                upper = [center[0], center[1], actor["pos"][2] + (center[2] - actor["pos"][2]) * 1.8]
                visible = self.map.line_of_fire(eye, upper)
            weapons = actor.get("weapons", ["gun"])
            threat = (1.0 if actor.get("kind") == "mech" else .16) * (1 + .04 * actor.get("cubes", 0))
            threat *= 1.0 if visible else .18
            threat *= 1.0 + max(0, 80 - d) / 60
            if "lightning" in weapons and d < 55:
                threat *= 1.6
            if actor.get("charging"):
                threat *= 1.5
            result.append({"actor": actor, "d": d, "los": visible, "risk": threat})
        return result

    def choose_target(self, obs, threats):
        """Compatibility helper: no broad threat score can grant mech fire."""
        decision = self.engagement.select(obs, threats, recovering=self.recover)
        return decision.target or self.npc_defense_target(obs, threats)

    def npc_defense_target(self, obs, threats):
        window = min(3.0, self.stats(obs["self"])["regen_delay"]) if self.recover else 3.0
        attackers = [q for q in threats if q["actor"]["kind"] == "npc"
                     and q["los"] and q["d"] <= 60
                     and obs["t"] - self.recent_attackers.get(q["actor"]["id"], -100) < window]
        return min(attackers, key=lambda q: (q["actor"].get("hp", 350), q["d"]))["actor"] if attackers else None

    def choose_upgrade(self, obs):
        offer = obs.get("offer")
        if not offer:
            return None
        me = obs["self"]
        kinds = {w["kind"] for w in me["weapons"] if w}
        scores = {"nanites": 95, "servos": 84, "armor": 81, "plating": 78,
                  "gun_damage": 68, "gun_mag": 73, "gun_rate": 63, "gun_velocity": 65,
                  "reactor": 65, "jets": 64, "capacitor": 48, "gyros": 45, "sensors": 38,
                  "laser_damage": 79, "laser_charge": 75, "laser_pierce": 31,
                  "lightning_efficiency": 79, "lightning_range": 80, "lightning_chain": 43,
                  "mortar_reload": 58, "mortar_splash": 62, "mortar_velocity": 49}
        if me["hp"] / me["max_hp"] < .45:
            scores["plating"] += 17
        if "lightning" in kinds:
            scores["reactor"] += 15
        if obs["zone"]["next_radius"] < 30:
            scores["nanites"] -= 30
            scores["plating"] += 12
        return max(range(len(offer["choices"])), key=lambda i: scores.get(offer["choices"][i]["id"], 25))

    def weapon_rank(self, obs):
        rank = {"gun": 0, "mortar": 1, "lightning": 2, "laser": 3}
        if obs["zone"]["radius"] < 55:
            rank["lightning"] = 4
        return rank

    def repair_before_projected_finish(self, obs, target):
        """Estimate repair advantage for movement, never suppress a viable shot."""
        if target is None or target.get("kind") != "mech":
            return False
        me = obs["self"]
        d = distance(me["pos"], target["pos"])
        scale = 1 + self.config["cubes"]["damage_per_cube"] * min(me["cubes"], self.config["cubes"]["stat_cap"])
        for drop in obs.get("drops", []):
            if drop.get("holder") != target["id"] or drop["lands_in"] > 0:
                continue
            if distance(me["pos"], drop["pos"]) <= drop["radius"]:
                continue  # Our presence freezes the opponent's capture clock.
            if any(a["kind"] == "mech" and a["id"] != target["id"]
                   and distance(a["pos"], drop["pos"]) <= drop["radius"] for a in obs.get("mechs", [])):
                continue
            remaining = max(0, drop["capture_s"] - drop.get("progress", 0))
            if remaining > 3:
                continue
            maximum = 0.0
            for weapon in me["weapons"]:
                if not weapon:
                    continue
                stats, kind = weapon["stats"], weapon["kind"]
                first = max(.05, weapon.get("cooldown", 0))
                if kind == "gun":
                    if d > stats["range"]:
                        continue
                    first = max(first, weapon.get("reload", 0))
                    ammo = stats["mag"] if weapon.get("reload", 0) > 0 else weapon.get("ammo", 0)
                    if ammo <= 0:
                        first = max(first, stats["reload"])
                        ammo = stats["mag"]
                    # Credit potentially outstanding bullets and ignore new
                    # bullet flight time: uncertainty must favor a possible kill.
                    body = self.config["mech"]["radius"] * (1 + self.config["cubes"]["size_per_cube"] * target.get("cubes", 0))
                    flight = max(0, d - self.stats(me)["radius"] - .5 - body) / stats["speed"]
                    pending = min(stats["mag"], math.ceil(flight / stats["cooldown"]))
                    shots = 0
                    while first <= remaining and shots < 128:
                        shots += 1
                        ammo -= 1
                        if ammo == 0:
                            first += stats["reload"]
                            ammo = stats["mag"]
                        else:
                            first += stats["cooldown"]
                    maximum += (shots + pending) * stats["damage"]
                elif kind == "lightning":
                    first = max(first, max(0, d - stats["range"]) / self.stats(me)["boost_speed"])
                    shots = max(0, 1 + int((remaining - first) / stats["cooldown"])) if remaining >= first else 0
                    maximum += shots * stats["damage"]
                else:
                    # This gate concerns the gun/lightning commitment. Avoid
                    # claiming impossibility for an unmodeled laser/mortar shot.
                    return False
            maximum *= scale * self.config["mech"]["rear_mult"]
            if maximum + 1e-6 < target.get("hp", 1400):
                return True
        return False

    def lightning_commit(self, obs, target, visible_count):
        me = obs["self"]
        if visible_count > 1 or me["energy"] < 55 or target.get("kind") != "mech":
            return False
        enemy_weapons = target.get("weapons", [])
        if "mortar" in enemy_weapons or self.repair_before_projected_finish(obs, target):
            return False
        lightning = next((w for w in me["weapons"] if w and w["kind"] == "lightning"), None)
        if lightning is None:
            return False
        short_advantage = "laser" in enemy_weapons and distance(me["pos"], target["pos"]) <= lightning["stats"]["range"] + 15
        effective_hp = me["hp"] / max(.05, 1 - self.stats(me).get("armor", 0))
        return effective_hp >= target.get("hp", target.get("max_hp", 1400)) * (.8 if short_advantage else .95)

    def defensive_yaw(self, obs, threats):
        """Keep several attackers in the front armor arc during a long reload."""
        p, actual = obs["self"]["pos"], obs["self"]["aim"][0]
        incoming = []
        for q in threats:
            if not q["los"]:
                continue
            actor = q["actor"]
            bearing = math.atan2(actor["pos"][1] - p[1], actor["pos"][0] - p[0])
            weight = q["risk"] * (2 if obs["t"] - self.recent_attackers.get(actor["id"], -100) < 3 else 1)
            incoming.append((bearing, weight))
        if not incoming:
            return actual
        delta = lambda a, b: (a - b + math.pi) % math.tau - math.pi
        candidates = [actual] + [a for a, _ in incoming]
        for i, (a, _) in enumerate(incoming):
            candidates.extend(a + delta(b, a) * .5 for b, _ in incoming[i + 1:])
        half_front = math.radians(self.stats(obs["self"])["front_arc_deg"] * .5)
        def cost(yaw):
            rear = sum(weight for bearing, weight in incoming if abs(delta(bearing, yaw)) > half_front - .04)
            return rear * 10 + abs(delta(yaw, actual)) * .01
        return min(candidates, key=cost)

    def take_weapon(self, obs):
        me = obs["self"]
        held = {w["kind"] for w in me["weapons"] if w}
        rank = self.weapon_rank(obs)
        for item in sorted(obs.get("pickups", []), key=lambda p: -rank.get(p["kind"], 0)):
            if item["kind"] in held or item["kind"] == "gun":
                continue
            if distance(item["pos"], me["pos"]) >= self.config["loot"]["pickup_radius"] or abs(item["pos"][2] - me["pos"][2]) > 4:
                continue
            empty = next((i for i, w in enumerate(me["weapons"]) if w is None), None)
            if empty is not None:
                return {"take": item["id"]}
            for i, w in enumerate(me["weapons"]):
                if w["kind"] != "gun" and not w.get("charge", 0) and rank.get(item["kind"], 0) > rank.get(w["kind"], 0):
                    return {"take": item["id"], "drop": i}
        return {}

    def position_cost(self, point, threats, center, radius, body_radius, recovering=False, muzzle_height=None):
        # Scores are strategy parameters, not claimed probabilities or game constants.
        outside = max(0.0, distance(point, center) + body_radius + 4 - radius)
        score = outside * 9.0
        height = muzzle_height if muzzle_height is not None else self.config["mech"]["muzzle_height"]
        origin = [point[0], point[1], point[2] + height]
        for q in threats[:5]:
            actor = q["actor"]
            d = distance(point, actor["pos"])
            if d < 260 and self.map.line_of_fire(origin, self.actor_center(actor)):
                # Re-evaluate exposure at this position, not at the old position.
                strength = q["risk"] / (1 if q["los"] else .18)
                score += strength * (55 if recovering else 16)
                score += max(0, 65 - d) * (1.3 if recovering else .35)
                if recovering:
                    reach = max((self.config["weapons"].get(kind, {}).get("range", 230) for kind in actor.get("weapons", ["gun"])), default=230)
                    score += strength * 90 * max(0, 1 - d / max(1, reach))
        return score

    def safe_goal(self, obs, threats, s, deadline):
        p = obs["self"]["pos"]
        center, radius = self.zone_future(obs, 22)
        if not self.recover and not threats:
            # Explore locally without repeatedly selecting the current point.
            options = []
            for i in range(12):
                angle = 2 * math.pi * i / 12 + self.slot * .17
                point = [p[0] + 75 * math.cos(angle), p[1] + 75 * math.sin(angle), 0]
                if distance(point, center) + s["radius"] + 12 > radius:
                    continue
                point[2] = self.map.ground_height(*point[:2])
                if any(distance(point, failed) < 8 for failed, _ in self.failed_goals):
                    continue
                if not self.map.point_clear(point, s["radius"], s["height"]):
                    continue
                cell = (int(point[0] // 35), int(point[1] // 35))
                score = self.visited.get(cell, 0) * 30 + distance(point, center) * .03
                options.append((score, point))
            if options:
                return min(options, key=lambda item: item[0])[1]
        generation_deadline = min(deadline - .004, time.perf_counter() + .003)
        candidates = self.map.cover_candidates(p, center, radius, s["radius"], s["height"], limit=12, deadline=generation_deadline)
        if self.recover and threats:
            vx = sum((p[0] - q["actor"]["pos"][0]) * q["risk"] / max(100, q["d"] ** 2) for q in threats[:5])
            vy = sum((p[1] - q["actor"]["pos"][1]) * q["risk"] / max(100, q["d"] ** 2) for q in threats[:5])
            if math.hypot(vx, vy) < .001:
                vx, vy = p[0] - threats[0]["actor"]["pos"][0], p[1] - threats[0]["actor"]["pos"][1]
            away = math.atan2(vy, vx)
            retreats = []
            for angle in (away, away + .7, away - .7):
                point = [p[0] + 40 * math.cos(angle), p[1] + 40 * math.sin(angle), 0]
                point[2] = self.map.ground_height(*point[:2])
                if distance(point, center) + s["radius"] + 6 < radius and self.map.point_clear(point, s["radius"], s["height"]):
                    retreats.append(point)
            candidates = list(candidates) + retreats
        # The origin is also a useful candidate when already behind effective cover.
        candidates = [list(p)] + list(candidates)
        if not candidates:
            return [*center, self.map.ground_height(*center)]
        best, score = list(p), float("inf")
        for point in candidates:
            if time.perf_counter() > deadline:
                break
            if any(distance(point, failed) < 8 for failed, _ in self.failed_goals):
                continue
            cost = self.position_cost(point, threats, center, radius, s["radius"], self.recover, s["muzzle_height"])
            cost += distance(point, p) * .22
            if not self.recover:
                cost += distance(point, center) * .07
            if cost < score:
                best, score = point, cost
        if distance(best, center) + s["radius"] > radius:
            u = unit(best[0] - center[0], best[1] - center[1])
            r = max(0, radius - s["radius"] - 15)
            best = [center[0] + r * u[0], center[1] + r * u[1], self.map.ground_height(center[0] + r * u[0], center[1] + r * u[1])]
        return best

    def check_route_progress(self, obs, goal, navigation, exposed):
        """Retire unreachable cover instead of repeatedly choosing its endpoint."""
        if self.mode not in ("recover", "rotate", "position"):
            self.goal_progress = None
            return
        t, p = obs["t"], obs["self"]["pos"]
        remaining = distance(p, goal)
        tracking = self.goal_progress
        if tracking is None or distance(goal, tracking["goal"]) > 8:
            tracking = self.goal_progress = {"goal": list(goal), "distance": remaining, "since": t}
        if remaining < tracking["distance"] - 2:
            tracking.update(distance=remaining, since=t)
        blocked = getattr(self.map, "last_route_status", None) == "unreachable"
        holding = math.hypot(*navigation) < .1 and t - tracking["since"] >= 2
        if remaining > 8 and (blocked or (holding and (exposed or self.mode == "rotate"))):
            self.failed_goals.append((list(goal), t + 12))
            self.failed_goals = self.failed_goals[-12:]
            self.goal_until = -1
            self.goal_progress = None

    def resource_goal(self, obs, threats, deadline=None):
        """Price completion time and exposure for each reachable opportunity."""
        me, t = obs["self"], obs["t"]
        p, stats = me["pos"], self.stats(me)
        # An actor expiring from the server's visible list does not establish
        # that a nearby resource became uncontested. These extra memories are
        # resource hazards only; they never become speculative firing targets.
        known = {q["actor"]["id"] for q in threats}
        threats = list(threats) + [
            {"actor": actor, "d": distance(p, actor["pos"]), "los": False, "risk": .2, "remembered": True}
            for actor_id, (actor, seen) in self.actor_memory.items()
            if actor_id not in known and t - seen < 8
        ]
        threats.sort(key=lambda q: q["d"])
        speed = max(1, stats["walk_speed"])
        candidates = []
        held = {w["kind"] for w in me["weapons"] if w}
        ranks = self.weapon_rank(obs)
        mechs = [q for q in threats if q["actor"]["kind"] == "mech"]
        pickup_r = self.config["cubes"]["pickup_radius"]
        eye = [p[0], p[1], p[2] + stats["muzzle_height"]]
        cube_gain = stats["hp"] * self.config["cubes"]["hp_per_cube"]
        cap = self.config["cubes"]["stat_cap"]

        def exposure(point, travel, dwell=0, farming=False):
            penalty = 0.0
            for q in mechs[:5]:
                actor = q["actor"]
                end_d = distance(point, actor["pos"])
                # A short pickup while already retreating need not abandon the escape.
                retreating = end_d >= q["d"] + min(3, travel * .3)
                immediate = travel <= pickup_r
                if q["los"] and q["d"] < 60 and not immediate and not retreating:
                    return None
                if farming and q["los"] and min(q["d"], end_d) < 125:
                    return None
                if end_d < 40 and not (immediate or retreating):
                    return None
                end_eye = [point[0], point[1], point[2] + stats["muzzle_height"]]
                exposed = self.map.line_of_fire(end_eye, self.actor_center(actor))
                if not exposed:
                    continue
                if self.recover and q["los"] and end_d < q["d"] - 2 and travel > pickup_r:
                    return None
                if dwell and end_d < 100:
                    return None
                power = 1 + .04 * actor.get("cubes", 0)
                penalty += power * max(0, 150 - end_d) * .16
                penalty += power * max(0, q["d"] - end_d) * .8
                if not q["los"]:
                    penalty += 22  # Opening a new line of fire has a real cost.
                if "lightning" in actor.get("weapons", []) and end_d < 65:
                    penalty += (65 - end_d) * 2
            return penalty

        def safe_zone(point, seconds):
            center, radius = self.zone_future(obs, seconds + 4)
            return distance(point, center) + stats["radius"] + 8 < radius

        def add(item, kind, key, benefit, seen=t, dwell=0, farming=False):
            point = list(item["pos"])
            travel = distance(p, point)
            eta = max(0, travel - pickup_r) / speed + dwell
            if travel > 150 or not safe_zone(point, eta):
                return
            if abs(point[2] - self.map.ground_height(*point[:2])) > 3:
                return
            risk = exposure(point, travel, dwell, farming)
            if risk is None:
                return
            if self.recover and travel > 30 and kind != "drop":
                return
            score = benefit - .52 * travel - 5 * dwell - risk - .2 * (t - seen)
            if key == self.resource_key:
                score += 10  # Complete useful work instead of oscillating objectives.
            if score > 0:
                candidates.append((score, point, kind, key, item))

        nearby = sorted(self.loot.items(), key=lambda pair: distance(p, pair[1][0]["pos"]))
        for key, (item, seen) in nearby[:32]:
            if deadline is not None and time.perf_counter() >= deadline:
                break
            if key in self.blacklist:
                continue
            kind = key[0]
            if kind == "cubes":
                count = sum(distance(item["pos"], other[0]["pos"]) <= pickup_r
                            and abs(item["pos"][2] - other[0]["pos"][2]) <= 4
                            for k, other in nearby if k[0] == "cubes" and k not in self.blacklist)
                useful = min(count, max(0, cap - me["cubes"]))
                next_count = me["cubes"] + count
                threshold = any(me["cubes"] < n <= next_count for n in self.config["cubes"]["upgrade_thresholds"])
                benefit = 32 * useful + 6 * (count - useful) + (25 if threshold else 0)
                if self.recover:
                    benefit += min(me["max_hp"] - me["hp"], cube_gain * useful) * .3
                add(item, kind, key, benefit, seen)
            elif kind == "pickups":
                if item["kind"] in held or item["kind"] == "gun":
                    continue
                if all(w is not None for w in me["weapons"]):
                    replacements = [w for w in me["weapons"] if w["kind"] != "gun" and not w.get("charge", 0) and ranks.get(item["kind"], 0) > ranks.get(w["kind"], 0)]
                    if not replacements:
                        continue
                benefit = {"laser": 93, "lightning": 77, "mortar": 59}.get(item["kind"], 0)
                if len(held) < 2:
                    benefit += 15
                add(item, kind, key, benefit, seen)
            else:
                if self.recover or me["hp"] < .8 * me["max_hp"] or me["cubes"] >= cap:
                    continue
                if not self.map.line_of_fire(eye, [*item["pos"][:2], item["pos"][2] + self.config["crates"].get("height", 2.4) * .7]):
                    continue
                remaining = item.get("hp", self.config["crates"]["hp"])
                gun = next((w for w in me["weapons"] if w and w["kind"] == "gun"), None)
                if not gun:
                    continue
                damage = gun["stats"]["damage"]
                shots = math.ceil(remaining / max(1, damage))
                dwell = max(0, shots - 1) * gun["stats"]["cooldown"] + gun.get("reload", 0)
                if shots > gun.get("ammo", 0):
                    dwell += gun["stats"]["reload"]
                benefit = 62 + (18 if me["cubes"] == 0 else 0) + 20 * (1 - remaining / self.config["crates"]["hp"])
                add(item, kind, key, benefit, seen, dwell, farming=True)

        # Isolated NPCs produce two cubes; do not start a farm inside a mech fight.
        if not self.recover and me["hp"] >= .8 * me["max_hp"] and me["cubes"] < cap:
            for q in threats:
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                if q["actor"]["kind"] != "npc" or not q["los"] or q["d"] > 55:
                    continue
                if any(m["los"] and m["d"] < 140 for m in mechs):
                    continue
                actor = q["actor"]
                key = ("npc", actor["id"])
                if key in self.blacklist:
                    continue
                add(actor, "npc", key, 87, dwell=actor.get("hp", 350) / 160, farming=True)

        for drop in obs.get("drops", []):
            if deadline is not None and time.perf_counter() >= deadline:
                break
            key = ("drop", drop["id"])
            if key in self.blacklist:
                continue
            point = list(drop["pos"])
            travel = distance(p, point)
            arrival = max(0, travel - drop["radius"]) / speed
            progress = drop.get("progress", 0) if drop.get("holder") == self.slot else 0
            dwell = max(0, drop["lands_in"] - arrival) + max(0, drop["capture_s"] - progress)
            # Avoid sitting at an announced drop for most of its fall time.
            if dwell > drop["capture_s"] + 4 or travel > 210:
                continue
            completion = arrival + dwell
            if not safe_zone(point, completion):
                continue
            # A known enemy that can contest before capture makes this speculative.
            if any(max(0, distance(point, q["actor"]["pos"]) - drop["radius"]) / max(speed, self.config["mech"]["boost_speed"]) < completion + 1 for q in mechs):
                continue
            risk = exposure(point, travel, dwell)
            if risk is None:
                continue
            incoming = 0.0
            drop_eye = [point[0], point[1], point[2] + stats["muzzle_height"]]
            for q in mechs[:5]:
                actor = q["actor"]
                if not self.map.line_of_fire(drop_eye, self.actor_center(actor)):
                    continue
                d = distance(point, actor["pos"])
                for kind in actor.get("weapons", ["gun"]):
                    weapon = self.config["weapons"].get(kind, {})
                    if d > weapon.get("range", 180):
                        continue
                    cycle = weapon.get("cooldown", 1) + (weapon.get("charge", 0) if kind == "laser" else 0)
                    shots = 1 + int(completion / max(.1, cycle))
                    damage = weapon.get("damage", 45) + (weapon.get("splash", 0) if kind == "mortar" else 0)
                    incoming += shots * damage * (1 + self.config["cubes"]["damage_per_cube"] * min(cap, actor.get("cubes", 0)))
            for q in threats:
                actor = q["actor"]
                if actor["kind"] != "npc":
                    continue
                d = distance(point, actor["pos"])
                active = d <= self.config["npc"]["aggro_range"] or t - self.recent_attackers.get(actor["id"], -100) < 3
                if active and self.map.line_of_fire(drop_eye, self.actor_center(actor)):
                    incoming += (1 + int(completion / self.config["npc"]["cooldown"])) * self.config["npc"]["damage"]
            # An unopposed capture can still be covered by ranged weapons.
            # Estimate base-weapon exposure assuming every shot lands.
            incoming *= 1 - stats.get("armor", 0)
            if incoming >= me["hp"] * .8:
                continue
            benefit = 100 + (1 - me["hp"] / me["max_hp"]) * 180
            score = benefit - travel * .5 - dwell * 5 - risk
            if key == self.resource_key:
                score += 15
            if score > 0:
                candidates.append((score, point, "drop", key, drop))
        return max(candidates, default=None, key=lambda c: c[0])

    def movement(self, obs, navigation, threats, s, urgent, deadline, goal=None,
                 boost_emergency=False, shot_energy=0.0):
        if time.perf_counter() >= deadline:
            # Keep a short verified route if optional tactical work has expired.
            path = self.tactical.rollout(obs["self"], navigation, False, s)[:4]
            if all(self.map.move_clear(a[1:4], b[1:4], s["radius"], s["height"])
                   for a, b in zip(path, path[1:])):
                return navigation, False
            return (0.0, 0.0), False
        return self.tactical.choose(obs, navigation, threats, s, goal=goal,
                                    recover=self.recover, urgent=urgent,
                                    spacing_boost=self.spacing_boost, deadline=deadline,
                                    boost_emergency=boost_emergency, shot_energy=shot_energy)

    def act(self, obs):
        start = time.perf_counter()
        deadline = start + .032
        me, t = obs["self"], obs["t"]
        self.spacing_boost = False
        self.update(obs)
        s = self.stats(me)
        threats = self.threats(obs, s)
        visible = [q for q in threats if q["los"] and q["actor"]["kind"] == "mech"]
        hp = me["hp"] / me["max_hp"]
        if hp < .55 or (len(visible) >= 2 and hp < .82):
            self.recover = True
        if hp >= .93 or (obs["zone"]["radius"] < 18 and visible):
            self.recover = False
        zone = obs["zone"]
        center, future_radius = self.zone_future(obs, 12)
        p = me["pos"]
        urgent = not me["in_zone"] or distance(p, center) + s["radius"] + 8 > future_radius
        safety = self.finish_safety.evaluate(
            obs, threats, s, recovering=self.recover, urgent=urgent,
            repair_before_finish=lambda actor: self.repair_before_projected_finish(obs, actor))
        decision = self.engagement.select(obs, threats, safe_finish=safety.allows,
                                          finish_budget_s=safety.budget_s,
                                          recovering=self.recover)
        target = decision.target or self.npc_defense_target(obs, threats)
        defending_npc = target is not None and target.get("kind") == "npc"
        # Defensive fire and movement are separate. A quiet mech can influence
        # spacing without becoming a target or receiving the first shot.
        spacing_target = target
        if spacing_target is None and visible:
            spacing_target = max(visible, key=lambda q: q["risk"])["actor"]
        resource = self.resource_goal(obs, threats, deadline=min(deadline - .017, time.perf_counter() + .004)) if not urgent and decision.mode != "FINISH" else None
        if resource and target is not None:
            close_attacker = distance(p, target["pos"]) < 120
            if resource[2] in ("crates", "npc") or (close_attacker and not self.recover):
                resource = None
        self.resource_key = resource[3] if resource else None
        if urgent:
            self.mode = "rotate"
        elif resource:
            self.mode = "loot"
        elif self.recover:
            self.mode = "recover"
        else:
            self.mode = "engage" if target else "position"
        self.state = ("ROTATE" if urgent else "RECOVER" if self.recover else
                      "DEFEND" if defending_npc else decision.mode)
        if urgent or (self.recover and not resource) or (not spacing_target and not resource):
            if self.goal is None or t >= self.goal_until or self.goal_kind != self.mode or distance(self.goal, center) > future_radius:
                self.goal = self.safe_goal(obs, threats, s, deadline - .013)
                self.goal_until = t + (1.2 if urgent or self.recover else 8)
                self.goal_kind = self.mode
            goal = self.goal
        elif resource:
            goal = resource[1]
            self.goal, self.goal_kind = goal, "loot"
            if resource[2] == "crates" and distance(p, goal) < 65:
                target = {**resource[4], "kind": "crate", "vel": [0, 0, 0]}
                # The muzzle cannot pitch down enough to hit a crate at our feet.
                d = distance(p, goal)
                ux, uy = unit(p[0] - goal[0], p[1] - goal[1])
                if d < .01:
                    ux, uy = -math.cos(me["aim"][0]), -math.sin(me["aim"][0])
                standoff = max(14.0, (s["muzzle_height"] - self.config["crates"].get("height", 2.4) * .5) / max(.1, -math.tan(s["min_pitch"])) + 4)
                if standoff - 2 <= d <= standoff + 3:
                    goal = list(p)
                else:
                    goal = [goal[0] + ux * standoff, goal[1] + uy * standoff, p[2]]
            if resource[2] == "drop" and distance(p, goal) < resource[4]["radius"] - s["radius"] * .3:
                goal = list(p)
            if resource[2] == "npc":
                target = resource[4]
                ux, uy = unit(p[0] - goal[0], p[1] - goal[1])
                goal = [goal[0] + ux * 30, goal[1] + uy * 30, p[2]]
        else:
            q = spacing_target
            d = distance(p, q["pos"])
            held = {w["kind"] for w in me["weapons"] if w}
            # At 120 m a 252 m/s gun round affords ~0.48 s to dodge; at
            # 70 m only ~0.28 s. Charging needs extra room for its slowdown.
            preferred = 150 if "laser" in held else 120
            if q.get("kind") == "npc":
                preferred = 35
            if target is not None and "lightning" in held and hp > .7 and self.lightning_commit(obs, q, len(visible)):
                preferred = 33 if "laser" in q.get("weapons", []) else 38
            if len(visible) >= 2:
                preferred += 35
            if "lightning" in q.get("weapons", []) and "lightning" not in held:
                preferred = max(80, preferred)
            ux, uy = unit(q["pos"][0] - p[0], q["pos"][1] - p[1])
            # Match an approaching enemy's radial velocity before adding strafe.
            # Fixed strafing otherwise makes retreat slower than its pursuit.
            velocity = q.get("vel", [0, 0, 0])
            closing_velocity = velocity[0] * ux + velocity[1] * uy
            radial = clamp((closing_velocity + .6 * (d - preferred)) / s["walk_speed"], -1, 1)
            if q.get("kind") == "mech":
                # Observation, self-defense and short finishes never authorize
                # chasing a mech that is withdrawing or beyond our spacing band.
                radial = min(0.0, radial)
            self.spacing_boost = radial < -.92 and d < preferred + 8
            tangent = .8 * math.sqrt(max(0, 1 - radial * radial))
            if t - self.last_strafe > 2.8:
                self.strafe *= -1
                self.last_strafe = t
            dx, dy = unit(ux * radial - uy * tangent * self.strafe, uy * radial + ux * tangent * self.strafe)
            goal = [p[0] + dx * 20, p[1] + dy * 20, p[2]]
        allow_fire = False
        fire_reason = decision.reason
        if target is not None and target.get("kind") == "mech":
            allow_fire = decision.allow_fire and decision.target is not None and decision.target["id"] == target["id"]
        elif target is not None:
            farming = resource is not None and resource[2] in ("crates", "npc") and not self.recover
            allow_fire = defending_npc or farming
            fire_reason = "attributed_npc_attack" if defending_npc else "safe_farming" if farming else "quiet_recovery"
        self.target_id = target.get("id") if target else None
        protected_ids = {a["id"] for a in obs.get("mechs", []) if a.get("kind") == "mech"
                         and (target is None or a["id"] != target.get("id") or not allow_fire)}
        quiet_reload = True
        for q in threats:
            if not q["los"]:
                continue
            actor = q["actor"]
            if actor.get("kind") == "npc":
                reach = self.config["npc"]["aggro_range"] + 15
            else:
                reach = max((self.config["weapons"].get(kind, {}).get("range", 250)
                             for kind in actor.get("weapons", ["gun"])), default=230) + 20
            if q["d"] <= reach:
                quiet_reload = False
                break
        combat = self.combat.plan(obs, target, allow_fire=allow_fire, emergency=urgent or self.recover,
                                  protected_ids=protected_ids, quiet_reload=quiet_reload)
        navigation = self.map.navigate(p, goal, s["radius"], s["height"], deadline=deadline - .012)
        self.check_route_progress(obs, goal, navigation, bool(visible))
        if distance(p, goal) < 1.5:
            navigation = (0, 0)
        motion_weapons = [({**w, "charge": max(.001, w.get("charge", 0)) if combat["fire"][i] else 0}
                           if w and w["kind"] == "laser" else w)
                          for i, w in enumerate(me["weapons"])]
        motion_obs = {**obs, "self": {**me, "weapons": motion_weapons}}
        edge_center, edge_radius = self.zone_future(obs, 1.0)
        boost_emergency = not me["in_zone"] or distance(p, edge_center) + s["radius"] + 1 > edge_radius
        shot_energy = sum(w["stats"].get("energy", 3) for i, w in enumerate(me["weapons"])
                          if w and w["kind"] == "lightning" and combat["fire"][i])
        move, boost = self.movement(motion_obs, navigation, threats, s, urgent, deadline, goal,
                                    boost_emergency=boost_emergency, shot_energy=shot_energy)
        if self.state == "FINISH":
            # Elective damage must not consume the movement reserve. The mortar
            # drain stat affects its victim; only lightning costs firing energy.
            reserve = max(35.0, s["boost_drain"] * 1.25 + 12)
            boost_cost = s["boost_drain"] * self.combat.action_dt if boost else 0.0
            if me["energy"] - boost_cost < reserve:
                boost, boost_cost = False, 0.0
            available = me["energy"] - boost_cost - reserve
            for slot, weapon in enumerate(me["weapons"]):
                if weapon and weapon["kind"] == "lightning" and combat["fire"][slot]:
                    cost = weapon["stats"].get("energy", 3)
                    if available < cost:
                        combat["fire"][slot] = False
                    else:
                        available -= cost
        stuck = bool(len(self.history) > 8 and t - self.history[0][0] > 1.3 and distance(p, self.history[0][1]) < 1.3 and sum(h[2] for h in self.history) > len(self.history) * .6)
        jump = False
        if stuck:
            if resource:
                self.blacklist[resource[3]] = t + 12
            self.goal_until = -1
            if me["grounded"] and me["energy"] > 40 and t - self.last_jump > 3:
                jump, self.last_jump = True, t
        releasing_charge = not allow_fire and any(w and w["kind"] == "laser" and w.get("charge", 0) > 0 for w in me["weapons"])
        if (target is None or not allow_fire) and not releasing_charge:
            # Turn toward received fire, otherwise scan instead of staring at the destination.
            if t - self.last_hurt < 3 and self.damage_bearing is not None:
                combat["aim"] = [self.damage_bearing, me["aim"][1]]
            elif threats:
                enemy = max(threats, key=lambda q: q["risk"])["actor"]
                combat["aim"] = [math.atan2(enemy["pos"][1] - p[1], enemy["pos"][0] - p[0]), 0]
            else:
                sounds = [a for a in obs.get("sounds", []) if a["kind"] in ("gun", "laser_charge", "mortar", "lightning")]
                combat["aim"] = [sounds[-1]["bearing"] if sounds else me["aim"][0] + .4, 0]
        if (self.recover and not any(combat["fire"])
                and not any(w and w.get("charge", 0) > 0 for w in me["weapons"])
                and any(w and w["kind"] == "gun" and w.get("reload", 0) > .3 for w in me["weapons"])):
            combat["aim"] = [self.defensive_yaw(obs, threats), 0]
        action = {"tick": obs["tick"], "move": list(move), "boost": boost, "jump": jump, **combat}
        upgrade = self.choose_upgrade(obs)
        if upgrade is not None:
            action["pick"] = upgrade
        action.update(self.take_weapon(obs))
        self.last_move = move
        self.telemetry = {"mode": self.mode, "state": self.state, "goal": goal, "resource": self.resource_key,
                          "target": target.get("id") if target else None,
                          "target_hp": target.get("hp") if target else None,
                          "allow_fire": allow_fire, "fire_reason": fire_reason,
                          "quiet_reload": quiet_reload,
                          "engagement": {"mode": decision.mode, "confidence": decision.confidence,
                                         "evidence_age": decision.evidence_age, "finish_eta": decision.finish_eta,
                                         "budget_s": decision.finish_budget_s, "exclusions": decision.exclusions},
                          "finish_safety": safety.reasons,
                          "route_status": getattr(self.map, "last_route_status", None),
                          "escape_anchor": getattr(safety, "escape_anchor", None),
                          "safety_ms": getattr(safety, "elapsed_ms", None),
                          "recover": self.recover, "threats": len(visible), "stuck": stuck,
                          "tactical": self.tactical.last_report, "ms": (time.perf_counter() - start) * 1000}
        return action


if __name__ == "__main__":
    mf.run(Bot)
