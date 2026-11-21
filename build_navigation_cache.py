"""Offline exact grid cache builder. Never invoked by the bot at runtime."""
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse
import gzip
import json
import math
from pathlib import Path
import time

from arena_map import ArenaMap
from navigation_cache import DIRECTIONS, MAX_BYTES, encode, geometry_key


_arena = None
_points = None
_dimensions = None


def initialize(map_dir, config, dimensions):
    global _arena, _points, _dimensions
    _arena = ArenaMap(map_dir, config, use_navigation_cache=False)
    if not _arena.available:
        raise RuntimeError(_arena.error)
    _points = [_arena._point((i % _arena.gx, i // _arena.gx))
               for i in range(_arena.gx * _arena.gy)]
    _dimensions = dimensions


def build_chunk(start, end):
    arena = _arena
    records = []
    for dims in _dimensions:
        free = bytearray(end - start)
        edges = bytearray(end - start)
        for index in range(start, end):
            x, y = index % arena.gx, index // arena.gx
            free[index - start] = arena._free((x, y), dims)
            for direction, (dx, dy) in enumerate(DIRECTIONS):
                if 0 <= x + dx < arena.gx and 0 <= y + dy < arena.gy:
                    nxt = (y + dy) * arena.gx + x + dx
                    if arena.move_clear(_points[index], _points[nxt], *dims):
                        edges[index - start] |= 1 << direction
        records.append((bytes(free), bytes(edges)))
        arena._walk_cache.clear()
    return start, end, records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    with gzip.open(root / "check/stream.jsonl.gz", "rt", encoding="utf-8") as file:
        hello = json.loads(next(file))
    config = hello["config"]
    arena = ArenaMap(root / "arena", config, use_navigation_cache=False)
    if not arena.available:
        raise RuntimeError(arena.error)
    dims = tuple(dict.fromkeys(
        (math.ceil(config["mech"]["radius"] * (1 + config["cubes"]["size_per_cube"] * c) * 2) / 2,
         math.ceil(config["mech"]["height"] * (1 + config["cubes"]["size_per_cube"] * c) * 2) / 2)
        for c in range(11)))
    n = arena.gx * arena.gy
    free_bytes = (n + 7) // 8
    stride = free_bytes + n
    payload = bytearray(stride * len(dims))
    key = geometry_key(arena, root / "arena", root / "arena_map.py")
    started = time.perf_counter()
    completed = 0
    print(f"Building {n} cells, {len(dims)} exact dimensions, {args.workers} workers", flush=True)
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                             initargs=(root / "arena", config, dims)) as pool:
        futures = [pool.submit(build_chunk, start, min(n, start + 256))
                   for start in range(0, n, 256)]
        for future in as_completed(futures):
            start, end, records = future.result()
            for d, (free, edges) in enumerate(records):
                base = d * stride
                for j, value in enumerate(free):
                    if value:
                        i = start + j
                        payload[base + (i >> 3)] |= 1 << (i & 7)
                payload[base + free_bytes + start:base + free_bytes + end] = edges
            completed += end - start
            if completed % 4096 < 256 or completed == n:
                print(f"{completed}/{n} cells, {time.perf_counter() - started:.1f}s", flush=True)
    # Refuse an asset if source/map/settings changed during offline generation.
    if geometry_key(arena, root / "arena", root / "arena_map.py") != key:
        raise RuntimeError("geometry inputs changed during generation")
    data = encode(key, dims, payload)
    if len(data) > MAX_BYTES:
        raise RuntimeError("cache exceeds 20 MiB")
    destination = root / "navigation-cache.bin"
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)
    print(json.dumps({"output": str(destination), "bytes": len(data), "dimensions": dims,
                      "seconds": time.perf_counter() - started}), flush=True)


if __name__ == "__main__":
    main()
