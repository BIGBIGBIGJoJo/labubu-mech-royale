"""Persistent, body-clear combat destinations for ground navigation.

An anchor is an intended destination, not a proof that a complete route exists.
ArenaMap still validates and follows the route. Brief target memory guides only
movement; this module never creates observations or requests shots.
"""
from __future__ import annotations

import math
import time


class CombatPositioning:
    MEMORY_S = 2.0
    PROGRESS_S = 2.0
    TARGET_MOTION = 20.0
    BUDGET_S = .0028
    OFFSETS = (0, 20, -20, 40, -40, 65, -65)

    def __init__(self, config, arena):
        self.config = config
        self.arena = arena
        self.anchor = None
        self.target_id = None
        self.target_pos = None
        self.last_seen = -math.inf
        self._dims = None
        self._preferred = None
        self._detour = False
        self._progress_pos = None
        self._progress_t = 0.0
        self._progress_distance = 0.0
        self._failed = []

    def _clear(self):
        self.anchor = None
        self.target_id = None
        self.target_pos = None
        self._dims = None
        self._preferred = None
        self._detour = False
        self._progress_pos = None

    def cancel(self):
        """Preempt combat movement for recovery, resources, or zone rotation."""
        self._clear()
        self._failed.clear()
        self.last_seen = -math.inf

    @staticmethod
    def _distance(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _in_zone(self, point, obs, radius):
        zone = obs.get("zone")
        if not zone:
            return True
        center, reach = zone["center"], zone["radius"]
        if self._distance(point, center) + radius > reach:
            return False
        # Avoid retaining an anchor that the imminent shrink will invalidate.
        now = obs["t"]
        begin = max(now, zone.get("shrink_start", now + self.MEMORY_S))
        end = zone.get("shrink_end", begin + 1)
        fraction = max(0.0, min(1.0, (now + self.MEMORY_S - begin) / max(.001, end - begin)))
        nxt = zone.get("next_center", center)
        next_radius = zone.get("next_radius", reach)
        future = (center[0] + (nxt[0] - center[0]) * fraction,
                  center[1] + (nxt[1] - center[1]) * fraction)
        return self._distance(point, future) + radius <= reach + (next_radius - reach) * fraction

    def _valid(self, point, obs, stats):
        return (point is not None and len(point) >= 3
                and all(math.isfinite(float(v)) for v in point[:3])
                and self._in_zone(point, obs, stats["radius"])
                and self.arena.point_clear(point, stats["radius"], stats["height"]))

    def _reject_stalled(self, obs):
        self._failed.append((self.target_id, self.anchor, obs["t"] + 4.0))
        self._failed = self._failed[-8:]
        self._clear()

    def _recently_failed(self, point, target_id, now):
        return any(tid == target_id and until > now and self._distance(point, failed) < 5
                   for tid, failed, until in self._failed)

    def _retained(self, obs, stats):
        if self.anchor is None:
            return None
        now, pos = obs["t"], obs["self"]["pos"]
        if (now - self.last_seen > self.MEMORY_S
                or self._dims != (stats["radius"], stats["height"])
                or not self._valid(self.anchor, obs, stats)):
            self._clear()
            return None
        distance = self._distance(pos, self.anchor)
        if distance < 2.0:
            self._clear()
            return None
        if now - self._progress_t >= self.PROGRESS_S:
            # A real detour may initially increase distance to the final anchor.
            # Require either approach or meaningful displacement, not monotonic
            # distance reduction along every obstacle-avoidance segment.
            travelled = self._distance(pos, self._progress_pos)
            if self._progress_distance - distance < 1.0 and travelled < 2.5:
                self._reject_stalled(obs)
                return None
            self._progress_t = now
            self._progress_pos = tuple(pos)
            self._progress_distance = distance
        return self.anchor

    def continuation(self, obs, stats):
        """Return the recent movement anchor through a short visibility gap."""
        return self._retained(obs, stats)

    def _remember(self, point, obs, target, preferred, stats, detour):
        changed = (self.anchor is None or self.target_id != target["id"]
                   or self._distance(self.anchor, point) > 1.0)
        self.anchor = tuple(point)
        self.target_id = target["id"]
        # Keep the original target position for a detour so gradual movement
        # eventually invalidates it instead of resetting the motion threshold.
        if changed or not detour:
            self.target_pos = tuple(target["pos"])
        self.last_seen = obs["t"]
        self._dims = (stats["radius"], stats["height"])
        self._preferred = preferred
        self._detour = detour
        if changed:
            self._progress_t = obs["t"]
            self._progress_pos = tuple(obs["self"]["pos"])
            self._progress_distance = self._distance(self._progress_pos, self.anchor)
        return self.anchor

    def choose(self, obs, target, ideal_goal, preferred, stats, deadline=None):
        """Return a clear movement goal, or None if no safe candidate is found.

        Keep valid local intentions. When an intention points into a solid,
        choose a clear point on an incremental standoff ring and retain it while
        the target remains sufficiently stationary. Navigation still establishes
        route feasibility. Work stops at the caller's deadline or ~2.8 ms.
        """
        start = time.perf_counter()
        deadline = min(deadline if deadline is not None else math.inf, start + self.BUDGET_S)
        if start >= deadline:
            return None
        old_anchor = self.anchor
        retained = self._retained(obs, stats)
        if (retained is not None and (target["id"] != self.target_id
                or self._distance(target["pos"], self.target_pos) > self.TARGET_MOTION
                or abs(preferred - self._preferred) > max(10.0, .15 * abs(self._preferred)))):
            self._clear()
            retained = None
        # Preserve the existing fast path for an unobstructed local intention.
        if (time.perf_counter() < deadline
                and not self._recently_failed(ideal_goal, target["id"], obs["t"])
                and self._valid(ideal_goal, obs, stats)):
            return self._remember(ideal_goal, obs, target, preferred, stats, False)
        if retained is not None and self._detour:
            self.last_seen = obs["t"]
            return retained
        pos = obs["self"]["pos"]
        tx, ty = target["pos"][:2]
        distance = self._distance(pos, target["pos"])
        ring = max(float(preferred), distance - 20.0, 0.0)
        bearing = math.atan2(pos[1] - ty, pos[0] - tx)
        self._failed = [entry for entry in self._failed if entry[2] > obs["t"]]
        best = None
        for degrees in self.OFFSETS:
            if time.perf_counter() >= deadline:
                break
            angle = bearing + math.radians(degrees)
            x, y = tx + ring * math.cos(angle), ty + ring * math.sin(angle)
            point = (x, y, self.arena.ground_height(x, y))
            if not self._valid(point, obs, stats):
                continue
            if self._recently_failed(point, target["id"], obs["t"]):
                continue
            travel = self._distance(pos, point)
            if travel < 2.0:
                continue
            cost = travel
            if old_anchor is not None:
                cost += .15 * min(60.0, self._distance(point, old_anchor))
            if best is None or cost < best[0]:
                best = cost, point
        if best is not None:
            return self._remember(best[1], obs, target, preferred, stats, True)
        self._clear()
        # A deliberate hold is useful only when its actual cylinder is valid.
        if time.perf_counter() < deadline and self._valid(pos, obs, stats):
            return tuple(pos)
        return None
