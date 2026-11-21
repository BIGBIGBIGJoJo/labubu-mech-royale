"""Bounded ground-goal screening against the exact directed navigation graph.

NO means the current navigator's snapped graph has no route, not that a physical
route or a jump is impossible. UNKNOWN preserves the caller's existing policy.
Graph construction is offline only; runtime uses component IDs and closure bits.
"""
from collections import OrderedDict, deque
import hashlib
import json
import math
from pathlib import Path
import struct
import time

from navigation_cache import DIRECTIONS

YES, NO, UNKNOWN = "yes", "no", "unknown"
MAGIC = b"MFRGv001"
VERSION = 1
MAX_BYTES = 1024 * 1024
NO_COMPONENT = 65535


def fingerprint(cache_path, source_path=__file__):
    return {"version": VERSION,
            "navigation_sha256": hashlib.sha256(Path(cache_path).read_bytes()).hexdigest(),
            "algorithm_sha256": hashlib.sha256(Path(source_path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()}


def build_components(grid, free, edges):
    """Offline exact SCC/closure, including A*'s free-cell and diagonal rules."""
    gx, gy = grid
    n = gx * gy
    flags = [bool(free[i >> 3] & (1 << (i & 7))) for i in range(n)]
    adj, reverse = [[] for _ in range(n)], [[] for _ in range(n)]
    for i in range(n):
        if not flags[i]:
            continue
        x, y = i % gx, i // gx
        for bit, (dx, dy) in enumerate(DIRECTIONS):
            nx, ny = x + dx, y + dy
            if not edges[i] & (1 << bit) or not (0 <= nx < gx and 0 <= ny < gy):
                continue
            j = ny * gx + nx
            if not flags[j] or (dx and dy and (not flags[y * gx + nx] or not flags[ny * gx + x])):
                continue
            adj[i].append(j)
            reverse[j].append(i)
    seen, order = bytearray(n), []
    for start in range(n):
        if not flags[start] or seen[start]:
            continue
        stack = [(start, False)]
        while stack:
            i, done = stack.pop()
            if done:
                order.append(i)
                continue
            if seen[i]:
                continue
            seen[i] = 1
            stack.append((i, True))
            stack.extend((j, False) for j in adj[i] if not seen[j])
    ids, count = [NO_COMPONENT] * n, 0
    for start in reversed(order):
        if ids[start] != NO_COMPONENT:
            continue
        stack, ids[start] = [start], count
        while stack:
            i = stack.pop()
            for j in reverse[i]:
                if ids[j] == NO_COMPONENT:
                    ids[j] = count
                    stack.append(j)
        count += 1
    if count >= NO_COMPONENT:
        raise ValueError("too many components")
    dag = [set() for _ in range(count)]
    for i in range(n):
        for j in adj[i]:
            if ids[i] != ids[j]:
                dag[ids[i]].add(ids[j])
    indegree = [0] * count
    for exits in dag:
        for j in exits:
            indegree[j] += 1
    pending = deque(i for i, degree in enumerate(indegree) if not degree)
    order = []
    while pending:
        i = pending.popleft()
        order.append(i)
        for j in dag[i]:
            indegree[j] -= 1
            if not indegree[j]:
                pending.append(j)
    if len(order) != count:
        raise ValueError("component graph is not acyclic")
    reach = [0] * count
    for i in reversed(order):
        reach[i] = 1 << i
        for j in dag[i]:
            reach[i] |= reach[j]
    width = (count + 7) // 8
    payload = struct.pack("<" + "H" * n, *ids)
    payload += b"".join(bits.to_bytes(width, "little") for bits in reach)
    return count, payload


class ReachabilityIndex:
    def __init__(self, grid, records, payload):
        self.gx, self.gy = grid
        self.dimensions = {}
        data, offset = memoryview(payload), 0
        node_bytes = self.gx * self.gy * 2
        for record in records:
            count = record["components"]
            width = (count + 7) // 8
            stop = offset + node_bytes + count * width
            self.dimensions[tuple(record["dims"])] = (data[offset:offset + node_bytes],
                                                        data[offset + node_bytes:stop], width)
            offset = stop

    def reaches(self, start, target, dims):
        data = self.dimensions.get(dims)
        if data is None or not all(0 <= x < self.gx and 0 <= y < self.gy for x, y in (start, target)):
            return None
        ids, closure, width = data
        a, b = (2 * (y * self.gx + x) for x, y in (start, target))
        first, last = ids[a] | ids[a + 1] << 8, ids[b] | ids[b + 1] << 8
        if first == NO_COMPONENT or last == NO_COMPONENT:
            return None
        return bool(closure[first * width + (last >> 3)] & (1 << (last & 7)))


def encode(grid, records, payload, key):
    header = {"grid": grid, "dimensions": records, "key": key,
              "payload_sha256": hashlib.sha256(payload).hexdigest()}
    raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    return MAGIC + struct.pack("<I", len(raw)) + raw + payload


def load(arena, path=None, cache_path=None):
    exact = getattr(arena, "_navigation_cache", None)
    if exact is None:
        return None, "unavailable navigation cache"
    try:
        path = Path(path or Path(__file__).with_name("ground-reachability.bin"))
        cache_path = Path(cache_path or Path(__file__).with_name("navigation-cache.bin"))
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("metadata exceeds limit")
        raw = path.read_bytes()
        if len(raw) < 12 or raw[:8] != MAGIC:
            raise ValueError("invalid format")
        size = struct.unpack("<I", raw[8:12])[0]
        if not 0 < size <= 16384 or len(raw) < 12 + size:
            raise ValueError("invalid header length")
        header = json.loads(raw[12:12 + size])
        if header["key"] != fingerprint(cache_path) or header["grid"] != [exact.gx, exact.gy]:
            raise ValueError("metadata key mismatch")
        records = header["dimensions"]
        if not isinstance(records, list) or len(records) != len(exact.dimensions):
            raise ValueError("invalid dimensions")
        dimensions = [tuple(r["dims"]) for r in records]
        if len(set(dimensions)) != len(dimensions) or set(dimensions) != set(exact.dimensions):
            raise ValueError("dimension mismatch")
        if any(type(r["components"]) is not int or not 0 < r["components"] < NO_COMPONENT for r in records):
            raise ValueError("invalid component count")
        payload = memoryview(raw)[12 + size:]
        expected = sum(exact.gx * exact.gy * 2 + r["components"] * ((r["components"] + 7) // 8)
                       for r in records)
        if len(payload) != expected or hashlib.sha256(payload).hexdigest() != header["payload_sha256"]:
            raise ValueError("invalid payload")
        return ReachabilityIndex(header["grid"], records, payload), "loaded"
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        return None, f"unavailable: {exc}"


class GroundReachability:
    """Reuse immutable goal connectors; observations only create short contexts."""
    def __init__(self, arena, index=None):
        self.arena = arena
        self.index, self.status = (index, "injected") if index is not None else load(arena)
        self.goal_anchors = OrderedDict()
        self.goal_connectors = OrderedDict()

    @staticmethod
    def remember(cache, key, value):
        cache[key] = value
        cache.move_to_end(key)
        if len(cache) > 512:
            cache.popitem(last=False)

    def begin(self, pos, radius, height, deadline):
        return GoalContext(self, tuple(pos), radius, height, deadline)


class GoalContext:
    MIN_GEOMETRY_SECONDS = .0015

    def __init__(self, owner, pos, radius, height, deadline):
        self.owner, self.arena, self.pos = owner, owner.arena, pos
        self.radius, self.height, self.deadline = radius, height, deadline
        self.dims = (math.ceil(radius * 2) / 2, math.ceil(height * 2) / 2)
        self.start = None
        self.start_clear = None
        self.budget_exhausted = False
        self.report = {YES: 0, NO: 0, UNKNOWN: 0, "geometry_calls": 0}

    def ray(self, start, end):
        if time.perf_counter() + self.MIN_GEOMETRY_SECONDS >= self.deadline:
            self.budget_exhausted = True
            return None
        self.report["geometry_calls"] += 1
        result = self.arena.move_clear(start, end, self.radius, self.height)
        if time.perf_counter() >= self.deadline:
            self.budget_exhausted = True
            return None
        return result

    def classify(self, goal):
        result = self._classify(tuple(goal))
        self.report[result] += 1
        return result

    def _classify(self, goal):
        if self.owner.index is None or self.dims not in self.owner.index.dimensions:
            return UNKNOWN
        if time.perf_counter() >= self.deadline:
            self.budget_exhausted = True
            return UNKNOWN
        if math.dist(self.pos[:2], goal[:2]) < 1:
            return YES
        # This helper describes ground navigation, not rooftop/jet routes.
        if abs(goal[2] - self.arena.ground_height(*goal[:2])) > self.arena.step_up + .02:
            return UNKNOWN
        if self.start is None:
            self.start = self.arena._nearest_free(self.arena._cell(self.pos), self.dims, self.deadline)
        key = (self.dims, goal)
        target = self.owner.goal_anchors.get(key)
        if target is None:
            target = self.arena._nearest_free(self.arena._cell(goal), self.dims, self.deadline)
            if target is not None:
                self.owner.remember(self.owner.goal_anchors, key, target)
        if self.start is None or target is None:
            return UNKNOWN
        reachable = self.owner.index.reaches(self.start, target, self.dims)
        if reachable is None:
            return UNKNOWN
        if not reachable:
            # A coarse graph can miss a valid continuous route; preserve it.
            direct = self.ray(self.pos, goal)
            if direct is None:
                return UNKNOWN
            if direct:
                return YES
        if self.start_clear is None:
            self.start_clear = self.ray(self.pos, self.arena._point(self.start))
        if self.start_clear is not True:
            return UNKNOWN
        if not reachable:
            return NO
        connector_key = (self.dims, self.radius, self.height, target, goal)
        connector = self.owner.goal_connectors.get(connector_key)
        if connector is None:
            connector = self.ray(self.arena._point(target), goal)
            if connector is not None:
                self.owner.remember(self.owner.goal_connectors, connector_key, connector)
        if connector:
            return YES
        if connector is None:
            return UNKNOWN
        direct = self.ray(self.pos, goal)
        return YES if direct else UNKNOWN
