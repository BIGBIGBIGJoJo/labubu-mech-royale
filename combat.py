"""Bounded, dependency-free weapon control for mechfight/1.

Combat.plan does no I/O and never mutates the observation. A supplied
line_of_fire(start, end) must return True for an unobstructed world segment.
Without that callback geometry is unknown and segments are treated as clear.

Setting allow_fire=False releases every trigger. An already charging laser can
therefore emit one beam: the documented protocol has no charge-cancel action.
"""
from __future__ import annotations

import copy
import math


def angle_delta(a, b):
    """Signed shortest rotation from b to a."""
    return (a - b + math.pi) % (2.0 * math.pi) - math.pi


def direction(aim):
    cp = math.cos(aim[1])
    return (cp * math.cos(aim[0]), cp * math.sin(aim[0]), math.sin(aim[1]))


def point_aim(origin, point):
    dx, dy, dz = (point[i] - origin[i] for i in range(3))
    return [math.atan2(dy, dx), math.atan2(dz, math.hypot(dx, dy))]


def intercept_time(relative, velocity, speed):
    """First positive constant-velocity interception time, or None."""
    a = sum(v * v for v in velocity) - speed * speed
    b = 2.0 * sum(r * v for r, v in zip(relative, velocity))
    c = sum(r * r for r in relative)
    if c < 1e-8:
        return 0.0
    if abs(a) < 1e-8:
        return -c / b if b < -1e-8 else None
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    # Stable quadratic roots avoid cancellation for extreme speed ratios.
    q = -0.5 * (b + math.copysign(root, b))
    roots = (q / a, c / q) if abs(q) > 1e-12 else (-b / (2.0 * a),)
    positive = [t for t in roots if t >= 0.0 and math.isfinite(t)]
    return min(positive) if positive else None


class Combat:
    def __init__(self, config, line_of_fire=None):
        self.config = config
        self.line_of_fire = line_of_fire
        self.sim_dt = 1.0 / max(1.0, float(config.get("match", {}).get("tick_hz", 20)))
        self.action_dt = self.sim_dt * max(1, int(config.get("match", {}).get("decide_every", 2)))
        self._full_since = {}
        self._mortar_slot = None
        self._mortar_target = None
        self._mortar_until = -1.0
        self._mortar_retry_at = -1.0
        self.last_report = None
        # Enemy armor is not part of the standard actor observation. Bound it
        # using all configured armor upgrades instead of assuming zero armor.
        armor = max(0.0, float(config.get("mech", {}).get("armor", 0)))
        armor_multiplier = 1.0
        for upgrade in config.get("upgrades", []):
            stacks = max(0, int(upgrade.get("max", 1)))
            for effect in upgrade.get("effects", []):
                if effect.get("path") == "mech.armor":
                    armor += max(0.0, effect.get("add", 0.0)) * stacks
                    armor_multiplier *= max(1.0, effect.get("mul", 1.0)) ** stacks
        self.max_enemy_armor = min(0.95, armor * armor_multiplier)

    def _clear(self, start, end):
        return self.line_of_fire is None or bool(self.line_of_fire(start, end))

    def _stats(self, weapon):
        stats = dict(self.config.get("weapons", {}).get(weapon["kind"], {}))
        stats.update(weapon.get("stats", {}))
        return stats

    def _body(self, target):
        kind = target.get("kind", "mech")
        if kind == "npc":
            base = self.config.get("npc", {})
            return float(base.get("radius", 1.8)), float(base.get("height", 3.5))
        if kind == "crate":
            base = self.config.get("crates", {})
            return float(base.get("radius", 1.4)), float(base.get("height", 2.4))
        base = self.config.get("mech", {})
        scale = 1.0 + self.config.get("cubes", {}).get("size_per_cube", 0.05) * target.get("cubes", 0)
        return float(base.get("radius", 2.5)) * scale, float(base.get("height", 9.0)) * scale

    def _self_stats(self, me):
        stats = dict(self.config.get("mech", {}))
        stats.update(me.get("stats", {}))
        scale = 1.0 + self.config.get("cubes", {}).get("size_per_cube", 0.05) * me.get("cubes", 0)
        # Live stats retain the pre-cube radius/height, whereas eye and muzzle
        # heights already include cube growth. Scale these two groups once.
        for key, default in (("radius", 2.5), ("height", 9.0)):
            stats[key] = stats.get(key, default) * scale
        for key, default in (("eye_height", 8.0), ("muzzle_height", 7.0)):
            if key not in me.get("stats", {}):
                stats[key] = self.config.get("mech", {}).get(key, default) * scale
        return stats

    def _slewed(self, actual, command, stats, seconds=None):
        seconds = self.sim_dt if seconds is None else seconds
        yaw_step = max(0.0, stats.get("turn_rate", 4.0)) * seconds
        pitch_step = max(0.0, stats.get("pitch_rate", 3.0)) * seconds
        dy = max(-yaw_step, min(yaw_step, angle_delta(command[0], actual[0])))
        dp = max(-pitch_step, min(pitch_step, command[1] - actual[1]))
        return [actual[0] + dy, actual[1] + dp]

    def laser_damage_bound(self, me, stats, target, charge):
        """Conservative laser damage for deciding an early lethal release.

        Weapon stats already contain weapon upgrades. Cube damage remains a
        separate documented multiplier. NPCs/crates have no armor; unknown
        mech armor is bounded by the configured upgrade pool. Rear bonus is
        deliberately omitted because the opponent can turn before impact.
        """
        full = max(1e-6, float(stats.get("charge", 0.75)))
        fraction = stats.get("min_frac", 0.35)
        amount = stats.get("damage", 315.0) * (fraction + (1 - fraction) * min(1.0, max(0.0, charge) / full))
        cube_config = self.config.get("cubes", {})
        amount *= 1 + cube_config.get("damage_per_cube", 0.04) * min(me.get("cubes", 0), cube_config.get("stat_cap", 10))
        if target.get("kind", "mech") == "mech":
            armor = target.get("armor", target.get("stats", {}).get("armor", self.max_enemy_armor))
            if not isinstance(armor, (int, float)) or not math.isfinite(armor):
                armor = self.max_enemy_armor
            amount *= 1 - max(0.0, min(0.95, armor))
            if "mortar" in target.get("weapons", []):
                amount *= 1 + stats.get("cookoff", 0.6)
        return amount

    def _laser_lethal(self, me, stats, target, charge):
        hp = target.get("hp")
        return (isinstance(hp, (int, float)) and math.isfinite(hp) and hp > 0
                and charge >= stats.get("min_charge", 0.15) - 1e-6
                and self.laser_damage_bound(me, stats, target, charge) >= hp + 1e-6)

    def _aligned(self, actual_next, solution, radius, height, projectile_radius=0.0):
        distance = max(0.01, solution["horizontal"])
        yaw_tolerance = math.atan2(radius * 0.80 + projectile_radius, distance)
        half_height = height * 0.40 + projectile_radius
        center_z = solution.get("center_z", solution["point"][2])
        pitch_low = math.atan2(center_z - half_height - solution["origin"][2], distance)
        pitch_high = math.atan2(center_z + half_height - solution["origin"][2], distance)
        return (abs(angle_delta(solution["aim"][0], actual_next[0])) <= yaw_tolerance
                and pitch_low <= actual_next[1] <= pitch_high)

    def _direct_solution(self, kind, stats, origin, center, velocity, barrel_offset, limits, target_height):
        speed = float(stats.get("speed", 252.0))
        # All shots have a small muzzle extension. Re-solve the gun intercept
        # twice after applying it; a translated origin matters at close range.
        shot_origin = list(origin)
        flight = 0.0
        predicted = list(center)
        for _ in range(2):
            if kind == "gun":
                relative = [center[i] - shot_origin[i] for i in range(3)]
                flight = intercept_time(relative, velocity, speed)
                if flight is None:
                    return None
            predicted = [center[i] + velocity[i] * flight for i in range(3)]
            if kind != "lightning":
                # Large cube-scaled mechs can be too tall to aim at another
                # actor's center at short range while its upper body remains
                # hittable. Intersect the pitch envelope with the body interior.
                horizontal = math.dist(shot_origin[:2], predicted[:2])
                low = max(predicted[2] - target_height * 0.40,
                          shot_origin[2] + math.tan(limits[0]) * horizontal)
                high = min(predicted[2] + target_height * 0.40,
                           shot_origin[2] + math.tan(limits[1]) * horizontal)
                if low > high + 1e-8:
                    return None
                predicted[2] = max(low, min(high, predicted[2]))
            aim = point_aim(shot_origin, predicted)
            vec = direction(aim)
            shot_origin = [origin[i] + barrel_offset * vec[i] for i in range(3)]
        aim = point_aim(shot_origin, predicted)
        distance = math.dist(shot_origin, predicted)
        if distance > stats.get("range", 230.0) or (kind != "lightning" and not limits[0] - 1e-7 <= aim[1] <= limits[1] + 1e-7):
            return None
        aim[1] = max(limits[0], min(limits[1], aim[1]))
        # Check the muzzle extension as well: a wall can shorten the barrel.
        clear = self._clear(origin, predicted)
        center_z = center[2] + velocity[2] * flight
        if not clear and kind in ("gun", "laser"):
            # A remembered actor's center may be hidden by a low wall while a
            # meaningful part of its upper or lower body remains hittable.
            for height_fraction in (0.39, -0.39):
                alternate = [predicted[0], predicted[1], center_z + target_height * height_fraction]
                alternate_aim = point_aim(origin, alternate)
                if not limits[0] <= alternate_aim[1] <= limits[1] or not self._clear(origin, alternate):
                    continue
                vec = direction(alternate_aim)
                alternate_origin = [origin[i] + barrel_offset * vec[i] for i in range(3)]
                alternate_distance = math.dist(alternate_origin, alternate)
                if alternate_distance > stats.get("range", 230.0):
                    continue
                predicted, shot_origin, aim = alternate, alternate_origin, alternate_aim
                distance, clear = alternate_distance, True
                break
        return {"aim": aim, "point": predicted, "origin": shot_origin,
                "horizontal": math.dist(shot_origin[:2], predicted[:2]),
                "distance": distance, "clear": clear, "flight": flight, "center_z": center_z}

    def _mortar_solution(self, stats, origin, center, velocity, me, self_stats, limits):
        speed = float(stats.get("speed", 72.0))
        gravity = float(stats.get("gravity", 22.0))
        if speed <= 0 or gravity <= 0:
            return None
        point = list(center)
        flight = 0.0
        for _ in range(4):
            dx, dy, dz = (point[i] - origin[i] for i in range(3))
            horizontal = math.hypot(dx, dy)
            if horizontal < max(15.0, stats.get("splash_radius", 7.0) + self_stats["radius"] + 3.0):
                return None
            discriminant = speed ** 4 - gravity * (gravity * horizontal ** 2 + 2.0 * dz * speed ** 2)
            if discriminant < 0.0:
                return None
            pitch = math.atan2(speed * speed - math.sqrt(discriminant), gravity * horizontal)
            if not limits[0] <= pitch <= limits[1]:
                return None
            flight = horizontal / max(1e-8, speed * math.cos(pitch))
            if flight > stats.get("ttl", 7.0):
                return None
            point = [center[i] + velocity[i] * flight for i in range(3)]
        aim = [math.atan2(point[1] - origin[1], point[0] - origin[0]), pitch]
        vec = direction(aim)
        previous = list(origin)
        # Fixed work bound. A conservative extra collision margin belongs in
        # the arena segment checker, which has the actual terrain geometry.
        for step in range(1, 17):
            t = flight * step / 16.0
            sample = [origin[i] + speed * vec[i] * t for i in range(3)]
            sample[2] -= 0.5 * gravity * t * t
            if not self._clear(previous, sample):
                return None
            previous = sample
        future_self = [me["pos"][i] + me.get("vel", [0, 0, 0])[i] * flight for i in range(3)]
        safety = stats.get("splash_radius", 7.0) + self_stats["radius"] + 3.0
        if min(math.dist(me["pos"][:2], point[:2]), math.dist(future_self[:2], point[:2])) < safety:
            return None
        return {"aim": aim, "point": point, "origin": origin,
                "horizontal": math.dist(origin[:2], point[:2]),
                "distance": math.dist(origin, point), "clear": True, "flight": flight}

    def plan(self, obs, target, allow_fire=True, emergency=False):
        # Optional movement consumers may reuse this call's gun geometry.
        # Clear it before every early return; it is never a firing permission.
        self.last_report = None
        me = obs["self"]
        weapons = list(me.get("weapons", [None, None]))[:2]
        weapons += [None] * (2 - len(weapons))
        own = self._self_stats(me)
        actual = list(me.get("aim", [0.0, 0.0]))
        action = {"aim": actual, "fire": [False, False], "reload": False}
        now = float(obs.get("t", obs.get("tick", 0) * self.sim_dt))
        # Early reload while recovering or with no target; there is no benefit
        # to partial magazines during an otherwise idle interval.
        for weapon in weapons:
            if weapon and weapon["kind"] == "gun" and not weapon.get("reload", 0):
                stats = self._stats(weapon)
                ammo = weapon.get("ammo", stats.get("mag", 12))
                if ammo <= 0 or ((target is None or not allow_fire) and ammo < stats.get("mag", 12)):
                    action["reload"] = True
        if target is None or not allow_fire:
            self._full_since.clear()
            self._mortar_slot = None
            return action
        if emergency:
            self._mortar_slot = None

        radius, height = self._body(target)
        velocity = list(target.get("vel", [0.0, 0.0, 0.0]))
        center = list(target["pos"])
        center[2] += height * 0.5
        origin = list(me["pos"])
        origin[2] += own.get("muzzle_height", 7.0)
        limits = (own.get("min_pitch", -0.7), own.get("max_pitch", 1.3))
        solutions, stats_by_slot, ready, fire_delay = {}, {}, {}, {}
        for slot, weapon in enumerate(weapons):
            if not weapon:
                continue
            kind = weapon["kind"]
            stats = stats_by_slot[slot] = self._stats(weapon)
            ready_in = max(0.0, weapon.get("cooldown", 0.0))
            if kind == "gun":
                ready_in = max(ready_in, weapon.get("reload", 0.0))
            ready[slot] = ready_in <= self.action_dt + 1e-6
            # Actions remain held for decide_every simulation ticks. Predict
            # torso slew at the first tick on which this weapon can fire, not
            # always at the first tick and not at an arbitrarily later tick.
            fire_delay[slot] = min(self.action_dt, max(self.sim_dt, math.ceil((ready_in - 1e-8) / self.sim_dt) * self.sim_dt)) if ready[slot] else self.sim_dt
            if kind == "laser" and weapon.get("charge", 0.0) > 0:
                fire_delay[slot] = self.sim_dt
            launch_target = [center[i] + velocity[i] * fire_delay[slot] for i in range(3)]
            if kind == "mortar":
                mortar_origin = list(me["pos"])
                mortar_origin[2] += own.get("height", 9.0) + 0.5
                # Do not perform arc checks for a weapon that cannot shoot.
                sol = self._mortar_solution(stats, mortar_origin, launch_target, velocity, me, own, limits) if ready[slot] else None
            else:
                sol = self._direct_solution(kind, stats, origin, launch_target, velocity, own["radius"] + 0.5, limits, height)
            if sol:
                solutions[slot] = sol
                if kind == "gun":
                    self.last_report = {
                        "tick": obs["tick"], "t": now,
                        "target_id": target.get("id"), "slot": slot,
                        "pos": tuple(me["pos"]), "actual_aim": tuple(actual),
                        "action_dt": self.action_dt,
                        "solution": copy.deepcopy(sol),
                    }

        charging = next((i for i, w in enumerate(weapons)
                         if w and w["kind"] == "laser" and w.get("charge", 0) > 0), None)
        # A fully charged or urgently released laser owns the shared aim.
        owner = None
        if charging is not None and charging in solutions:
            weapon = weapons[charging]
            if (emergency or weapon.get("charge", 0) >= stats_by_slot[charging].get("charge", 0.75) - 0.12
                    or self._laser_lethal(me, stats_by_slot[charging], target, weapon.get("charge", 0))):
                owner = charging
        if self._mortar_slot is not None:
            slot = self._mortar_slot
            same_target = self._mortar_target == target.get("id")
            usable = (slot in solutions and weapons[slot] and weapons[slot]["kind"] == "mortar"
                      and ready[slot] and solutions[slot]["clear"] and same_target and not emergency)
            if not usable or now >= self._mortar_until:
                if usable and now >= self._mortar_until:
                    self._mortar_retry_at = now + self.action_dt
                self._mortar_slot = None
            elif owner is None:
                # Finish slewing a valid low arc instead of alternating it with
                # a newly ready gun before either weapon has a usable aim.
                owner = slot
        if owner is None:
            candidates = []
            for slot, sol in solutions.items():
                if not sol["clear"]:
                    continue
                weapon, stats = weapons[slot], stats_by_slot[slot]
                kind = weapon["kind"]
                reload_ending = 0 < weapon.get("reload", 0) <= self.action_dt + 1e-6
                if kind == "gun" and (weapon.get("reload", 0) <= self.action_dt + 1e-6) and (weapon.get("ammo", 1) > 0 or reload_ending):
                    priority = 50 if ready[slot] else 15
                elif kind == "laser" and (ready[slot] or weapon.get("charge", 0) > 0):
                    priority = 35 if not emergency else 5
                elif kind == "lightning" and ready[slot]:
                    priority = 65 if me.get("energy", 0) >= stats.get("energy", 3) + (18 if emergency else 8) else 0
                elif kind == "mortar" and ready[slot]:
                    priority = 25 if not emergency and now >= self._mortar_retry_at else 0
                else:
                    priority = 0
                if priority:
                    candidates.append((priority, -slot, slot))
            if candidates:
                owner = max(candidates)[2]
        if owner is not None:
            action["aim"] = list(solutions[owner]["aim"])
            if weapons[owner]["kind"] == "mortar" and self._mortar_slot is None and not emergency:
                self._mortar_slot = owner
                self._mortar_target = target.get("id")
                self._mortar_until = now + 0.3
        else:
            # Track even while reloading or behind cover, but never pretend
            # remembered actors are necessarily directly visible.
            track = point_aim(origin, center)
            action["aim"] = [track[0], max(limits[0], min(limits[1], track[1]))]
        for slot, weapon in enumerate(weapons):
            if not weapon:
                continue
            kind, stats = weapon["kind"], stats_by_slot[slot]
            sol = solutions.get(slot)
            valid = bool(sol and sol["clear"])
            actual_next = self._slewed(actual, action["aim"], own, fire_delay[slot])
            if kind == "gun":
                aligned = valid and self._aligned(actual_next, sol, radius, height,
                                                  self.config.get("projectile", {}).get("gun_radius", 0.3))
                reload_ending = 0 < weapon.get("reload", 0) <= self.action_dt + 1e-6
                action["fire"][slot] = bool(ready[slot] and aligned and weapon.get("reload", 0) <= self.action_dt + 1e-6
                                             and (weapon.get("ammo", 1) > 0 or reload_ending) and not action["reload"])
                if not valid and not weapon.get("reload", 0) and weapon.get("ammo", 99) <= 3:
                    action["reload"] = True
            elif kind == "laser":
                charge = float(weapon.get("charge", 0.0))
                full = float(stats.get("charge", 0.75))
                aligned = valid and self._aligned(actual_next, sol, radius, height)
                if charge >= full - 1e-6:
                    self._full_since.setdefault(slot, now)
                else:
                    self._full_since.pop(slot, None)
                if charge > 0:
                    max_wait = min(0.35, max(0.0, stats.get("hold_s", 2.0) * 0.5))
                    hold_expired = now - self._full_since.get(slot, now) >= max_wait
                    lethal = aligned and self._laser_lethal(me, stats, target, charge)
                    release = emergency or lethal or (charge >= full - 1e-6 and (aligned or hold_expired))
                    # Invalid target solution (range/pitch) cannot be repaired
                    # by charging longer. Release to restore movement.
                    action["fire"][slot] = bool(not release and sol is not None)
                else:
                    # Charging is useful only with a real shot, and avoid its
                    # movement penalty during root-policy escape decisions.
                    action["fire"][slot] = bool(ready[slot] and valid and not emergency
                                                 and abs(angle_delta(sol["aim"][0], actual_next[0])) < 0.6)
            elif kind == "lightning":
                # Lightning checks horizontal yaw only. The documented cone
                # ambiguity is resolved conservatively as half the full angle.
                cone = math.radians(stats.get("cone_deg", 30.0)) * 0.5
                energy_reserve = 18.0 if emergency else 8.0
                action["fire"][slot] = bool(ready[slot] and valid
                    and abs(angle_delta(sol["aim"][0], actual_next[0])) <= cone
                    and me.get("energy", 0) >= stats.get("energy", 3.0) + energy_reserve)
            elif kind == "mortar":
                # Do not mix an arc with gun/laser aim. Tight pitch gating
                # prevents a just-turning torso from firing a short shell.
                action["fire"][slot] = bool(ready[slot] and valid and owner == slot
                    and abs(angle_delta(sol["aim"][0], actual_next[0])) < 0.018
                    and abs(sol["aim"][1] - actual_next[1]) < 0.012)
        return action
