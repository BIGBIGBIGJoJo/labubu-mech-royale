# Historical experiment document

This file records earlier experimental branches. The current controlled
experiment is described in PROGRAM_DESIGN.md and the three current strategy-agent plans. Its runtime
does not include all mechanisms proposed or tested below.

# Recovery goal follow-up: exact replay and bounded proposal

This plan was reviewed as a work-only investigation before implementation on
the separate selective-v5 branch. The preceding permission candidate is frozen
as `01df3dc` and submitted as BB-AC10AB33, which scored 2.69. The earlier energy
candidate scored 2.33; retained historical best is 4.75 and the objective remains
6.0. This narrow recovery-goal change is now implemented in the aggressive
candidate. Its original prototype measurements below remain separate from final
candidate validation. This change itself does not alter enemy-fire permission.

## Reproduced cause

`work/recovery_goal_replay.py` imports the private run's captured `policy-source`, replays every observation that originally received an action, and instruments `safe_goal` without changing its ranking. From 110–122.7 seconds, **128/128 goals matched within one metre, and 126/128 movement vectors matched within 0.1**. All late self/nearby selections were reproduced. Host deadlines can still change candidate work; this is a policy replay, not an alternate game.

At 117.7 and 118.4 all 13 generated candidates were scored, with about 15 ms available and about 10 ms consumed. Neither selection was caused by deadline truncation or a failed route. The bot explicitly scored its current point as exposed, rather than mistaking it for cover.

| Time | Candidate | Exposure/zone position cost | Travel penalty | Total |
|---|---|---:|---:|---:|
| 117.7 | Current point | 200.640 | 0 | **200.640** |
| 117.7 | Nearby wall point, 4.70 m away | 199.685 | 1.034 | 200.719 |
| 117.7 | Northern wall point, 14.28 m away | 198.927 | 3.141 | 202.068 |
| 118.4 | Current point | 195.209 | 0 | **195.209** |
| 118.4 | Northern wall point, 13.85 m away | 195.109 | 3.047 | 198.156 |

The existing `0.22 * travel_distance` term outweighs modest endpoint safety improvements. Recovery then keeps a nearby goal for up to 1.2 seconds. While the goal is close, navigation can be zero, and the tactical controller penalizes displacement when navigation is zero; delayed commands and later goal changes create local turning. That explains the selection mechanism, not the precise server trajectory.

Candidate generation compounds the issue. Recovery adds only three 40 m retreats at away-angle offsets 0 and ±0.7 radians. At 117.7, their endpoints violate the unchanged 22-second future-circle test by 35.95, 24.09, and 33.34 m. None is admitted. The future circle is centred at `(11.14, 137.78)` with radius 140, while the mech is at `(138.24, 125.13)`, near its eastern edge. A lateral route can stay inside that circle, but those three outward rays do not find one.

There is no evidence that the boost recharge latch caused the late failure. Its single recharge interval ended at 113.5. During 117.7–122.7 the mech traveled 53.04 m with only 6.62 m net displacement, while energy remained 42.58–82.18. The prior movement report contains the complete energy findings.

## Proposed narrow fallback

Prototype: `work/recovery_goal_prototype.py`. It is not imported by the bot.

Apply only when all of these hold: mode is `recover`, the chosen goal is within 8 m, its existing exposure/zone cost is positive, at least one threat has LOS, and the most recent damage is within the observed HP regeneration delay. Preserve quiet healing, effective cover, longer existing routes, and all `rotate` decisions.

1. Generate at most eight 24 m local directions around the weighted away vector, adding sideways directions absent from the existing three-ray fan.
2. Project endpoints into the **same** future circle with an 8 m body margin. Reject displacements outside 8–24.25 m, near-duplicate points, failed-goal neighbourhoods, and any path failing the current cube-scaled `move_clear` sweep.
3. Evaluate existing position cost only after the sweep passes. A replacement must improve that cost by at least 1 point. Use `0.04 * travel` only for these verified short escape candidates; preserve the existing 0.22 penalty for ordinary travel and long cover routes.
4. Give the fallback at most 3 ms from the existing `safe_goal` deadline, retaining a 0.8 ms margin before a geometry/cost call. If the caller lacks that remaining budget, keep its original answer. Do not increase the 32 ms policy deadline or the tactical planner budget.

The radii, thresholds and 0.04 coefficient are proposed strategy parameters, not competition constants. This avoids globally lowering travel cost, which the broad preliminary probe showed could instead choose a 65 m cover endpoint without establishing a reachable route.

## Exact-state prototype results

| Time | Baseline | Prototype | Endpoint distance to attacker | Position cost change |
|---|---|---|---|---:|
| 117.7 | Hold `(138.24,125.13)` | Move 15.70 m to `(140.106,140.721)` | 69.84→75.22 m | 200.640→197.804 |
| 118.4 | Hold `(141.09,125.84)` | Move 15.39 m to `(140.095,141.199)` | 73.06→75.53 m | 195.209→193.938 |

Both alternatives have a clear full-body ground sweep and 8 m clearance inside the same future circle. Each was selected in 100/100 repeated probes. Nine other captured `safe_goal` calls retain their baseline answer: meaningful existing recovery routes, the quiet 116.4-second point, rotation calls, and the 121.5-second case where the bounded candidates do not improve position cost enough.

Across 1,100 isolated fallback calls, p99 was 2.656 ms and maximum 2.916 ms. These measurements exclude the preceding baseline selection and are not a full-policy deadline guarantee. Original late calls had roughly 4–6 ms remaining after their baseline selection, but integration must inspect the actual remaining deadline rather than assume that margin.

## Limits and validation required before adoption

- These alternatives remain exposed; they improve modeled spacing and local motion, not actual verified concealment. The score differences are small. They do not establish that either 441-damage laser hit would be avoided or that the match score would improve.
- The prototype changes two earlier decisions. Later logged enemy and self observations cannot be treated as a valid alternate trajectory after those changes. No counterfactual survival claim is made.
- At 121.5 there is no admitted better short alternative. The bounded fix intentionally retains the original answer rather than forcing travel into worse pressure or abandoning zone safety.
- Existing position scoring uses endpoint geometry and a heuristic threat value, not a travel-time damage model. A broader incoming-muzzle/own-body exposure review would be a separate change.
- Production tests should cover protected healing/cover, no recent damage, rotation preservation, real-map captured 117.7/118.4 cases, blocked segments, failed-goal rejection, insufficient deadline, and no lower-cost safe alternative. Then run full-policy timing and a separately frozen private diagnostic before considering a submission.

Evidence files: `work/recovery_goal_replay_results.json`, `work/recovery_goal_probe_results.json`, and `work/recovery_goal_prototype_results.json`. The broad probe is exploratory; the narrow prototype above is the actual proposal.
