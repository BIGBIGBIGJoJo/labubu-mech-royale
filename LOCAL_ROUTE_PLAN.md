# Historical experiment document

This file records earlier experimental branches. The current controlled
experiment is described in PROGRAM_DESIGN.md and FIRST_MAGAZINE_PLAN.md. Its runtime
does not include all mechanisms proposed or tested below.

# Local route recovery

This candidate addresses a reproduced navigation deadlock in the aggressive bot. It preserves the existing combat policy, energy management, tactical controller and ordinary navigation. The last submitted aggressive version scored 4.63; this route change has not yet established a higher official score.

## Observed problem

At the captured 90, 103 and 118 second observations, the body is valid and ground corridors exist, but the five-metre navigation graph cannot represent the narrow entrances reliably. The later pocket contains only two connected coarse cells; the northern corridor contains six. A local half-metre search finds a continuously traversable ground connection between them and then to a larger area. Jumping is unnecessary for these measured routes.

Simply waiting only on an unfinished A* search, changing waypoint arrival to 1.5 m, or restarting after a coarse-cell change did not resolve the continued-motion failure. An arbitrary local exit also failed: it could select another small pocket. The implemented recovery therefore requires a checked connection to a strictly larger coarse component, measured with a probe capped at eight cells. This is a useful routing heuristic, not proof that the original strategic goal is reachable.

## Implemented behavior

`LocalRouteRecovery` composes `ArenaMap`. Ordinary calls delegate unchanged. Root can request recovery using its existing sustained planner-stall signal, including when A* reports `ready`. An exhausted coarse search can also activate recovery when observed horizontal speed is below 2 m/s and the strategic goal remains more than 8 m away. A moving pursuit alone does not activate it.

Recovery requires an explicit grounded observation and feet within 0.05 m of terrain. Roofs, elevated bridges and airborne states retain existing routing. The initial component is measured at the current recovery anchor, with a swept-body connection to the nearest coarse cell; a retained historical A* start is never trusted for this classification.

The local search uses a 0.5 m lattice in a bounded neighbourhood. Every accepted edge uses the current cube-scaled body and the same terrain/collision checks as ordinary movement. Work resumes across observations. Components already reaching the eight-cell probe cap are declined because a strictly larger component cannot be established within that probe. Failed anchors suppress repeat work until meaningful observed movement or a body/map change.

A discovered route ends at the checked coarse-cell centre, not merely near a narrow connection. Each fine-point-to-coarse-cell link has its own swept validation. The tactical controller receives a local exit goal and continues to evaluate current velocity, charge, projectiles, beams, zone risk and collision. It retains its existing half-throttle fallback, 14 ms allocation and six-check limit. Recovery adds no jump, jet, forced boost, reduced body or relaxed collision tolerance.

Strategic goal refreshes update search preference, including the future-zone penalty, without discarding valid geometry or restarting discovery. Body/map changes, a vertical-level change, major relocation or a backwards clock invalidate the episode. Reaching the current strategic goal cancels recovery immediately, preserving an intended hold. An episode expires after 30 simulation seconds. Completing an exit clears the old coarse search before normal routing resumes from the current position.

The captured 90 s strategic endpoint itself fails exact body clearance. Local recovery can leave the corridor but cannot make that endpoint valid. Goal validation and retirement remain root policy responsibilities.

## Integration

```python
recovery = LocalRouteRecovery(arena)
navigation, tactical_goal = recovery.navigate(
    obs, strategic_goal, stats, request_recovery, deadline
)
```

The module exposes `active`, `status` and bounded `last_report` telemetry. Root retains the strategic goal and passes the returned tactical goal only to movement. While status is `local_searching` or `local_following`, root must not repeatedly retire an equivalent strategic goal and disrupt the episode. `local_declined` and `exit_reached` identify terminal outcomes. Missing coarse-map APIs decline gracefully; ordinary test arenas can continue to delegate navigation.

## Work limits

| Resource | Limit |
|---|---:|
| Accepted fine nodes | 2,048 |
| Fine point cache | 16,384 |
| Directed fine edges / exact exit links | 16,384 each |
| Coarse component jobs / exit-cell entries | 128 each |
| Reachable cells per component probe | 8 |
| Remembered failed anchors / episode reports | 8 each |

The search uses the caller's navigation deadline, reserves 1.5 ms for steering, checks time between neighbour operations and leaves 0.7–0.8 ms before starting another expensive query. A partially expanded neighbour resumes on the next observation. Individual Python geometry queries and process scheduling are not preemptible, so this is bounded work rather than a hard real-time guarantee.

## Validation

Twenty-four focused tests cover captured geometry, exact swept links, stale coarse origins, deadlines, bounded cache failure, goal refresh and arrival, body/map changes, elevated/airborne/missing-grounded observations, unchanged ordinary delegation, failure suppression and completion handoff. The fixtures contain mechanics and a cropped official map, with no session or authentication data.

The production module was also run with the unchanged tactical controller on the full map for 40 simulation seconds from each captured start, including incremental discovery and every actually issued 0.1 s command. All 1,200 applied sweeps were clear:

| Start | Displacement at 20 s | Displacement at 40 s | Larger-component exits completed |
|---|---:|---:|---|
| 90 s | 31.85 m | 31.85 m | Six-cell corridor to capped-eight area at 10.7 s |
| 103 s | 22.48 m | 41.33 m | Two to six cells at 12.0 s; six to capped-eight at 27.5 s |
| 118 s | 22.59 m | 41.30 m | Two to six cells at 11.4 s; six to capped-eight at 27.6 s |

These checks hold enemy observations fixed, simulate no combat damage and include no network delay. They show route discovery and continued collision-clear movement, not survival or score improvement. Discovery latency is material: a narrow exit can take several simulation seconds to find. The 90 s case deliberately retains its original recorded invalid strategic goal and subsequently holds toward it; the separately implemented ZONE_GOAL_PLAN.md correction rejects that endpoint in the full controller.

One fine-discovery call in that run took 17.28 ms; the other two cases peaked at 5.61 and 4.61 ms. Six focused instrumented repetitions then measured 534 active-discovery calls with a maximum of 5.12 ms and none above 6 ms. The original outlier was not instrumented, so its cause is unconfirmed. Full-policy and Docker validation must include active fine discovery and retain the competition's 50 ms limit; the outlier is not presented as a guaranteed six-millisecond bound.

An additional full `Bot.act` timing check seeded recovery at each captured failure and exercised 390 calls with local recovery active. Maximum full-policy times were 40.03, 31.26 and 31.47 ms respectively, with zero calls above 50 ms and finite JSON actions. These repeated fixed observations are a cost stress test, not a second gameplay result.
