# Validation and experiment log

Verified on November 21, 2026. Official score means mean `16 - place` over
48 practice matches. Private-room placement is a different diagnostic.

**Container-check correction:** during aggressive-v2 validation, the Windows
checker was found to rewrite `/arena` as `C:\\arena` before launching the Linux
bot. Earlier Windows-launched Docker results below establish protocol behavior
with the map fallback, not map-enabled container timing. Host real-map tests and
official scores are separate evidence. Current validation runs the unmodified
checker inside Linux with the arena mounted; preflight confirms map loading.

## Official submissions

| Submission | Commit | Practice score | Result |
|---|---|---:|---|
| BB-062E97A7 | b49715d45447840d66a3e5d24624fdbf3f43389e | 2.77 | Accepted; above the published starter baseline 1.15 |
| BB-F2B295B5 | b99310a760505c250b7afaf03e07269a4e47416d | 3.10 | Accepted; improved resource collection and targeting |
| BB-80D20692 | 7c38fba27c3feb6f52c2b74b45423f63beb33ff5 | 4.19 | Accepted; previous best |
| BB-12F2E201 | 39b6d509af8e82b0ceb9e1c430dd964674d7488e | **4.75** | Accepted; current best and automatically selected entry |
| BB-81C2BC51 | 373f70986d2ffe9077d7afc1a8c773097b4f4ede | 4.63 | Accepted; lower than the selected best |
| BB-1B3ACBAA | 88488f29e2b56ea82b33930793a6506c91efc21a | 2.46 | Accepted; selective policy underperformed in coordinated practice |
| BB-391F3E46 | e5f021a2a0364a1db2d162afe0e3a29b9ed8b792 | 2.29 | Accepted; route/reload fixes did not improve practice score |
| BB-C709FC88 | 54c9f5f30f3a16cfd3bf276cfe31f7e3037309a9 | 2.33 | Accepted; energy change remains below the selected best |
| BB-AC10AB33 | 01df3dc61f89352c4d54b8aa93b3922a206d8355 | 2.69 | Accepted; bounded defensive continuation, previous selective objective |
| BB-A29B40E8 | 219fde26f0004c10946bf34613c0c8287690d697 | 4.63 | Accepted; first aggressive candidate, below retained best |
| BB-152A342F | a237d0beb3bbb1ad47c059d233bbf9f868d3408f | 4.60 | Accepted; movement correction did not improve official score |
| BB-0962E9D9 | 005e830f22800cb32b5c9bbca94a99e0e1fae47d | 4.58 | Accepted; first-magazine preference did not improve official score |
| BB-622AA903 | f0609d61c0d199a7311c0338abc912345fc14145 | 4.63 | Accepted; drop-contestation memory did not improve official score |
| BB-C938CB71 | 919f826b217691b18842baace9ea0e2dd7cdd499 | 4.21 | Accepted; nearest-pursuit policy did not improve official score |

The strategy-v2 candidate improved 4.19 to 4.75 (approximately 13.4%).
Fourteen submissions have been accepted. The hourly quota replenishes over time;
check the authenticated panel before any further attempt.

The automatically selected entry is the commit above; this is **not** a claim
of qualifying for the top-32 tournament or winning the track.

Source: authenticated team's submission panel on the
[official track page](https://www.joinbuilders.org/buildathon/tracks/builders).
The team page automatically enters its best accepted score unless another
submission is explicitly selected. No tournament placement is guaranteed.

BB-AC10AB33 scored 2.69. The user subsequently changed the objective to greedy,
aggressive play. The first aggressive implementation scored 4.63; none of the
selective scores measures it. The current design is in PROGRAM_DESIGN.md and
the three current strategy-agent plans. The 6.0 target remains unmet.

## Nearest-enemy pursuit: completed experiment

The user updated the objective to fast nearest-enemy pursuit, maximum available
firepower, optional reloads when no enemy is nearby, and low-health recovery
only in quiet intervals. The user explicitly selected equal treatment of mechs
and NPCs and current weapon reach for the nearby-enemy rule. The pursuit-v1
candidate begins at exact retained best `39b6d50`; its design is in
PROGRAM_DESIGN.md and the three strategy-agent plans.

Frozen runtime SHA256 values are `8ef433138bb7313147c2f0d21e2d20e4009ddff006cae1fad5a9349b8dec90ac`
for bot.py, `4ae8832867d8c3aea2ec3907d65df06d6fbb5517fa6322f9311bfe5315248765`
for combat.py and `a40aa5d643eeb84b70909758562fb253f1498fd7ad5dc4881e330aaa76bbec50`
for tactical.py. The following checks apply to that source:

- **214 tests pass**, including nearest ordering, shared proximity, partial reload,
  quiet recovery, two-slot fire, lightning cone, bounded visibility and pursuit movement.
- Restricted Linux-container checker: **300/300 replies on time**, zero missing,
  late, stale, wrong-tick or invalid replies. Ready in 2,892 ms; p50 10.1 ms,
  p90 23.9 ms, p99 27.3 ms, maximum 31.4 ms. Checker and bot shared one CPU,
  512 MB, network isolation and the documented read-only/uid/pid limits.
  Same-image preflight confirmed 259 map prisms and 774,680 terrain samples.
- Host stress: **580 valid decisions**, none above 50 ms, maximum 31.21 ms.
  A separate dense/opening test had **252 timely decisions**, maximum 24.28 ms;
  all 27 actors remained eligible for nearest selection in the 200 dense cases.
  All 52 opening cases requested pursuit boost. Unchecked visibility remained
  explicitly unknown and could not create a false quiet-healing interval.
- The private integration match ended **16th with zero kills and zero cubes**,
  last observed at 29.1 seconds, still holding only the starting gun. It dealt
  1,137.5 damage and took 1,241.8 damage, with zero zone damage. All 292
  observations received actions; zero policy errors, skips or decisions above
  50 ms; maximum computation 27.74 ms. This poor single-match outcome is
  retained as adverse evidence, not converted into a predicted official score.
- A trace audit found all 292 target choices matched nearest living reported
  actors, with no partial reload or recovery commands while an enemy was near.
  All proximity assessments completed; the captured runtime matched all five
  source hashes. The bot dealt 260 damage to NPC 103 before it disappeared
  and two cubes appeared at 3.9 seconds. It immediately pursued the next mech
  and did not collect those cubes (closest observed distance 35.9 m). At
  18.5 seconds a gun-and-laser mech became nearest at 44.75 m. The bot stayed
  gun-only and continued combat below 55% HP from 25.9 seconds until death,
  consistent with the requested near-enemy rule. There was no oscillatory
  target churn or substantial movement stall. These observations identify a
  resource tradeoff, not a proven counterfactual win or aggregate score cause.

The first unbounded visibility revision exceeded 50 ms in five of 200 dense
cases, with a maximum 99.13 ms. The final revision budgets visibility work
between map rays while preserving all actors and conservative unknown handling.
The budget cannot preempt an individual ray; measured passing samples are not
a universal real-time guarantee. The official pursuit result is **4.21** (BB-C938CB71); the selected best remains **4.75**. The 6.0 target is unmet.

## Additional pursuit diagnostics

Two further frozen-source private matches checked the resource-acquisition and
quiet-healing concern. They ended seventh (zero kills/cubes) and third (three
kills, fourteen cubes, gun plus laser). Both took zero zone damage. There were
2,015 actions, seven skipped online observations, zero policy errors and zero
decisions above 50 ms; maximum computation was 32.70 ms.

Across these actions, the audit found no recovery while near, no near-enemy
partial-reload admissions, no resource override during pursuit and no incomplete
proximity decisions. The seventh-place run regained 1,035 HP in a quiet recovery
interval. In the third-place run, thirteen of fourteen cubes were acquired with
no pursuit target, and one was incidental at a combat transition; quiet looting
also acquired lightning and then laser. Thus resource collection and healing
work in quiet windows. The concern is lost resource opportunities during
continuous pursuit, not universal resource denial. Random private results do
not establish an official score improvement.

## Current candidate: gun-only combat spacing

This isolated follow-up starts at submitted pursuit commit `919f826` (4.21),
with `39b6d50` (4.75) still retained as the official best. It restores the existing
70 m gun preference against mechs when only the gun is held, so a close enemy
does not erase that movement preference. NPC, multiple-weapon and occluded
approach behavior stays at pursuit-v1. Target ordering, combat, reload and
healing contracts are unchanged. See SPACING_PLAN.md for the hypothesis,
conditional replay evidence and validation; no score benefit is established.

Frozen tactical SHA256 is
`cdbf955645840bc3c36d49861410172225d7962d35dcc9b53548526a47278491`.
The only executable runtime difference from pursuit-v1 is the two-line anchor
restoration in tactical.py. The final source passes **224 tests**. Host stress
completed **580 valid decisions**, none above 50 ms, maximum 31.20 ms.

The restricted real-map Linux checker returned **300/300 replies on time**,
with zero missing, late, stale, wrong-tick or invalid replies. Ready took
2,912 ms; p50 10.5 ms, p90 23.7 ms, p99 27.8 ms, maximum 30.6 ms. The checker
and bot shared one CPU and 512 MB under the documented isolation limits.
Same-image preflight confirmed 259 map prisms and 774,680 terrain samples.

The frozen private integration match ended **15th, zero kills and zero cubes**,
last observed at 22.8 seconds. It dealt 877.5 damage and took 1,375.74 observed
damage, including 995.4 laser damage from its final gun-and-laser opponent;
zone damage was zero. There were 224 actions, five skipped online observations,
zero policy errors and zero decisions above 50 ms; maximum computation was
25.43 ms. Twenty clear-mech frames exercised the restored preference below
70 m (minimum observed target distance 64.45 m). A trace audit found no nearest,
reload, healing or pursuit/resource contract violations; all source hashes
matched. One nearby assessment was incomplete and conservatively treated as
nearby. This adverse random result is retained; it does not establish an
official improvement or isolate a causal effect of the spacing change.

## NPC farming range (historical, unsubmitted experiment)

The frozen runtime SHA256 beginning `bde124e` passed 148 tests and the restricted
Linux checker: 300/300 timely replies, p99 33.6 ms, maximum 38.8 ms, ready in
3,337 ms. A preflight confirmed real-map loading. Host stress had one 195.02 ms
recovery decision among 580; the new farming branch is skipped during recovery.
The original spike was not instrumented, so no cause is claimed.

Its private diagnostic ended first with five kills and nine cubes, but no NPC
was ever listed. Thus the new farming range was not exercised. There were
1,802 actions, five skipped online observations and zero policy errors; one
action took 57.42 ms. The result does not establish a farming or official-score
benefit. Separate recorded-prefix timing found the supplemental search often
received no time after existing resource work. A budget revision was applied
but was not revalidated or submitted before the objective changed.

The npc-economy-v1 candidate starts from exact retained best `39b6d50`. It
changes elective NPC farming discovery only. Its plan and recorded resource
comparisons are in NPC_ECONOMY_PLAN.md. The lower-scoring magazine, drop-memory
and earlier movement changes are not included.

## Drop contestation memory (historical experiment)

The exact frozen candidate `f0609d6` / BB-622AA903 scored **4.63**. It fixed the
reproduced admission discontinuity but did not improve the official aggregate.
Its memory change is not included in the current experiment.

The drop-memory-v1 candidate starts from exact retained best `39b6d50`. It
changes only short-lived memory used by the supply-drop contestation check.
Its plan and reproduced admission discontinuities are in DROP_MEMORY_PLAN.md.
Upgrade priority, targeting, firing and movement remain at the 4.75 baseline.

- **137 tests pass**: the 124 baseline tests and 13 new tests. Four paired
  recorded snapshots cover three disappearance-triggered admissions and a
  confirmed-kill control. A second reviewer independently passed the 13 focused
  tests and checked the frozen runtime diff.
- Corrected restricted Linux-container checker: **300/300 replies on time**,
  zero missing, late, stale, wrong-tick or invalid replies; p50 11.6 ms,
  p90 26.8 ms, p99 32.8 ms, maximum 34.6 ms, ready in 2,987 ms. Checker and bot
  shared one CPU and 512 MB with the documented sandbox limits. A separate
  identical-image preflight confirmed 259 map prisms and 774,680 terrain samples.
- Real-map host stress: **580 valid decisions**, maximum 32.28 ms, none above
  50 ms. Tests establish local correctness and timing, not a competitive score.
- The frozen private diagnostic finished **4th, three kills, seven cubes**,
  last observed at 113.9 seconds. It dealt 5,839 damage, took 2,131 damage and
  took zero zone damage. All 1,140 observations received actions, with no
  policy errors or decisions over 50 ms; maximum computation was 33.37 ms.
  This random private match is an integration check, not a score comparison
  or evidence that the memory change caused its kills or placement.
- A frozen resource-only comparison across 526 eligible private observations
  found three changed choices, at 105.1-105.3 seconds: the retained opponent
  record was 1.7-1.9 seconds old, and the new rule declined the drop that the
  baseline admitted. Recorded actions remained in recovery. At exactly 2.0
  seconds the record expired and the drop became eligible. The cache held at
  most three records. All three kills occurred before this gate was exercised;
  no supply capture occurred, so no causal competitive benefit is established.

## First magazine upgrade (historical experiment)

The exact frozen candidate `005e830` / BB-0962E9D9 scored **4.58**. The
conditional throughput benefit did not produce a higher official aggregate
score; its priority change is not retained in the current experiment.

The offense-v1 candidate starts from the exact retained 4.75 source `39b6d50`.
It changes first-magazine upgrade priority only; the lower-scoring aggressive
selector, fine-route recovery and zone-projection experiments below are not
included in its runtime. Their commits and evidence remain preserved.

The movement candidate BB-152A342F scored **4.60**, compared with 4.63 for its
aggressive predecessor and 4.75 for the retained best. The demonstrated local
movement repairs did not establish improved aggregate practice performance.
That experiment is documented in FIRST_MAGAZINE_PLAN.md.

- **134 tests pass**, including ten focused first-magazine selection checks.
- The unmodified checker ran inside the restricted Linux container with the
  real arena: **300/300 replies on time**, no missing, late, stale, wrong-tick or
  invalid replies; p50 11.4 ms, p90 26.8 ms, p99 32.8 ms, maximum 33.8 ms, ready
  in 2,989 ms. Checker and bot shared one CPU and 512 MB. An identical-image
  preflight confirmed map loading: 259 prisms and 774,680 terrain samples.
- Real-map host stress: **580 valid decisions**, maximum 31.28 ms, none above
  50 ms. These measurements establish local conformance, not gameplay strength.
- The frozen private diagnostic finished **6th, two kills, seven cubes** at
  87.4 seconds: 4,014 damage dealt, 2,299 taken, zero zone damage and zero policy
  errors. All 868 actions computed below 50 ms, maximum 32.87 ms. Seven online
  observations were skipped; local computation excludes network latency.
- The new preference selected the first magazine over servos at 76.0 seconds;
  it applied at 76.4 seconds, changing capacity from 12 to 20 and reload from
  2.4 to 1.92 seconds. Both kills occurred before that upgrade. Only seven rounds
  were spent afterward, with a partial reload while 15 remained, so the extra
  capacity was not exercised. This validates selection and application, not a
  causal damage, kill or official-score improvement.

## Aggressive-v2 movement correction (historical experiment)

This candidate preserves the submitted aggressive-v1 firing and economy policy.
It adds bounded local routing for confirmed small disconnected components and
validates future-zone goal projections, including failed-goal exclusions. The
diagnosis is in OPTIMIZATION_REPORT.md; implementation details and limitations
are in LOCAL_ROUTE_PLAN.md and ZONE_GOAL_PLAN.md.

- **467 tests pass**, including 24 local-route, four root-integration and 17
  zone-projection checks.
- Corrected Linux-container checker: 300/300 replies on time, zero invalid
  lines, wrong ticks or discarded older replies; p99 33.9 ms, maximum 34.6 ms,
  ready in 3,229 ms. Both checker and bot shared one CPU, 512 MB, no swap/network,
  uid 65534, read-only files and a 64 MB tmpfs. A separate identical-image
  preflight confirmed `map.available=True`, 259 prisms and 774,680 terrain samples.
- Three additional recorded-scenario streams passed the same unmodified checker
  inside that restricted image: **660/660 timely replies**, maximum 33.3 ms,
  zero missed/late/stale/wrong-tick/invalid replies. Host replay of the same
  observations naturally activated local recovery on all 660 decisions without
  forcing internal state. The container exposed normal actions, not activation
  telemetry; these streams are timing/conformance tests, not simulated matches.
- Real-map host stress: 580 schema-valid decisions, maximum 40.43 ms, none above
  50 ms. This includes dense fights, recovery, urgent rotation and resources.
- An additional 390 full-policy decisions with local recovery active all
  produced finite actions below 50 ms; maximum 40.04 ms. Positions were held
  fixed to exercise discovery/following cost, so this is not a match simulation.
- Production routing and the unchanged tactical controller completed 1,200
  checked 0.1-second motion sweeps without a blocked applied segment. Each
  40-second mechanical run includes route discovery. The deeper pocket exited
  in two stages after approximately 27.5 seconds under the harness's separate
  six-millisecond navigation window. Actual policy shares its existing overall
  deadline and can give navigation more remaining time.
- Zone-projection helper: 150 exact-state calls returned no invalid endpoints
  or holds; maximum 1.12 ms with a 1.5 ms endpoint budget. Expensive optional
  exposure ranking is skipped when insufficient time remains.

One routing call in the mechanical run took 17.28 ms despite a six-millisecond
requested component budget. Its cause was not instrumented. A subsequent 534-call
instrumented discovery check peaked at 5.12 ms and did not reproduce it. The
existing geometry calls are non-preemptible; the full-policy/container checks
above are the relevant local deadline evidence, not a hard timing guarantee.
The mechanical inputs freeze enemies and omit damage/network effects. They do
not establish survival, kills, or an official score improvement.

The frozen private diagnostic finished **2nd with two kills and three cubes**
at 154.4 seconds. It dealt 4,280 damage, took 3,486 damage and took zero zone
damage. All 1,542 actions computed below 50 ms (maximum 32.98 ms), with zero
policy errors; two observations were skipped by the online interface. It
travelled 1,640 m. No sustained navigation stall or blocked rotate/recover/
position goal was found. Local recovery never activated in this particular
match: it validates ordinary delegation, not live use of the fine route search.
The rank and kills are an uncontrolled FFA diagnostic, not the official score.

## Aggressive-v1 candidate verification

This candidate follows the updated user objective in AGGRESSIVE_PLAN.md. It
proactively attacks current usable enemies, prioritizes validated short kills,
restores approach, permits hostile collateral, and retains zone, terrain,
energy, reload and recovery mechanics. The separately reproduced short recovery
escape is included. Previous selective results do not measure this candidate.

The initial pre-fix checkpoint had the following results:

- All 373 regression tests passed, including 21 proactive-selection tests,
  40 root orchestration tests and 19 recovery-escape tests.
- Restricted Docker checker: 300/300 timely replies, zero invalid lines, wrong
  ticks or older queued responses; p99 13.8 ms, maximum 17.8 ms, ready in 1,530 ms.
- Full-policy real-map host stress: 580 schema-valid decisions, maximum 32.35 ms,
  zero above 50 ms. The dense weak-target cases selected 23 proactive short kills.
- Actual-LOS selector benchmark: 288 cases, mean 3.40 ms, p99 7.19 ms, maximum
  8.46 ms. A relaxed reference found zero usable targets missed solely by budget
  in that run. The requested 6 ms selector cutoff is cooperative: an in-progress
  geometry query can overrun it. Full-policy checks above establish the relevant
  local action timing, not a guarantee on every host.

The first prepublication aggressive diagnostic finished 3rd with zero kills and
three cubes at 118 seconds. It dealt 3,156 damage, took 2,173, and took 285 zone
damage. All 1,181 actions computed below 50 ms (maximum 33.37 ms), with zero
policy errors. Proactive fire began at 0.3 seconds before an attributed incoming
attack from that target. This uncontrolled private result is not an official score.

The trace exposed two defects requiring correction before publication: repeated
neutral trajectory fallback went undetected while navigation intended movement,
and the first weapon slot's reload delay biased the otherwise usable target's
readiness score. The source/trace snapshot remains local for exact reproduction;
the corrected candidate was checked again as follows.

The corrected source passes **422 tests**, including 30 aggressive-selection,
44 orchestration, 19 tactical-recovery and 17 navigation-intent cases. It fixes
readiness-order bias, reuses exact geometry only within the current decision,
records the actual finishing weapon, and permits a verified quick laser charge
during grounded non-urgent recovery. Tactical recovery now gives a fully checked
half-throttle candidate early priority after neutral geometry fallback. A separate
intent monitor reports stalls without forcing unsafe motion.

- Restricted Docker checker: 300/300 replies on time, zero invalid lines or
  wrong ticks; p99 13.2 ms, maximum 13.6 ms, ready in 1,425 ms. Two replies to
  older queued observations were discarded; the checker passed.
- Full-policy real-map host stress: 580 schema-valid decisions, maximum 31.54 ms,
  none above 50 ms. The dense weak-target cases selected 22 proactive short kills.
- Updated actual-LOS selector benchmark: 288 cases, mean 3.31 ms, p99 7.38 ms,
  maximum 7.67 ms; zero budget-only missed usable targets against the relaxed
  reference. The cooperative selector cutoff still does not guarantee a hard
  per-component duration.
- The captured 51.3-second opportunity now reports a laser finishing ETA of
  0.85 seconds. This is a decision/geometry check, not a counterfactual kill.

The half-throttle change fixes initial movement at the captured stuck positions,
but repeated mechanical rollouts still stop at a short route endpoint. Offline
fine-resolution connectivity finds a ground exit that the coarse route search
misses. Global escape remains an open limitation; no unverified route or collision
relaxation is included in this candidate.

The corrected frozen private diagnostic finished **4th with two kills and six
cubes** at 117.1 seconds. It dealt 6,299 damage, took 2,393 damage and took zero
zone damage. All 1,166 issued actions computed below 50 ms (maximum 32.24 ms),
with zero policy errors; six online observations were skipped. It travelled
1,292 m. The recorded gun finishing episode at 38.0–39.8 seconds stayed on the
same wounded target and was followed by an observed hit and kill at 39.9 seconds.
This is an uncontrolled private match with different opponents and world state,
not an official score or a controlled comparison with the earlier diagnostic.

The official aggressive-v1 result was **4.63**, below the retained best of 4.75
and the 6.0 target. It improves on the prior selective candidate's 2.69, but the
combined changes do not isolate which mechanism caused that difference. The
next candidate isolates bounded local route recovery; submitted source 219fde2
is preserved.

## Selective-v4 permission candidate

The [follow-up plan](SELECTIVE_V4_PLAN.md) separates fresh fight evidence from a
fixed finish deadline and permits bounded continuation against confirmed current
attackers. Quiet actors remain protected. The reviewed implementation adds
physical first-body reachability checks and one consistent authorization set for
predicted damage and final weapon guards.

- 326 tests pass, including 44 new policy cases and six root-controller cases.
- Restricted Docker checker: 300/300 timely replies, zero invalid lines or wrong
  ticks, p99 18.0 ms, maximum 28.8 ms, ready in 1,484 ms. One older queued
  observation was discarded; the checker passed.
- Host stress: 580 schema-valid decisions, maximum 38.00 ms, none over 50 ms.
  All 40 added continued-attacker cases selected the intended bounded defensive
  reason. The generic dense beam-fight fixture crosses our body and therefore
  exercises defense, not elective FINISH; dedicated tests cover finish behavior.

These are local checks, not an official score or proof of improved placement.

The complete bot, real arena geometry, and unmodified FinishSafety also accepted
the recorded opportunity: entry at 51.7 seconds on target 8, continuation at
52.0, with the original fixed deadline 53.7. Both observations retained their
real incoming gun projectile. All 20 repeated three-frame trials agreed; maximum
decision time was 31.89 ms. A 521-observation prefix replay reached the same
decisions and stayed below 50 ms (maximum 32.56 ms). This verifies decisions on
recorded observations, not a counterfactual kill or survival outcome.

The frozen private diagnostic finished 1st with three kills and 43 cubes at
170.5 seconds. It dealt 3,826 damage, took 2,598, and took no zone damage.
All 1,695 actions computed below 50 ms (maximum 32.15 ms), with zero policy
errors. Eleven observations were skipped by the online interface. All 171
mech-trigger commands had explicit permission; the first occurred at 79.4
seconds against a recently attributed attacker. No elective FINISH was selected.
These are uncontrolled FFA results; house opponents in official practice do not
eliminate each other, so the placement is not an official score estimate.

## Selective-v3 energy candidate

The separate [energy experiment](BOOST_PLAN.md) adds observed-energy boost
hysteresis and validated emergency exceptions. It also corrects recognition of
documented NPC projectiles in finish safety. It keeps the prior route/reload
corrections and the confirmed engagement policy.

- 276 behavioral, weapon, geometry and orchestration tests pass.
- Restricted Docker checker: 300/300 timely replies, zero invalid lines or wrong
  ticks, p99 13.4 ms, maximum 21.1 ms, ready in 1,400 ms. Two older queued
  observations were discarded; the checker passed.
- Host stress: 540 schema-valid decisions, all below 50 ms. Maximum was 47.44 ms
  in one dense recovery case; other scenario maxima were below 32 ms. The Docker
  build and private diagnostic ran concurrently with this host stress check.
- Actual-selector energy and map measurements are described in BOOST_PLAN.md.

These checks establish local behavior and conformance, not an official score.

The frozen private diagnostic finished 3rd with zero kills and four cubes at
122.7 seconds. It dealt 1,719 damage, took 1,960, and took no zone damage.
All 1,225 actions computed below 50 ms (maximum 33.07 ms), with zero policy
errors. All 52 mech-trigger commands had explicit permission; the first followed
an attributed attack at 107.2 seconds. No elective FINISH was selected.
This uncontrolled private match does not establish practice strength.

## Selective-finish candidate verification

The current candidate follows [the three-agent plan](AGENT_STRATEGY_PLAN.md):
safe crate/NPC farming, attributed self-defense, and short safe finishes against
the lowest-HP eligible participant in an observed enemy fight. It has no timed
permission to attack quiet mechs. Weapon-level checks also reject predicted
interception and collateral hits on other observed mechs.

- 251 tests pass, including 57 combat, 32 engagement, 28 orchestration, and
  16 finish-safety tests. Existing navigation, resource, and survival regressions
  remain covered.
- Restricted Docker check: 300/300 timely observations, zero invalid lines or
  wrong ticks, p99 13.5 ms, maximum 15.8 ms, ready in 1,408 ms. Two responses to
  older queued observations were discarded; the checker passed.
- Host stress: 540 schema-valid decisions spanning recorded input, dense
  attributed attacks, recovery, urgent rotation, observed fights, loot, and
  exploration. Maximum measured computation was 35.94 ms; none exceeded 50 ms.
- Finish-safety geometry: 900 real-map cases across 0, 8, and 23 cubes,
  p99 0.794 ms and maximum 1.453 ms. This checks bounded computation and physical
  exit feasibility, not future enemy behavior.
- Collateral checks: 3,000 calls per weapon with 15 protected mechs; each
  weapon's p99 was below 0.25 ms and every maximum below 0.58 ms.

These are local measurements. Recorded input, unit fixtures, and private rooms
do not establish an official 48-match score. A held laser charge cannot be
canceled; the controller avoids redirecting its unavoidable release at a newly
selected quiet enemy. Shot/escape predictions use observed motion, not a
guarantee that actors will keep that motion.

The frozen candidate's first private diagnostic finished **1st, 2 kills, 5 cubes**
at 146.8 seconds. It dealt 2,919 damage, took 3,196, took zero zone damage, and
had zero policy errors. All 1,462 issued actions computed within 50 ms (maximum
31.24 ms). Seven online observations were skipped; network input timing differs
from the official lockstep runtime.

The trace contains 116 mech-trigger commands, all with explicit permission.
The first occurred at 46.5 seconds immediately after a `damaged.by=2` event;
the same quiet opponent had been observed without firing at 44–46 seconds.
There were no elective FINISH selections: observed early opponents exceeded the
short finish budget, and later safety/recovery conditions vetoed entry. Thus this
run supports the farming/defense/recovery behavior, not a measured benefit from
third-party finishing. It is one uncontrolled private match, not the official score.

A second unchanged private run finished **2nd, 0 kills, 4 cubes**, with no policy
errors or decisions over 50 ms (maximum 33.11 ms). Its first mech trigger followed
an attributed attack at 127.2 seconds. It took 852 zone damage during the late
rotation, which warrants a movement investigation. Neither private run selected
FINISH. The official result was **2.46**: the private outcomes did not establish
competitive practice strength. The 4.75 entry remains selected, and the 6.0
objective has not been reached.

## Selective follow-up: urgent routes and reload readiness

This candidate isolates two measured faults while retaining the original
three-second defensive attribution and all opening/finish permission rules.

The late-rotation replay showed 260.3 m traveled for only 15.5 m net displacement,
mostly with ready routes and clear local geometry. Urgent-only route weighting
reduced backward projected progress from 63 to 4 of 201 captured observations;
mean 0.6-second routed progress rose from 1.66 to 7.40 m. Mean immediate
projectile cost rose from 3.14 to 4.45 as a documented tradeoff. Collision,
projectile, beam, and actual-zone costs remain active; nonurgent behavior is
unchanged. This is a decision replay, not a simulated match outcome.

The reload change suppresses optional partial-magazine reloads while a visible
opponent is within threatening reach. Empty guns still reload. Three partial
reloads in the second private trace overlapped 2.7 observed seconds of renewed
defensive permission. A frozen-observation check found 1.0 second with valid gun
triggers if the available rounds had been retained; it does not establish hits.

- 262 tests pass, including four captured-rotation regressions and seven reload
  regressions across the weapon and orchestration layers.
- Restricted Docker: 300/300 on time, no dropped older replies, wrong ticks or
  invalid lines; p99 15.9 ms, maximum 17.6 ms, ready in 1,473 ms.
- Host stress: 540 valid decisions, maximum 42.71 ms, none over 50 ms. One dense
  combat case exceeded 40 ms; the remaining scenario maxima were below 33 ms.

The unchanged follow-up candidate finished **2nd, 0 kills, 3 cubes** in a private
diagnostic at 165.4 seconds. It took zero zone damage, had zero policy errors,
and all 1,653 issued actions computed within 50 ms (maximum 32.59 ms). The trace
logged 131 authorized mech-trigger commands and no permission violations. Its
first mech trigger followed attributed damage at 89.2 seconds. No FINISH was
selected. This was a different random match, so the absence of zone damage does
not establish a controlled before/after survival gain.

The official follow-up result was **2.29**, below both the 2.46 selective baseline
and retained 4.75 best. Local correctness evidence did not establish improved
coordinated-practice strength. The next energy experiment remains separately
specified in [BOOST_PLAN.md](BOOST_PLAN.md).

## Earlier strategy-v2 and v3 checks

The accepted 4.75 commit passed 124 tests and the restricted Docker checker:
300/300 timely replies, no invalid or wrong-tick actions, p99 12.7 ms,
maximum 13.3 ms, and ready in 1,189 ms. Host stress: 500 decisions,
all schema-valid, maximum 31.18 ms. These timings are local measurements.

The follow-up candidate fixes skipped partial-route endpoints, retires failed
cover goals, uses the documented lightning cone, and checks the actual firing
ray while the torso slews. A private diagnostic of the route changes won with
three kills and 24 cubes; the final firing-ray changes were added afterward and
are covered by focused tests, not that closed-loop match. Private placements
remain diagnostically useful but are not official scores.

The final v3 candidate passes 135 tests and the restricted Docker checker:
300/300 on-time replies, no invalid or wrong-tick actions, p99 14.3 ms,
maximum 14.5 ms, ready in 1,147 ms. One answer to an older queued observation
was discarded by the checker; the run passed. Host stress before a computation-
saving ray-check optimization covered 500 decisions, all valid, maximum 34.83 ms.

## 4.19 baseline verification

- 73 unit/behavioral tests passed: 20 combat, 16 geometry, 37 strategic decisions.
- Official Docker conformance check: 300 observations, 300 on time, zero bad
  lines, zero wrong ticks. Final candidate measured p50 4.4 ms, p99 8.6 ms, maximum 10.7 ms;
  ready in 1,225 ms. Test used 1 CPU, 512 MB, no swap, 128 process limit,
  no network, read-only filesystem, 64 MB `/tmp`, uid 65534, read-only arena.
- Updated real-map stress run: 500 decisions, all schema-valid, maximum local
  computation 24.28 ms. This host-only measurement is not a sandbox guarantee.
- Geometry diagnostics: ten long ground routes reached within 3 m, zero blocked
  steps in the kinematic test. This is not an authoritative physics simulation.

Timing depends on the host and workload. The official checker is recorded input,
so its PASS establishes protocol compliance, not gameplay quality.

## Private-room diagnostics

Four early revisions finished 11th, 10th (one kill), 8th, and 14th in separate normal
private-room matches. These matches use different random worlds and are not a
controlled score comparison. Input was observed to reach the public game roughly
0.4 seconds later, unlike the scored lockstep container interface.

A subsequent recovery/cover candidate finished 10th, acquired a laser, dealt
945 damage, and demonstrated actual recovery from 937.5 to 1,311 HP behind cover.
All 617 observations received actions, with zero policy errors and maximum local
computation 24.01 ms. This run exposed nearby attacking NPCs being ignored; the
final candidate fixes that priority and has four corresponding regression tests.

The traces found and motivated concrete fixes:

- Keep distance from unfinished crates so the muzzle can aim down at them.
- Remove remembered nearby loot when clear proximity vision proves it gone.
- Keep defensive torso orientation during retreat to reduce rear hits.
- Explore when no resource is currently known.
- Permit short safe loot detours despite a distant combat target.
- Match pickup goals to the weapon the bot would actually equip.
- Aim at reachable upper/lower target body points when appropriate.
- Cache directional terrain traversal correctly.
- Continue defensive fire during active incoming damage, then stop for healing.
- Precompute diverse cover points so generation leaves time for threat evaluation.
- Match a pursuer's radial speed; reserve boost for increasing distance safely.
- Retreat in open fields when no hard cover is available.
- Prioritize actual nearby NPC attackers when no mech presents an immediate threat.

Development observations and raw traces remain local; the public repository
contains no school email, authentication material, or private room credentials.
