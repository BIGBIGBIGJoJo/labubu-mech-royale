# Exact navigation geometry cache

Candidate branch: `goal/navcache-seven`, based on
`39b6d509af8e82b0ceb9e1c430dd964674d7488e`. This is an isolated performance
change. Combat, tactical scoring, resource/goal selection, the 600-node search
cap, and navigation's 2.5 ms steering reserve remain unchanged.

## What is cached

The offline asset stores each original `_free` result and each original
**directed** adjacent `_traversable` result on the existing 5 m grid. It does not
infer clearance for other body sizes or reverse an edge. Continuous movement,
steering, shot rays, cover scoring and unsupported dimensions keep their existing
geometry implementation.

- Grid: 215 by 146, or 31,390 cells; 248,958 directed in-bounds neighbor edges.
- Exact rounded (radius, height) pairs: (2.5,9), (3,9.5), (3,10), (3,10.5),
  (3,11), (3.5,11.5), (3.5,12), (3.5,12.5), (3.5,13), (4,13.5).
  These are the ten unique pairs produced by the configured cube counts 0–10.
- One free-cell bitset and one eight-direction byte per cell per dimension.
- Asset: **353,832 bytes**, including metadata. SHA256:
  `616af90ee23084c02194171787811d1bf24efd850eca993e52e152bacdfec8c3`.
- Full build: **207.64 seconds**, two workers, on this Windows host.

The loader validates the two map-file hashes, grid/bounds, step-up, maximum
slope, arena inset, contact epsilon, explicit format/algorithm version, normalized
`arena_map.py` source hash, dimensions, payload length and checksum. Missing,
incompatible or corrupted data falls back to original geometry. A private match's
different duration/zone timetable does not invalidate identical geometry.

The cache is loaded once at startup. Lookups perform no hashing, file access,
generation or writes. Cached storage uses memory views over one immutable asset.
The bot image remains read-only. Any `arena_map.py` edit, including a comment,
requires regeneration; CRLF versus LF is normalized. Copy the reviewed source and
asset together when freezing this candidate.

## Verification

- Full Windows suite: **135 tests passed**.
- Cache suite inside restricted Linux: **11 tests passed**.
- The real-map parity test compares 128 deterministic random cells × ten sizes,
  including all in-bounds directed neighbors, against native geometry.
- A complete small sloped map checks every cell and directed edge, including a
  permitted descent whose reverse ascent is blocked.
- Unsupported sizes/nonadjacent queries, expired budgets, steering reserve,
  corrupted/missing assets, changed map/config/source, CRLF normalization and no
  geometry calls/writes for supported lookups are covered.
- On the captured difficult C1 route, the first eight generous-budget search
  calls (4,800 nodes) produce **identical entire search states, paths and steering**
  with original geometry versus the cache. This passes on Windows and Linux.
- `git diff --check` passed before freeze.

Official checker ran **inside Linux**, with actual `/arena` mounted read-only,
network disabled, 1 CPU, 512 MB RAM/swap limit, read-only root, 64 MB `/tmp`, uid
65534. Preflight asserted 259 prisms and 774,680 terrain samples and matched all
six loaded image Python files to the reviewed repository after CRLF normalization.

Result: **PASS, 300/300 on time**, no late answers, wrong ticks, bad lines or dropped
queued answers. Startup 3,034 ms. Answer p50 10.5 ms, p90 26.3, p99 32.4, maximum
36.7. The checker's generic “not the 1-CPU match container” wording does not describe
this invocation: the enclosing validation container was explicitly limited to
one CPU. The checker is protocol/timing validation, not a score evaluation.

## Chronological C1 replay

Both policies consumed all 1,045 recorded C1 observations in order in separate
restricted Linux containers. Observations were identical; these are conditional
replays, **not closed-loop matches or score predictions**. Navigation timing and
state were recorded; diagnostic direct-path checks ran after each bot action.
Direct and near-goal frames are excluded from “route required.”

| Metric, all 104.5 seconds | Baseline 39b | Cache |
|---|---:|---:|
| Frames requiring a route | 632 | 632 |
| Frames with completed route | 198 (31.3%) | 344 (54.4%) |
| Search episodes completed / started | 24 / 51 | 26 / 51 |
| Completed-episode mean latency | 0.467 s | 0.131 s |
| Completed-episode p90 latency | 1.0 s | 0.2 s |
| Search expansions | 13,481 | 53,675 |
| Mean navigation time | 4.73 ms | 3.28 ms |
| Navigation entry budget ≤2.5 ms | 143 frames | 160 frames |
| Tactical fallback frames | 161 | 143 |
| Mean full-action time | 25.01 ms | 23.70 ms |
| Maximum action time | 40.94 ms | 37.59 ms |
| Actions over 50 ms | 0 | 0 |

Completion latency describes completed episodes only. Timing-sensitive goals can
differ across replays, so this is not a paired estimate for every individual goal.
Zero-budget frames remain: a cache does not override the caller's deadline.

### The recorded jam remains

In the 38.6–54.1 s window, both runs had 115 route-required frames. Completed-route
frames were 13 baseline versus 11 cached; tactical fallbacks were 94 versus 93,
despite expansions increasing from 5,937 to 31,348. This candidate does not fix that
jam.

The fixed t=45 s request was also searched to exhaustion with the cache and
generous budgets: 29 bounded calls closed **17,285 reachable nodes**, emptied the
frontier and still did not reach its target. The best partial path remained three
points. The target is unreachable in the existing rounded 5 m directed graph for
that request. Additional compute alone cannot complete it. Reachability-aware
goal projection would be a separate behavior change and is not bundled here.

## Timing and repeatability

With generous budgets and 1 CPU, the same first eight 600-node searches took
611–927 ms each with original geometry versus 26.5–37.3 ms with the cache. These
are throughput measurements; production navigation still obeys its deadlines.

Three independent fresh-Bot replays used the existing `repeat_policy.py` and the
same 1,045 observations. Comparison is run 0 against runs 1 and 2:

| Different decisions | Baseline 39b | Cache |
|---|---:|---:|
| Movement, run 1 | 235 | 108 |
| Movement, run 2 | 216 | 84 |
| Goal, run 1 | 110 | 69 |
| Goal, run 2 | 77 | 6 |
| Fire, both comparisons | 0 | 0 |

Cache action medians: 24.69, 24.61, 25.23 ms. P99: 33.94, 33.91, 34.29 ms.
Maxima: 34.92, 35.24, 37.48 ms; no action exceeded 50 ms. This reduces but does not
eliminate deadline-sensitive movement decisions. These three-run counts are not
a statistical estimate of match-score variance.

The retained asset is 353,832 bytes. Whole-map Linux startup peak RSS was about
26–27 MiB with cache versus 24.5 MiB disabled in separate processes; this includes
temporary map hashing allocations. Five isolated cache validations/loads took
45.9–49.5 ms. Map construction dominated total 2.6–2.9 s startup.

An eight-call cached-search cProfile run attributed approximately 43% of profiled
time to `_free`/`_traversable` wrappers plus lookup, 32% to the navigation loop
itself, 12% to the heuristic, and 7% to remaining continuous segment geometry.
Profiler overhead affects these percentages. No hash/file-load function appeared
in the lookup profile. Further Python-loop optimization is separate from this
cache-only candidate.

## Reproduction and local evidence

From this repository:

```text
python build_navigation_cache.py --workers 2
python -m unittest discover -s tests -v
docker build --platform linux/amd64 -t labubu-score7:navcache .
```

From the shared workspace, the reviewed validation wrapper is:

```powershell
& .\outputs\run-validation.ps1 -Repo .\work\labubu-navcache -Image labubu-score7:navcache
```

Local diagnostic artifacts in `../game-interface-audit/`:

- `navcache-official-checker.txt`
- `navcache_replay.py`, `navcache-baseline-linux.json`, `navcache-candidate-linux.json`
- `repeat_policy.py`, `baseline-repeatability-linux.jsonl`, `navcache-repeatability-linux.jsonl`
- `navcache_startup.py`, `navcache-fixed-route-linux.jsonl`
- `navcache_profile_hits.py`, `navcache-hit-profile-linux.txt`
- `STATIC_NAVIGATION_CACHE_FEASIBILITY.md`, `static-navigation-profile.json`

No live game, public submission, push or score claim was made by this validation.
