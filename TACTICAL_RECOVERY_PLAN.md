# Fix a reproduced tactical movement deadlock

The aggressive private run contains two sustained stationary windows despite a distant navigation goal, nonzero navigation, valid current body placement and available movement corridors. This is a controller candidate-selection failure plus a monitoring blind spot; the evidence does not support relaxing collision tolerances.

The fractional-speed candidate and separate intent-aware diagnostic are now
implemented. This document preserves the original pre-fix evidence and design;
global route connectivity remains under investigation. Local collision-clear
progress alone does not establish an escape, survival benefit or official score.

## Captured evidence

Source: `work/aggressive-v1-live/20261121T122744Z-578e/policy-source`; observations/actions: `match-01/trace.jsonl`. The frozen pre-fix run placed third, with no kills, three cubes, and 285 zone damage. It is one private FFA diagnostic, not an official coordinated-practice scoring comparison.

| Captured time | Position | Fresh navigation | Route | Original result |
|---|---|---|---|---|
| 90 s | (-36.26, 82.95, -0.31) | (-0.1823, -0.9832) | ready | neutral, fallback, not stuck |
| 103 s | (-31.75, 54.68, -1.44) | (-0.2218, -0.9751) | unreachable | neutral, fallback, not stuck |
| 118 s | same as 103 s | same as 103 s | unreachable | neutral, fallback, not stuck |

At each captured state, velocity is zero and no laser charge slows movement.
Energy is 100 at 90/118 s and 70.3 at 103 s; the fixture preserves these values.
The three-cube body has radius 2.875 m and height 10.35 m. Both positions pass
`point_clear`; terrain differs from observed feet by less than 0.004 m.
Two-metre sweeps in all 16 sampled directions pass. Thus neither energy
starvation, stale charge, initial overlap nor a generally blocked position
explains the neutral output.

Fresh frozen-map navigation followed by the original planner reproduces neutral fallback at all three exact observations. The original trace reports only three geometry checks per call, despite 27 generated candidates; isolated reproduction checks three or four before its clock reserve expires.

The planner ranks full-speed constant-direction 0.6 s trajectories cheaply, then checks at most six against geometry. It can spend the available time rejecting highly ranked boosted/full-speed candidates and never reach a valid one. At 90 s the exact full walking navigation vector is already valid for the complete horizon, yielding 6.52 m progress. At 103/118 s full-speed navigation fails, but a constant half-throttle unboosted vector passes all 12 physics steps and yields 3.60 m progress. Quarter throttle also passes and yields 1.88 m. Other full-speed directions are legal, but are not reached within the normal checking order.

| Time | Neutral existing urgent cost | Half-throttle cost | Known bullet/beam cost, half throttle | Half-throttle geometry median |
|---|---:|---:|---:|---:|
| 90 | 14.70 | -0.53 | 0 / 0 | 3.60 ms |
| 103 | 0.30 | -13.22 | 0 / 0 | 6.99 ms |
| 118 | 58.26 | 35.75 | 0 / 0 | 6.63 ms |

Costs use the existing urgent progress weight, existing full projectile/beam/zone terms and exact exposure queries. These are local trajectory comparisons, not a prediction of surviving the match. The half-throttle path at 103 s becomes more exposed than the stationary position; existing urgent cost still prefers its progress. At 118 s it remains outside the zone during the short horizon; its zone cost is retained.

Reproduction artifacts: `work/aggressive_stall_geometry_probe.py`, `work/aggressive_stall_trajectory_probe.py`, `work/aggressive_stall_fallback_probe.py`, and their corresponding `_results.json` files.

## Implemented narrow tactical change

1. Preserve ordinary selection on the first call. Record a recovery-eligible failure only when a grounded actor has nonzero requested navigation and the planner had no validated candidate, rather than deliberately selecting a neutral candidate.
2. On the next such call, give one constant half-throttle, unboosted navigation candidate early geometry priority inside the existing 14 ms movement deadline. Use the current observed velocity, cube-scaled body, current laser charge multiplier, vector acceleration, support/air transition model and the complete 0.6 s horizon. Do not normalize this candidate back to length one.
3. Keep the existing projectile, aimed-beam, zone, progress and exposure costs. A candidate is usable only after a complete swept-body validation and complete hazard scoring. Compare against the neutral/braking cost so that movement into a known projectile does not become mandatory. Seed the validated best candidate, then examine ordinary candidates with the remaining budget; ordinary safer candidates may still win. An exhausted validation never authorizes motion.
4. Count the priority check against the existing geometry-check limit. Its measured geometry cost is approximately 4–7 ms here (occasionally 8.9 ms), so reserve it before the current cheap-ranking work rather than promising a late 2 ms fallback. Bound optional exact LOS queries by remaining time, using the existing conservative exposure estimate otherwise. Do not increase the full-policy 50 ms limit or existing tactical 14 ms window.
5. Keep neutral when all tested trajectories are blocked, insufficient time remains, navigation is absent, or the cost comparison favors braking. Do not force jump, boost or wall traversal. This supplies a legitimate candidate; it does not guarantee escaping an unreachable global route.

Constant fractional input is preferable to a one-action pulse followed by hypothetical braking here. Protocol line 226 explicitly supports slower walking for input length below one. A continually re-issued half-throttle command matches its predicted 0.6 s command; there is no assumed future brake that the policy never sends. The current integrator already supports fractional direction components. A pulse/brake state machine is therefore unnecessary for these reproduced states and should be deferred.

## Separate intent-aware monitoring

The existing stuck detector stores the magnitude of the final action. Neutral fallback consequently makes its required mean movement greater than 0.6 impossible. `check_route_progress` runs before tactical selection, requires near-zero navigation, and excludes engage/loot; these observed nonzero-nav failures bypass it too.

The separate implemented detector is documented in
[NAVIGATION_RECOVERY_PLAN.md](NAVIGATION_RECOVERY_PLAN.md). It tracks prior
navigation demand, neutral fallback and observed displacement, distinguishing
quiet healing, arrival and deliberately selected braking. Its window is more
than 1.3 s of a two-second history, more than eight samples, less than 1.3 m net
movement, mean navigation above 0.6 and more than 60% neutral fallback. Actual
progress clears the flag; refreshing a goal does not. It is diagnostic only and
does not change goal expiry, force movement/jumps, or blacklist resources.

## Required regression and timing checks

- Trimmed mechanics-only observations at 90, 103 and 118 s, plus cropped official geometry/terrain. Preserve exact coordinates, velocity, body dimensions, zone, projectiles, actors and charge state; remove account/session material.
- After a reproduced ordinary neutral geometry fallback, the next call returns a nonzero, unboosted, fully validated trajectory within its normal budget. At 103/118, verify fractional speed is retained and its actual predicted sweep is clear.
- The 90 s state demonstrates starvation of an already valid full-walk candidate, not solely horizon overconstraint.
- Fully blocked geometry remains neutral. A newly observed imminent projectile, charging beam, zone crossing, current momentum or charged movement must be evaluated on the recovery candidate and may reject it.
- No navigation, intentional neutral selection, normal healing, exhausted deadlines and airborne actors do not trigger the new grounded fallback priority.
- Repeated calls are checked from updated observed positions/velocities in a small mechanics rollout, including an obstacle at the end of the corridor; no repeated-input future-brake fiction.
- Independent actualBot intent-history cases cover engage/rotate demand, real observed progress, short 0.2–0.4 s delays, quiet healing, selected neutral without fallback, and loot non-blacklisting.
- Run focused tests, full suite, complete-policy recorded-observation timing and exact Docker timing. Report online queue sensitivity separately; captured private delay does not establish official scorer delay.

The described local candidate and diagnostic are implemented and regression
tested. Global reachability and actual escape from the late shrinking zone
remain separate validation questions; local collision-clear movement alone
does not establish a better official score. Final-candidate tests and timing
belong in VALIDATION.md and must not be confused with the pre-fix table above.
