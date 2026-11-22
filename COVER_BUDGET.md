# Conservative recovery exposure queries

Base: `bcd58ed4abbc4b46be3779a10246347c99c99622`.

Recovery position scoring treats an unmodeled mortar path or an unknown weapon as exposed regardless of direct visibility. It previously cast direct rays which could not reduce that binary risk. `ExposureModel.incoming(..., conservative_only=True)` now returns explicit unmodeled uncertainty without those rays. Only recovery `position_cost` opts in. Ordinary incoming queries retain direct samples; known direct weapons and NPCs still cast rays, and an empty weapon list remains no held threat.

Scalar risk and all its weights remain unchanged. Visibility telemetry can change from True to None. A mixed unmodeled threat plus a direct threat whose query actually times out can now preserve an unresolved scan candidate instead of advancing; this is conservative and tested. The fast path does not invent a deadline or ray-budget reason for a fully priced unmodeled threat. Unknown never means protected.

There are no movement, route, geometry, goal-hold, deadline or weapon-policy changes. This candidate does **not** fix the late stationary sequence described below.

## Validation

Runnable immutable image: `sha256:b28c4b3f16cb5be3f737af1f4ae84411e746de3fec3bb0fcc13943ea9d34f714`.

Normalized-LF production hashes:

- `bot.py`: `ffd49654ceeba495153c3a833df12bd72e24a01a2462ba7a4ba626e4ea746c4c`
- `exposure.py`: `40c00bfed17ea3d6d679ca84b41a4c1ece8ddd97af648d3d7a0197eb8959e86a`

All 246 tests passed in restricted Linux, including eight new regressions for scalar cost equivalence, preserved detailed default queries, unknown and empty loadouts, NPCs, zero budget, and mixed-threat timeout/cursor behavior. The official starter checker answered 300/300 observations on time, p99 31.6 ms, maximum 31.9 ms, with no bad lines, wrong ticks or errors.

An untouched chronological `Bot.act` replay processed all 1,038 observations of `incoming-cover-bcd58ed-20261122-110126/trace.jsonl.gz`. All source files and cache files matched the mounted worktree; native terrain, both loaded caches, 259 map prisms and 774,680 samples were asserted before replay. No action or navigation hooks were installed. Restricted execution used 1 CPU, 512 MB, no network, read-only root and the real arena mount.

- p50 30.681 ms; p99 31.507 ms; maximum 32.368 ms.
- Zero exceptions and zero observations above the official 50 ms action limit. The unchanged cooperative controller deadline remains 32 ms; individual geometry calls may finish slightly after it.
- Late recovery, 87.9–103.7 s: 159 frames, 13 scans, 61 completed nonanchor candidates, two scans with no nonanchor progress, 90 nonzero moves, 64 tactical fallbacks.
- The 12 observations from 99.2–100.3 s still all emit zero movement, now with tactical fallback. More evaluated goals alone does not establish usable escape movement.

The original run and this fixed-observation replay are not paired match outcomes. Earlier instrumented control/scratch runs produced different scan histories and counts, so their results are retained separately rather than substituted for this exact production-source validation.

## Evidence and remaining bottleneck

At recorded 99.2 s, the original scan evaluated only the origin and then held it as the recovery goal. Two current-generator points pass complete diagnostic ground/support/terminal-Z/collision checks and improve the existing score: a 4.993 m point scores 610.830 and a 5.893 m northern point scores 609.519, versus the origin's 614.077. Both remain exposed; neither is claimed to provide safe healing. Their complete direct witnesses take about 3–4 ms with diagnostic time, exceeding the separate experimental 2.5 ms witness budget.

A scratch fast-path replay exposes a distinct tactical problem at 99.5 s: two highly ranked boosted trajectories hit a wall late in their rollouts, using approximately 14 ms before a third expires. Existing navigation walk is ranked seventh and never validated, although its complete rollout passes and its adjusted existing cost is lower than neutral. The production validation still contains stationary fallback. Any validation-order remedy is a separate experiment and is absent from this commit.

Audit artifacts in the shared workspace:

- `work/game-interface-audit/cover-budget-linux-tests.txt`
- `work/game-interface-audit/cover-budget-linux-checker.txt`
- `work/game-interface-audit/cover-budget-b28c4b3-full-prefix.json`
- `work/game-interface-audit/cover-budget-independent-review.json`
- `work/game-interface-audit/incoming-cover-bcd58ed-20261122-110126/STOP_CAUSE_AUDIT.md`
- `work/game-interface-audit/incoming-cover-bcd58ed-20261122-110126/tactical-99_5-rejections.json`

No new private game or official submission was run for this candidate before freezing it. Freezing establishes reproducibility, not a score improvement or promotion recommendation.
