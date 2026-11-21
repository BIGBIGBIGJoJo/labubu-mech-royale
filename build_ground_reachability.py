"""Build directed reachability metadata offline from the reviewed exact asset."""
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
import time

from arena_map import ArenaMap
from ground_reachability import MAX_BYTES, build_components, encode, fingerprint


def build_one(task):
    dims, grid, free, edges = task
    count, payload = build_components(grid, free, edges)
    return {"dims": dims, "components": count}, payload


def main():
    root = Path(__file__).resolve().parent
    with gzip.open(root / "check/stream.jsonl.gz", "rt", encoding="utf-8") as file:
        config = json.loads(next(file))["config"]
    arena = ArenaMap(root / "arena", config)
    if arena.navigation_cache_status != "loaded":
        raise RuntimeError(arena.navigation_cache_status)
    exact = arena._navigation_cache
    grid = (exact.gx, exact.gy)
    key = fingerprint(root / "navigation-cache.bin")
    tasks = [(dims, grid, bytes(data[0]), bytes(data[1])) for dims, data in exact.dimensions.items()]
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(build_one, tasks))
    records = [record for record, _ in results]
    data = encode(grid, records, b"".join(payload for _, payload in results), key)
    if len(data) > MAX_BYTES or fingerprint(root / "navigation-cache.bin") != key:
        raise RuntimeError("size limit exceeded or inputs changed during generation")
    destination = root / "ground-reachability.bin"
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.replace(destination)
    print(json.dumps({"bytes": len(data), "seconds": time.perf_counter() - started,
                      "dimensions": records}), flush=True)


if __name__ == "__main__":
    main()
