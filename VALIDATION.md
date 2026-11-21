# Validation and experiment log

Verified on November 21, 2026. Official score means mean `16 - place` over
48 practice matches. Private-room placement is a different diagnostic.

## Official submissions

| Submission | Commit | Practice score | Result |
|---|---|---:|---|
| BB-062E97A7 | b49715d45447840d66a3e5d24624fdbf3f43389e | 2.77 | Accepted; above the published starter baseline 1.15 |
| BB-F2B295B5 | b99310a760505c250b7afaf03e07269a4e47416d | 3.10 | Accepted; improved resource collection and targeting |
| BB-80D20692 | 7c38fba27c3feb6f52c2b74b45423f63beb33ff5 | 4.19 | Accepted; previous best |
| BB-12F2E201 | 39b6d509af8e82b0ceb9e1c430dd964674d7488e | **4.75** | Accepted; current best and automatically selected entry |
| BB-81C2BC51 | 373f70986d2ffe9077d7afc1a8c773097b4f4ede | 4.63 | Accepted; lower than the selected best |

The strategy-v2 candidate improved 4.19 to 4.75 (approximately 13.4%).
Five submissions have been accepted. The hourly quota replenishes over time;
check the authenticated panel before any further attempt.

The automatically selected entry is the commit above; this is **not** a claim
of qualifying for the top-32 tournament or winning the track.

Source: authenticated team's submission panel on the
[official track page](https://www.joinbuilders.org/buildathon/tracks/builders).
The team page automatically enters its best accepted score unless another
submission is explicitly selected. No tournament placement is guaranteed.

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
