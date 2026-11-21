"""Labubu's adaptive survival controller for the official mechfight/1 protocol."""
from __future__ import annotations

import math
import time
from collections import deque

import mechfight as mf
from arena_map import ArenaMap
from combat import Combat


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
        self.slot = hello["slot"]
        self.recover = False
        self.mode = "explore"
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

    def stats(self, me):
        return {**self.config["mech"], **me.get("stats", {})}

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
        if t >= self.visit_t + 1:
            cell = (int(me["pos"][0] // 35), int(me["pos"][1] // 35))
            self.visited[cell] = self.visited.get(cell, 0) + 1
            self.visit_t = t
        for event in obs.get("events", []):
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
        me = obs["self"]
        ranged = max((w["stats"].get("range", 230) for w in me["weapons"] if w and w["kind"] != "mortar"), default=230)
        targets = [q for q in threats if q["los"] and q["d"] < ranged]
        if not targets:
            return None
        close_mech = any(q["actor"]["kind"] == "mech" and q["d"] < 90 for q in targets)
        attacking_npcs = [q for q in targets if q["actor"]["kind"] == "npc" and q["d"] <= 60 and obs["t"] - self.recent_attackers.get(q["actor"]["id"], -100) < 3]
        if attacking_npcs and not close_mech:
            # Clear an actual nearby attacker before trading shots at distant mechs.
            return min(attacking_npcs, key=lambda q: (q["actor"].get("hp", 350), q["d"]))["actor"]
        def value(q):
            a = q["actor"]
            hp = a.get("hp", a.get("max_hp", 1400))
            threat = 2.0 if a.get("kind") == "mech" else .4
            return threat + q["risk"] + 1.6 * (1 - hp / max(a.get("max_hp", 1400), 1)) - .006 * q["d"]
        return max(targets, key=value)["actor"]

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

    def position_cost(self, point, threats, center, radius, body_radius, recovering=False):
        # Scores are strategy parameters, not claimed probabilities or game constants.
        outside = max(0.0, distance(point, center) + body_radius + 4 - radius)
        score = outside * 9.0
        height = self.config["mech"]["muzzle_height"]
        origin = [point[0], point[1], point[2] + height]
        for q in threats[:5]:
            actor = q["actor"]
            d = distance(point, actor["pos"])
            if d < 260 and self.map.line_of_fire(origin, self.actor_center(actor)):
                score += q["risk"] * (55 if recovering else 16)
                score += max(0, 65 - d) * (1.3 if recovering else .35)
                if recovering:
                    reach = max((self.config["weapons"].get(kind, {}).get("range", 230) for kind in actor.get("weapons", ["gun"])), default=230)
                    score += q["risk"] * 90 * max(0, 1 - d / max(1, reach))
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
            cost = self.position_cost(point, threats, center, radius, s["radius"], self.recover)
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

    def resource_goal(self, obs, threats):
        me, t = obs["self"], obs["t"]
        p = me["pos"]
        if any(q["los"] and q["d"] < 90 and q["actor"]["kind"] == "mech" for q in threats):
            return None
        center, radius = self.zone_future(obs, 18)
        candidates = []
        held = {w["kind"] for w in me["weapons"] if w}
        ranks = self.weapon_rank(obs)
        for key, (item, seen) in self.loot.items():
            if key in self.blacklist:
                continue
            d = distance(p, item["pos"])
            if d > 125 or abs(item["pos"][2] - self.map.ground_height(*item["pos"][:2])) > 3:
                continue
            if distance(item["pos"], center) > radius - 10:
                continue
            kind = key[0]
            if kind == "cubes":
                benefit = 55 if me["cubes"] < 10 else 15
            elif kind == "pickups":
                if item["kind"] in held or item["kind"] == "gun":
                    continue
                if all(w is not None for w in me["weapons"]):
                    replacements = [w for w in me["weapons"] if w["kind"] != "gun" and not w.get("charge", 0) and ranks.get(item["kind"], 0) > ranks.get(w["kind"], 0)]
                    if not replacements:
                        continue
                benefit = {"laser": 74, "lightning": 58, "mortar": 40}.get(item["kind"], 0)
            else:
                if me["hp"] < .86 * me["max_hp"] or me["cubes"] >= 10:
                    continue
                benefit = 36
            if any(distance(item["pos"], q["actor"]["pos"]) < 65 for q in threats if q["actor"]["kind"] == "mech"):
                continue
            score = benefit - .6 * d - .25 * (t - seen)
            if score > 0:
                candidates.append((score, list(item["pos"]), kind, key, item))
        # Drops are opportunistic restoration, never an unconditional destination.
        for drop in obs.get("drops", []):
            d = distance(p, drop["pos"])
            if d > 90 or drop["lands_in"] > 7 or any(distance(drop["pos"], q["actor"]["pos"]) < 100 for q in threats):
                continue
            if distance(drop["pos"], center) > radius - 12:
                continue
            benefit = 45 + (1 - me["hp"] / me["max_hp"]) * 80
            candidates.append((benefit - d * .6, list(drop["pos"]), "drop", ("drop", drop["id"]), drop))
        return max(candidates, default=None, key=lambda c: c[0])

    def movement(self, obs, navigation, threats, s, urgent, deadline):
        me, t = obs["self"], obs["t"]
        p = me["pos"]
        speed = s["walk_speed"]
        boost = me["energy"] > (12 if urgent else 35) and (urgent or self.spacing_boost or (self.recover and any(q["los"] for q in threats)))
        if boost:
            speed = s["boost_speed"]
        angles = [math.atan2(navigation[1], navigation[0]) + offset for offset in (0, .35, -.35, .7, -.7, 1.1, -1.1, 1.57, -1.57, 2.2, -2.2, math.pi)]
        directions = [(math.cos(a), math.sin(a)) for a in angles]
        if math.hypot(*navigation) < .1:
            directions = [(0.0, 0.0)] + directions
        else:
            directions.append((0.0, 0.0))
        c, radius = self.zone_future(obs, .8)
        projectiles = sorted(obs.get("projectiles", []), key=lambda q: distance(q["pos"], p))[:16]
        best, best_score = navigation, float("inf")
        found = False
        tested = 0
        for dx, dy in directions:
            if time.perf_counter() > deadline:
                break
            tested += 1
            endpoint = [p[0] + dx * speed * .48, p[1] + dy * speed * .48, p[2]]
            if (dx or dy) and not self.map.move_clear(p, endpoint, s["radius"], s["height"]):
                continue
            found = True
            score = -7 * (dx * navigation[0] + dy * navigation[1])
            if not dx and not dy:
                score += 1 if math.hypot(*navigation) > .1 else -4
            score += max(0, distance(endpoint, c) + s["radius"] + 2 - radius) * (12 if urgent else 6)
            # Each candidate uses actual acceleration over the first half-second.
            accel = s["ground_accel"] if me["grounded"] else s["air_accel"]
            vx = me["vel"][0] + clamp(dx * speed - me["vel"][0], -accel * .3, accel * .3)
            vy = me["vel"][1] + clamp(dy * speed - me["vel"][1], -accel * .3, accel * .3)
            for bullet in projectiles:
                bp, bv = bullet["pos"], bullet["vel"]
                rx, ry = bp[0] - p[0], bp[1] - p[1]
                ux, uy = bv[0] - vx, bv[1] - vy
                closest_t = clamp(-(rx * ux + ry * uy) / max(ux * ux + uy * uy, .001), 0, .65)
                miss = math.hypot(rx + ux * closest_t, ry + uy * closest_t)
                gravity = self.config["weapons"]["mortar"]["gravity"] if bullet["kind"] == "mortar" else 0
                bz = bp[2] + bv[2] * closest_t - .5 * gravity * closest_t * closest_t
                if p[2] - 2 <= bz <= p[2] + s["height"] + 2:
                    danger_radius = s["radius"] + (self.config["weapons"]["mortar"]["splash_radius"] if bullet["kind"] == "mortar" else 1.0)
                    score += max(0, danger_radius - miss) * (11 if bullet["kind"] == "mortar" else 8)
            for q in threats[:4]:
                a = q["actor"]
                if a.get("charging") and q["los"]:
                    yaw = a["aim"][0]
                    rx, ry = endpoint[0] - a["pos"][0], endpoint[1] - a["pos"][1]
                    if rx * math.cos(yaw) + ry * math.sin(yaw) > 0:
                        miss = abs(rx * math.sin(yaw) - ry * math.cos(yaw))
                        score += max(0, s["radius"] + 3 - miss) * 9
            if score < best_score:
                best, best_score = (dx, dy), score
        if tested == 0 and math.hypot(*navigation) > .1:
            # Keep a collision-checked route when the optional dodge search expires.
            endpoint = [p[0] + navigation[0] * speed * .25, p[1] + navigation[1] * speed * .25, p[2]]
            if self.map.move_clear(p, endpoint, s["radius"], s["height"]):
                return navigation, boost
        return (best if found else (0.0, 0.0)), boost

    def act(self, obs):
        start = time.perf_counter()
        deadline = start + .026
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
        target = self.choose_target(obs, threats)
        zone = obs["zone"]
        center, future_radius = self.zone_future(obs, 12)
        p = me["pos"]
        urgent = not me["in_zone"] or distance(p, center) + s["radius"] + 8 > future_radius
        resource = self.resource_goal(obs, threats) if not urgent and not self.recover else None
        if urgent:
            self.mode = "rotate"
        elif self.recover:
            self.mode = "recover"
        elif resource:
            self.mode = "loot"
        else:
            self.mode = "engage" if target else "position"
        if urgent or self.recover or (not target and not resource):
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
        else:
            q = target
            d = distance(p, q["pos"])
            held = {w["kind"] for w in me["weapons"] if w}
            preferred = 100 if "laser" in held else 70
            if q.get("kind") == "npc":
                preferred = 35
            if "lightning" in held and "laser" in q.get("weapons", []) and hp > .7:
                preferred = 33
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
            self.spacing_boost = radial < -.92 and d < preferred + 8
            tangent = .8 * math.sqrt(max(0, 1 - radial * radial))
            if t - self.last_strafe > 2.8:
                self.strafe *= -1
                self.last_strafe = t
            dx, dy = unit(ux * radial - uy * tangent * self.strafe, uy * radial + ux * tangent * self.strafe)
            goal = [p[0] + dx * 20, p[1] + dy * 20, p[2]]
        navigation = self.map.navigate(p, goal, s["radius"], s["height"], deadline=deadline - .006)
        if distance(p, goal) < 1.5:
            navigation = (0, 0)
        move, boost = self.movement(obs, navigation, threats, s, urgent, deadline)
        stuck = bool(len(self.history) > 8 and t - self.history[0][0] > 1.3 and distance(p, self.history[0][1]) < 1.3 and sum(h[2] for h in self.history) > len(self.history) * .6)
        jump = False
        if stuck:
            if resource:
                self.blacklist[resource[3]] = t + 12
            self.goal_until = -1
            if me["grounded"] and me["energy"] > 40 and t - self.last_jump > 3:
                jump, self.last_jump = True, t
        imminent = any(q["los"] and q["d"] < 28 for q in threats)
        active_contact = target is not None and target.get("kind") == "mech" and t - self.last_weapon_hurt < min(3.0, s["regen_delay"])
        active_contact = active_contact and any(q["actor"]["id"] == target["id"] and q["los"] for q in threats)
        if target is not None and target.get("kind") == "npc":
            active_contact = t - self.recent_attackers.get(target["id"], -100) < min(3.0, s["regen_delay"]) and not any(q["actor"]["kind"] == "mech" and q["los"] and q["d"] < 90 for q in threats)
        allow_fire = not self.recover or imminent or active_contact
        combat = self.combat.plan(obs, target, allow_fire=allow_fire, emergency=urgent or self.recover)
        if target is None or not allow_fire:
            # Turn toward received fire, otherwise scan instead of staring at the destination.
            if t - self.last_hurt < 3 and self.damage_bearing is not None:
                combat["aim"] = [self.damage_bearing, me["aim"][1]]
            elif threats:
                enemy = max(threats, key=lambda q: q["risk"])["actor"]
                combat["aim"] = [math.atan2(enemy["pos"][1] - p[1], enemy["pos"][0] - p[0]), 0]
            else:
                sounds = [a for a in obs.get("sounds", []) if a["kind"] in ("gun", "laser_charge", "mortar", "lightning")]
                combat["aim"] = [sounds[-1]["bearing"] if sounds else me["aim"][0] + .4, 0]
        action = {"tick": obs["tick"], "move": list(move), "boost": boost, "jump": jump, **combat}
        upgrade = self.choose_upgrade(obs)
        if upgrade is not None:
            action["pick"] = upgrade
        action.update(self.take_weapon(obs))
        self.last_move = move
        self.telemetry = {"mode": self.mode, "goal": goal, "recover": self.recover, "threats": len(visible), "stuck": stuck, "ms": (time.perf_counter() - start) * 1000}
        return action


if __name__ == "__main__":
    mf.run(Bot)
