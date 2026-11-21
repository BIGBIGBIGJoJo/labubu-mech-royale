# Design for a measured practice score of at least 7

The retained baseline is `39b6d509af8e82b0ceb9e1c430dd964674d7488e`, officially
scored 4.75 in receipt BB-12F2E201. The target is a verified official practice
score of at least 7. Passing tests or winning a private match does not satisfy it.

The controller remains an adaptive policy for partial observations. Every
component must use live configuration and current upgraded stats, expose a
diagnostic reason for its decision, and respect the full 50 ms response budget.

## Component algorithms and evidence gates

| Component | Algorithm | Robustness and evaluation |
|---|---|---|
| Input and state | Official newest-observation wrapper; monotonic observation time; bounded memory of damage sources, objectives and previously seen resources | No stale tick, no hidden match-seed dependence, local validation fails on exceptions |
| Terrain and geometry | Spatially indexed solid prisms, bilinear terrain, body clearance and exact line intersections; reuse identical terrain endpoints within a ray | Bridges, holes, low cover, cube growth, directional slopes, and no cross-query cache leakage |
| Navigation | Bounded incremental route search plus validated local steering; destinations must be reachable for current dimensions | Diagnose commanded progress versus actual displacement; never equate zero final movement with no movement intent |
| Tactical movement | Roll out feasible acceleration/braking/boost trajectories; reject collisions, then compare projectile risk, exposure, zone safety and progress | Blocked candidates cannot exhaust the useful shortlist; preserve a physically valid escape or brake fallback |
| Visibility and threat | Keep outgoing shootability distinct from incoming exposure; estimate incoming rays from enemy muzzle to our body | Unknown exposure is not safe; unequal heights, cube sizes and cover must be tested. This separation is the next modeled improvement, not yet integrated in the first candidate |
| Gun | Earliest positive moving-target intercept; shared torso aim; test actual launch ray at every fire opportunity in the held action | Clear desired aim alone cannot authorize a shot while the actual barrel still points into cover |
| Laser | Explicit charging/releasing state; damage-aware releases, alignment and actual-ray checks; preserve necessary emergency/timeout release | Validate charge slowdown and escape tradeoff using real traces; cannot assume an existing charge is cancelable |
| Lightning | Range, cone, LOS and energy checks; coordinate the shared aim with other weapons | Assess the damage cost of closing distance before using a short-range spacing preference |
| Mortar | Ballistic trajectory with gravity, pitch limits, obstruction and self-splash checks; coordinate shared aim | Verify launch height and physics timing against current evidence before changing the model; old mechanics replays may have different tuning |
| Target selection | Preserve continuity while considering shootability, attacker pressure, attainable damage and finish opportunity | Test target decisions against weapon readiness and actual hits; avoid unconditional nearest pursuit or blanket disengagement |
| Recovery | Enter/exit with hysteresis; find an achievable break in incoming damage; suppress damage while a useful quiet healing interval is attainable | Measure time to break contact, first regeneration and HP recovered; don't infer success from the recover state name |
| Economy | Evaluate acquisition cost and zone/exposure, then complete approach -> destroy/take -> collect -> leave with explicit abort conditions | Record opportunity, admission, completion and abandonment; positive fixtures must activate inside restricted Linux |
| Upgrades/loadout | Compare current survival and weapon needs using the actual offer and held weapons | Fixed rankings remain hypotheses until official comparisons establish benefit |
| Safe zone | Predict circle at arrival and preserve a feasible path and endpoint | Test shrink transitions, invalid projected goals and late phases; avoid route oscillation that produces travel without progress |
| Scheduling | Reuse exact work within a decision and bound optional search; keep transport margin | Measure full Linux round-trip latency, dense-case policy latency and positive feature activation |
| Evaluation | Freeze source, run regression and runtime checks, inspect normal private traces, then obtain official score | Private games have compressed zone schedules and different opponents; record adverse results and preserve the accepted best |

## First candidate

The first candidate changes three mechanisms only: tactical shortlist starvation,
actual gun/laser firing-ray validation during torso rotation, and exact reuse of
shared terrain-cell endpoints within a line query. Other high-level strategy
changes are deferred until current diagnostic evidence identifies the relevant
failure. Previous lower-scoring branches are evidence to examine, not changes to
merge wholesale.

## Iteration rule

For each bad result, retain the exact source and score, find a specific failed
mechanism in available observations, reproduce it, change that component, and
retest the integrated controller. A higher private placement does not prove an
official improvement. A test pass proves only the behavior it actually covers.
