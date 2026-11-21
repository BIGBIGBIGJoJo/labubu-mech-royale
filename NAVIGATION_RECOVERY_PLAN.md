# Detect navigation demand lost to neutral planner fallback

This plan preceded implementation. The separate root navigation-stall diagnostic
is now implemented and covered by 17 focused actual-Bot tests. It does not change
movement commands, jump behavior, goal-cache expiry or resource blacklisting.
Safe trajectory selection is a separate change described in
[TACTICAL_RECOVERY_PLAN.md](TACTICAL_RECOVERY_PLAN.md).

## Recorded evidence

Source snapshot and trace: `work/aggressive-v1-live/20261121T122744Z-578e/policy-source/` and `match-01/trace.jsonl`. Aggregate measurements: `work/aggressive-stuck-history-audit.json`.

| Interval | Decisions | Position change | Neutral / fallback | Reported stuck | Goal distance | State |
|---|---:|---:|---:|---:|---:|---|
| 90–96 s | 61 | 0 m | 58 / 58 | 0 | at least 19.35 m | rotate |
| 103–118 s | 151 | 0 m | 151 / 151 | 0 | at least 90.25 m | 8 recover, 143 rotate |

First interval route status was ready for 56 observations and unreachable for five. Second interval was unreachable throughout; HP fell from 272.26 to 2.26 while energy rose from 70.3 to 100. These are observations, not an estimate of the score that a fix would produce. Geometry agent independently reproduced nonzero navigation at 90 s and 103/118 s, followed by neutral tactical fallback; this report does not duplicate those geometry calculations.

## Why the existing signals miss it

`Bot.update` stores `(time, position, magnitude(last_move))`, where `last_move` is the final tactical command. The stuck condition requires more than 1.3 s of near-zero displacement and average final movement demand above 0.6. A planner that repeatedly returns zero drives that average to zero, so the detector cannot identify the observed failure.

`check_route_progress` runs before tactical choice. It watches raw navigation, not final movement, and only runs for recover/rotate/position. Its holding condition requires navigation magnitude below 0.1; thus nonzero navigation followed by neutral fallback bypasses that branch. An unreachable route can separately retire a goal, but this does not show that local tactical movement is still failing after the next goal is selected. Engage/loot skip this route-progress tracker entirely.

## Implemented signal

The old physical-obstruction signal and its behavior are unchanged. A separate
history, bounded to 64 samples and two seconds, records the preceding decision's
navigation demand and combined neutral-fallback result alongside position.
Translation demand is zero when the prior goal was already within its arrival
tolerance. The old history tuple still records final commanded movement.

Each sample contains simulation time, observed XY position, prior requested
navigation magnitude and whether the prior final command was neutral fallback.
The latter combines the final move magnitude and a fresh current-frame planner
report. Bot.movement's overall-deadline path now writes its own truthful report:
a validated short route is not a neutral fallback, while a blocked neutral
result is. A retained report from another decision is never reused as evidence.
Duplicate timestamps do not inflate history, and backwards time resets it.

Initial detection settings reuse existing windows rather than inventing a new timeout: at least nine observations over more than 1.3 s within the two-second history, less than 1.3 m net displacement, average requested navigation magnitude above 0.6, and more than 60% of recent observations with both neutral output (<0.1) and tactical fallback. Count only decisions whose goal remained beyond the existing 1.5 m arrival tolerance. These are explicit diagnostic parameters, not physics constants or proof of a blocked body.

Expose `planner_stalled` and `stall_reason="navigation_neutral_fallback"` separately from the existing physical `stuck`. Also expose current raw `navigation` and final movement/fallback, so future traces distinguish an absent route, deliberate braking and candidate-validation failure. Accumulate across harmless short goal replans: changing the desired endpoint cannot prove actual progress. Reset stale history when simulation time goes backwards, and clear the signal after meaningful observed displacement or cessation of movement demand.

The implemented signal is diagnostic only: it does not force a direction, jump,
retire a goal or blacklist a resource. The trace failure indicates local planner
rejection, not that a desired cube/drop is unreachable. The separately implemented
verified low-speed tactical candidate is the movement repair and can run before
this diagnostic timeout. Sweeps, projectile/zone checks and deadlines remain
authoritative. Collision-clear local motion does not prove a complete escape.

## Meaningful actual Bot.act regressions

Use the official hello/observation and existing FlatArena fixtures. Feed consecutive observations with controlled positions while exercising real Bot.act. Mock only the local tactical result and route status needed to isolate the history contract; do not replace target selection, root state arbitration or the entire movement method. Tests assert decisions/signals, not an invented game outcome.

1. **Pursuit demand lost to fallback:** healthy bot, current enemy beyond its preferred band, far goal, nonzero map navigation, unchanged position for more than 1.3 s; tactical choose reports fallback and returns neutral. Expect planner_stalled, but no blind jump, forced movement or loot blacklist. This covers engage mode, which old check_route_progress excludes.
2. **Urgent rotation demand lost to fallback:** same sustained condition with a future-zone route opposite the enemy. Expect planner_stalled while state/mode remain ROTATE/rotate and the desired zone route remains authoritative. Fire policy remains independent.
3. **Quiet healing/arrival is intentional:** recovering bot at an effective cover goal or bot at its arrival tolerance, raw navigation zero and neutral output. Even after two seconds, planner_stalled must remain false. A selected neutral candidate with fallback=false must not be labeled candidate-validation failure merely because raw navigation was nonzero.
4. **Transient fallback is not a sustained stall:** two to four neutral fallback frames followed by movement; no planner_stalled. This guards normal bounded-search exhaustion and the measured online command delay.
5. **Observed progress clears demand history:** enough XY progress to exceed the existing displacement threshold after a stall, despite later fallback frames. Expect signal reset; changing only target/goal identity without displacement must not clear the signal.
6. **Obstacle safety is preserved:** with every trajectory sweep rejected, sustained demand can be diagnosed but the action stays neutral and boost/jump remain false. The root diagnostic must never bypass the geometry decision. Geometry agent separately tests that its low-speed fallback moves only when its complete swept path is legal.
7. **Resource validity is separate:** an otherwise eligible cube/weapon goal with repeated neutral tactical fallback may trigger planner_stalled, but must not be added to resource blacklist solely by this new reason. Physical stuck detection and confirmed route impossibility retain their own established handling.

For captured-state validation, geometry agent's recorded 90/103/118 s cases should produce legal nonzero slow trajectories under the proposed fallback. Once those pass, rerun full-Bot frames with original observations/weapon state and inspect navigation, final command, fallback, route status and time budget. This remains a recorded-state decision check; only a later authorized live run can establish actual movement/survival.

Do not expand this change into global goal reranking, generic jumping, reduced collision dimensions, or relaxed urgent-zone costs. A small explicit diagnostic plus a validated slow trajectory addresses the observed mechanism and keeps the strategy comparison reviewable.
