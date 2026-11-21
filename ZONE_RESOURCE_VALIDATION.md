# C1 resource/rotation boundary and isolated prototype

This is a conditional trace diagnosis and tested policy prototype, not a counterfactual game, private-match result, or official score improvement. The isolated worktree is `work/labubu-economy`, branch `goal/economy-seven`, based on frozen `39b6d509af8e82b0ceb9e1c430dd964674d7488e`. This report records pre-submission validation.

## Observed boundary failure

The C1 private trace is `correctness-ab878-20261121-163846/trace.jsonl.gz`. Its source was frozen ab878a. The bot earned three cubes before 27.0 s, then no more despite two kills. It recorded zero zone damage; the later rotation was anticipatory.

At 65.7 s, the old current-position test against the circle twelve seconds ahead has +1.12 m slack and chooses loot. At 65.8 s, that slack becomes -0.16 m and it aborts for rotation. Yet `resource_goal` still admits the twelve-cube pile 44.10 m away, because that function tests the pickup endpoint at walk ETA +4 s instead. At 75.0 s, +1.79 m slack briefly permits a 52.43 m backtrack to a remembered cube; at 75.3 s, -0.18 m slack causes rotation again. The two tests disagree about the same objective and have no commitment or release hysteresis.

The first kill at 58.5 s creates twelve cubes at (-306.63,-92.19,-5.13); the bot never gets closer than 36.30 m. A second pile appears at 71.3 s near (-222,-112), and a different visible pile is about 17 m away at 72 s. The prototype does not assume either distant pile is safe merely because it is visible or valuable.

The prior `origin/pursuit-resource-v1` (`b78a5da`, recorded official 4.54) adds bounded pursuit detours but retains the same urgent-12 and endpoint-ETA+4 gates. Urgent rotation always preempts those detours. Its three-second total/two-second extra detour constraints cannot repair the 44 m opportunity at this boundary. No code from that broad candidate was copied.

## Online route witness at 65.8 s

Current position is (-325.31,-52.24,-4.97), 3 cubes, full 1568 HP, grounded, laser charge zero. The announced circle is center (36.43,-0.05), radius 380; next center (143.88,49.44), radius 240; shrink starts 77.5 and ends 97.5. Live walk speed is 11.7 m/s and ground acceleration is 58.5 m/s². These are captured configuration/state facts.

The new component derives an exit **from this observation alone**: (-269.7048,-82.2394,-5.20). It does not use any future recorded position or the old controller's future rotation goal. Both complete direct ground segments, self→pile and pile→exit, pass the existing map's cylinder sweep after including all twelve cubes: radius 4.375, height 15.75. Clear endpoints alone are never accepted as route evidence.

With startup/turn delays, the modeled trip takes 8.038 s. It additionally checks four seconds of stationary exit reserve. Minimum clearance includes the enlarged radius plus an 8 m margin and remains +2.140 m. This is a route witness in the existing geometry/timing model. Tactical avoidance, other actors, future unknown loot, and unmodeled engine behavior can change actual travel.

Any currently active laser charge, including a charge below the 0.15 s release minimum, rejects admission. Thus the timing never assumes an unfinished charge vanishes immediately. Admitted leases use the existing emergency combat flag to prevent new charge, while preserving the ordinary combat target. Ground navigation and the tactical rollout receive the anticipated larger radius/height. A stuck lease cancels before issuing a jump; it cannot rely on a grounded route while jetting over an obstruction.

## Implementation and API

`zone_resource.py` contains `ZoneResourcePlanner(config, arena)`:

- `rotation_required(obs, stats)` keeps the existing twelve-second/8 m trigger, and releases its latch only at +6 m slack.
- `plan(obs, candidate, stats, deadline)` validates the current observed resource, online exit, full route, anticipated size, current acceleration/velocity delay, moving zone, and exit reserve. Returns a plan or `None`.
- `start_lease(...)` starts a stable pickup/exit commitment after the caller's unchanged resource value/exposure checks.
- `continue_lease(obs, stats, eligible=..., deadline=...)` validates the same objective and fixed exit against current state. Collection transfers to exit. Missing/moved resource, lost progress, charge, unsafe route, new zone, expiry, or caller preemption cancels it.
- `lease_key`, `exiting`, `collection_observed(...)`, and `cancel(...)` support integration.

`bot.py` now repeats the original resource scoring/exposure checks for the leased key using an optional filter; the formulas and regular combat target selection are unchanged. Recovery preempts the lease. New urgent admissions require current observed loot, grounded in-zone state, zero active laser charge, and a complete witness. The existing 32 ms decision budget is unchanged: resource scoring receives at most 4 ms and leaves 21 ms, while lease planning receives at most 6 ms and leaves 18 ms for navigation/combat/tactical work. All geometry calls are checked against the deadline, but a single existing synchronous map query can overrun a soft deadline slightly.

The six-meter latch gap, four-second reserve, two-second progress/retry window, 0.75 m progress step, three exit angles, and startup/turn delay allowances are **policy/model hypotheses**, not engine constants or empirically optimized parameters. The direct-route requirement is intentionally conservative; a complete detour may exist even when this component rejects an opportunity.

## Validation and limitation

147 unit/integration tests pass. New fixtures cover actual 65.8 s online route/target/charge/movement-size activation, actual 75 s remembered-only backtrack rejection, positive progress and pickup-to-exit transfer, latch release, expiry, stalled progress, recovery/exposure preemption, active and subminimum charge, rapid shrink, slow acceleration, unexpected cube growth, and clear endpoints with a blocked corridor. The combat contract checks gun aim preservation, new-charge suppression, and held-laser release/shared aim. Synthetic modifications are tests of conditions, not claims about recorded gameplay.

Restricted Linux image `labubu-score7:economy` used linux/amd64, one CPU, 512 MB RAM, no network, read-only filesystem, and user 65534. The checker and child bot both ran **inside** that image using `/kit/check/check.py --map-dir /arena -- python3 -u /bot/bot.py`; map loading was verified at 259 prisms. Checker: 300/300 on-time, zero bad/wrong/late answers, readiness 2967 ms, p99 33.9 ms, maximum 36.6 ms. Dense 120-observation stress: p99 31.80 ms, maximum 33.03 ms, no exceptions or >50 ms responses.

Full-prefix restricted Linux conditional replay covers 176 observations at 58.5–76 s. It activates 41 frames across 5 admissions; the 65.8 s fixture activates in 2.25 ms of component work, with full `Bot.act` 33.98 ms, target 11, gun fire enabled, laser off, no jump, no tactical fallback. Window total p50 31.10/p99 34.74/max 35.50 ms, no exceptions or >50 ms. There are three tactical fallbacks: 58.8 s (rotation), 59.9 s (active lease), and 66.6 s (rotation after lease validation failed).

Timing sensitivity remains material. Host conditional replay activates 53 frames versus 41 under restricted Linux. The exact 65.8→66.6 route independently revalidates 10/10 times inside the same Linux limits (admission 2.10–2.46 ms; continuation 1.71–2.10 ms). Thus deadline pressure can conservatively cancel a geometrically valid lease. It returns to ordinary rotation; it does not extend the decision budget or assert an unfinished proof. If this proves frequent in further testing, the next step is a geometry-proof cache with fresh current-position/body/zone checks, not a larger total action budget.

Artifacts: `economy-validation.json` records exact source hashes and validation; `economy-linux-conditional.json` contains per-frame restricted results; `economy-component-conditional.json` is the earlier standalone component scan; `economy-integrated-c1-conditional.json` is host full-prefix integration replay. The standalone scan found 11 raw boundary changes versus 5 with the latch, but this is conditional behavior on the recorded trajectory, not a prediction of a new match.
