# Bounded reachable safe goals

Branch `goal/reachable-seven`, based on frozen navigation-cache commit
`6bd5920166f9e09e790b232a568361db767770f1`.

The captured C1 rotation repeatedly selected a goal whose snapped destination
could not be reached from the current ground-navigation graph. Exhaustive search
closed 17,285 nodes without finding it. This change screens only `safe_goal`
destinations, retaining the existing score among eligible candidates. It does not
change resource goals, combat movement, tactical scoring, A* budgets/caps, or
geometry predicates. `arena_map.py` and `navigation-cache.bin` remain byte-identical
to the base commit.

## Runtime behavior

`GroundReachability` loads offline component IDs and directed reachability bits.
The graph includes the exact free-cell, directed-edge and diagonal-corner rules
used by A*. Runtime performs no flood search or graph construction.

- **YES**: a continuous direct segment is clear, or the snapped graph has a path
  and the actual start-to-grid and grid-to-goal connectors validate.
- **NO**: a valid actual start connector leads into a component from which the
  navigator's snapped target is unreachable, and the continuous direct segment
  is blocked. This is a statement about the current ground planner, not proof
  that no physical or jet-assisted route exists.
- **UNKNOWN**: unavailable metadata, unsupported body dimensions, an uncertain
  connector, a rooftop goal, or insufficient time. Ordinary UNKNOWN candidates
  retain their existing scoring. Budget exhaustion ends optional selection.

Only NO candidates are rejected. The helper validates within the caller's
existing deadline, with a 1.5 ms guard before starting a native geometry call and
a deadline check after it. This guard does not preempt an already-running geometry
call; measured timing remains important. Immutable goal anchors and final
connectors use separate bounded 512-entry caches keyed by exact points and body
dimensions. A start connector is reused only within the current selection call.

The existing zone-clamp fallback can create a new goal that was never screened.
Before selection, the bot therefore revalidates its prior safe goal if its kind
was rotate/recover/position and it remains inside the existing 22-second future
zone. If selection would otherwise clamp an outside-zone result, that prior
objective is retained only after an explicit YES within the same deadline.
Resource goals and outside-zone prior goals are excluded. No new cover point is
silently projected elsewhere.

## Offline asset and integrity

`build_ground_reachability.py` uses two workers and reads the existing exact
navigation asset. The ten supported body-dimension graphs contain 60–65 strongly
connected components each. Directed component-DAG transitive closure preserves
one-way traversal; shared undirected connectivity is not treated as reachability.

Generation took 2.04 seconds on this host. Metadata is **633,513 bytes**; combined
navigation/reachability assets are **987,345 bytes**. The loader validates the exact
navigation-asset hash, normalized helper-source hash, format version, grid,
dimensions, payload size and checksum. Incompatible/missing data disables
screening rather than fabricating connectivity.

Metadata SHA256:
`371edcfc89e6f4b7c9903a25573ef15ed776153c7e0c1d7bd020c3af751204ae`.

Navigation asset SHA256 remains:
`616af90ee23084c02194171787811d1bf24efd850eca993e52e152bacdfec8c3`.

Both image assets were compared byte-for-byte with the repository inside the
restricted Linux container. Both loaders reported `loaded`; the real arena had
259 prisms and 774,680 samples. Whole-Bot peak RSS was 30,992 KiB; construction
took 2,506 ms in that check. Runtime requires no filesystem writes.

If this change is combined with a newly generated navigation asset or the helper
source changes, regenerate reachability metadata before building the image.

## Tests and official protocol checker

Final full suite: **153 tests passed inside restricted Linux**. Eighteen focused
tests cover transitive one-way paths, diagonal corner restrictions, actual start
and goal connectors, direct paths missed by the grid, UNKNOWN/deadline handling,
cache dimensions/bounds, metadata rejection, no runtime graph construction, the
C1 regression, and prior-goal fallback exclusions. Independent directed floods
from two starts across three body sizes agree with stored closure results for
128 deterministic target cells each.

The official checker ran inside Linux with network disabled, 1 CPU, 512 MB
RAM/swap limit, read-only root, 64 MB `/tmp`, uid 65534 and `/arena` mounted
read-only. Preflight asserted the actual map and matched seven loaded image
Python files against the repository after CRLF normalization.

**PASS: 300/300 answered in time**, no wrong ticks, bad lines, dropped queued
answers or late responses. Startup 2,964 ms. Answer p50 10.4 ms, p90 26.3 ms,
p99 32.6 ms, maximum 32.9 ms. This validates protocol and timing, not match score.

## Full-prefix C1 replay

All 1,045 observations were replayed chronologically in restricted Linux.
These are conditional decisions on recorded observations, not a counterfactual
match. Different goals change the route-required denominator. Timing-sensitive
choices remain possible, so these single runs are mechanism evidence rather than
a statistical score claim.

| Whole trace | Cache-only base | Reachable safe goals |
|---|---:|---:|
| Completed-route frames / route-required frames | 344 / 632 (54.4%) | 485 / 597 (81.2%) |
| Completed search episodes / started | 26 / 51 | 34 / 46 |
| Mean completed-episode latency | 0.131 s | 0.082 s |
| Search expansions | 53,675 | 6,645 |
| Mean navigation time | 3.28 ms | 1.38 ms |
| Tactical fallback frames | 143 | 86 |
| Maximum action time | 37.59 ms | 37.42 ms |
| Actions over 50 ms | 0 | 0 |

| Captured jam, 38.6–54.1 s | Cache-only base | Reachable safe goals |
|---|---:|---:|
| Completed-route frames / route-required frames | 11 / 115 (9.6%) | 86 / 90 (95.6%) |
| Search expansions | 31,348 | 111 |
| Mean navigation time | 10.59 ms | 2.26 ms |
| Tactical fallback frames | 93 | 42 |
| Navigation entry budget ≤2.5 ms | 15 | 16 |

A separate posthoc geometry check verified **all 156 actual selected goals** in
this window as YES and inside the existing future circle. This includes all 15
original witness timestamps. At t40, the prior low-ground objective
`[-337.511,-6.026,-4.755]` is retained with a clear direct route. At t45, the actual
selected goal is `[-328.464,-8.536,-4.738]`; live A* is complete after 38 nodes.
Other sampled graph routes complete after 15–41 nodes. Direct frames do not need
A*, and are not counted as unfinished routes.

The posthoc check certifies the selected route representation, not that every
frame had enough live compute to execute it. Some navigation calls still enter
with no search budget; tactical fallback also remains. Live play and scoring
must be evaluated separately.

## Reproduce

```text
python build_ground_reachability.py
python -m unittest discover -s tests -v
docker build --platform linux/amd64 -t labubu-score7:reachable .
```

From the shared workspace:

```powershell
& .\outputs\run-validation.ps1 -Repo .\work\labubu-reachable -Image labubu-score7:reachable
```

Local evidence in `../game-interface-audit/`:

- `reachable-retain-c1-linux.json`
- `reachable-retain-c1-linux-witnesses.json`
- `reachable-retain-official-checker.txt`
- `navcache-candidate-linux.json` (cache-only comparison)
- `reachable-safe-goal-probe.json` (earlier generous-budget design probe)

The earlier `reachable-c1-linux.json` belongs to the filter before prior-goal
retention and is not the final candidate. This report does not claim a live score
improvement or that all future goals will be classifiable.
