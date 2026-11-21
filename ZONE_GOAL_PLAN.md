# Historical experiment document

This file records earlier experimental branches. The current controlled
experiment is described in PROGRAM_DESIGN.md and the three current strategy-agent plans. Its runtime
does not include all mechanisms proposed or tested below.

# Validate zone-projected goals before navigation

Implemented in `Bot.safe_goal` and `Bot.project_zone_goal` after this plan was approved. It complements the fine-route recovery work; endpoint clearance is not a proof of route connectivity.

## Recorded defect and exact-source replay

Evidence comes from the earlier aggressive private diagnostic and its captured source, not from the official 4.63 result. The sanitized geometry and relevant numeric states are preserved in `tests/zone_goal_projection_fixture.json`.

At 90 s the goal `[-20.271585073399365, 72.05925928184553, -0.5985282330729235]` is exactly the radial projection of the current position `[-36.26, 82.95, -0.31]` onto the 22-second future circle. That circle has center `[163.31, -52.99]` and radius 240; the projected center radius is `240 - 2.875 - 15 = 222.125`.

`safe_goal` first scores the current position and cover candidates. The current position can win despite being outside the future circle. The function then replaces it with a radial projection and returns immediately. This new endpoint bypasses both actual-body `point_clear` and the eight-metre failed-goal filter. At 90 s the 2.875 m radius / 10.35 m height body intersects building prisms 97 and 101; the goal center is inside prism 101 (block 28, top 24.81).

The recorded invalid goal recurs at 85.5, 86.8, 89.4, and 93.3 s. During its long holds the map reports `ready` and produces nonzero navigation. Therefore `check_route_progress` sees neither `unreachable` nor neutral navigation and does not retire it, even though the later tactical result is neutral. This is distinct from the planner-stall signal already added.

At 96.2–96.5 s the projected endpoints remain invalid and the map reports `unreachable`. `check_route_progress` now retires them, but the next projection bypasses the failed-goal filter. The next returned endpoint is respectively 0.493 m, 0.092 m, and exactly 0 m from an active failed goal. Frozen-source prefix replay reproduces these retirements and reselections. Across 85–99 s, 133/141 replayed goals match recorded goals within 1 m; bounded search scheduling explains why the remaining comparisons must not be treated as a deterministic game replay.

At the 89.4/90.7 s selection, an already-scored, valid, nonfailed cover point `[-23.182361, 17.770555, -1.304178]` is available. At 96.2–96.5 s all twelve generated cover candidates are filtered by existing failures, so simply rejecting the bad projection without a bounded alternative would leave the bot at its out-of-zone origin.

The fixture records which failed-goal and cover lists were reconstructed by source replay; these were not additional fields in the live observations.

## Implemented correction

The change is confined to `safe_goal`'s projection path and its helper; ordinary cover scoring, recovery behavior, movement validation, zone priority, and fine-route implementation retain their existing roles.

1. Form the existing projected point and set its feet height from terrain. Accept it only if the actual radius/height passes `point_clear`, its body fits in the future circle, and it is outside every active failed-goal exclusion. A valid projection retains the existing behavior.
2. If it fails, retain the already-generated candidates that satisfy those same endpoint/zone/failed-goal checks. Rank them with the existing position and travel costs; do not discard a validated incumbent when the deadline expires.
3. Add at most eight further inward samples on the existing projection ray, with spacing `max(8, 2 * body_radius)`. The 8 m spacing reuses the failed-goal exclusion scale; the body-diameter floor avoids redundant probes for large bodies. Clamp radius to zero and deduplicate. When the origin lies outside the future circle, ordinary scoring reserves 1.5 ms inside the existing `safe_goal` deadline for endpoint checks. Exposure scoring of alternatives starts only with at least 2 ms left; otherwise the already-validated incumbent is retained. Each projected candidate gets fresh terrain height and the same full-body/zone/failed-goal checks before scoring. Timing is cooperative around atomic geometry calls, as in the existing map API.
4. If no validated future-circle endpoint exists within the budget, return an explicit current-position hold fallback instead of a fabricated in-zone coordinate. Keep rotation urgent and retry on the normal short cadence. A hold is a failure to find an endpoint, not a claim of successful navigation. Do not bypass failed-goal exclusions for a nontrivial destination, command a forced move/jump, or relax collision checks.

Before implementation, nine endpoint probes (original plus eight inward samples) found valid, nonfailed, in-zone alternatives at all three audited states: at 89.4 and 96.3 s the first accepted inward distance was 56 m; at 96.5 s it was 40 m. Ring-only offsets of up to +/-32 m found no valid nonfailed point, so an arc-only repair is insufficient for this recorded footprint. These are endpoint diagnostics, not proof of a safe route or improved score.

## Validation

All 17 focused tests pass in `tests/test_zone_goal_projection.py`. The 51 strategy, 44 orchestration, and 17 navigation-stall tests also passed after the helper was added. The final helper benchmark used 50 calls at each of the three recorded states with a 1.5 ms deadline: zero invalid non-hold endpoints and zero holds; medians 0.32–0.41 ms and overall maximum 1.12 ms on the local machine. This is a helper benchmark, not a full-policy timing or official-score result.

The focused regressions cover:

- Recorded 90 s body and map: selected projected destination must be body-clear and in the future circle; the original blocked coordinate must not be returned.
- Recorded 96.3/96.5 s failure lists: a candidate inside an active failed-goal radius cannot be reselected through projection. A valid inward or existing-cover alternative must be used when available.
- Valid original projection: preserve the previous coordinate and ordinary behavior.
- Large body, arena bounds, terrain feet height, and exhausted deadline: no invalid/fabricated endpoint; preserve a validated incumbent or explicit hold.
- No available valid endpoint: hold safely and retain urgent rotation, without adding blacklist entries or forced movement.
- The actual Bot rotation state when no validated endpoint exists: keep urgent rotation and return neutral movement without a forced jump or blacklist mutation.

Full Bot timing and real-map route mechanics remain part of the combined candidate's validation. Endpoint success alone does not count as connectivity, survival, or official-score improvement.

The captured branch had this defect; the new helper removes its unchecked return path. It is separable from official score variation. The latest official aggressive score at implementation time was 4.63; historical best was 4.75. This correction has no separate official score yet.
