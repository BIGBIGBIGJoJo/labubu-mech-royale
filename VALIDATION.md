# Validation and experiment log

Verified on November 21, 2026. Official score means mean `16 - place` over
48 practice matches. Private-room placement is a different diagnostic.

## Official submissions

| Submission | Commit | Practice score | Result |
|---|---|---:|---|
| BB-062E97A7 | b49715d45447840d66a3e5d24624fdbf3f43389e | 2.77 | Accepted; above the published starter baseline 1.15 |

Source: authenticated team's submission panel on the
[official track page](https://www.joinbuilders.org/buildathon/tracks/builders).
The team page automatically enters its best accepted score unless another
submission is explicitly selected. No tournament placement is guaranteed.

## Local verification

- 53 unit/behavioral tests passed: combat, geometry, and strategic decisions.
- Official Docker conformance check: 300 observations, 300 on time, zero bad
  lines, zero wrong ticks. Latest measured p50 4.4 ms, p99 8.3 ms, maximum 9.1 ms;
  ready in 1,267 ms. Test used 1 CPU, 512 MB, no swap, 128 process limit,
  no network, read-only filesystem, 64 MB `/tmp`, uid 65534, read-only arena.
- Earlier real-map stress run: 550 decisions, all schema-valid, maximum local
  computation 27.73 ms. This host-only measurement is not a sandbox guarantee.
- Geometry diagnostics: ten long ground routes reached within 3 m, zero blocked
  steps in the kinematic test. This is not an authoritative physics simulation.

Timing depends on the host and workload. The official checker is recorded input,
so its PASS establishes protocol compliance, not gameplay quality.

## Private-room diagnostics

Three early revisions finished 11th, 10th (one kill), and 8th in separate normal
private-room matches. These matches use different random worlds and are not a
controlled score comparison. Input was observed to reach the public game roughly
0.4 seconds later, unlike the scored lockstep container interface.

The traces found and motivated concrete fixes:

- Keep distance from unfinished crates so the muzzle can aim down at them.
- Remove remembered nearby loot when clear proximity vision proves it gone.
- Keep defensive torso orientation during retreat to reduce rear hits.
- Explore when no resource is currently known.
- Permit short safe loot detours despite a distant combat target.
- Match pickup goals to the weapon the bot would actually equip.
- Aim at reachable upper/lower target body points when appropriate.
- Cache directional terrain traversal correctly.

Development observations and raw traces remain local; the public repository
contains no school email, authentication material, or private room credentials.
