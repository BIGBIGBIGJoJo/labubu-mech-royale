# Combined route and tactical scheduling candidate

This candidate combines the exact geometry acceleration from `290f48e`, the
existing-caller tactical budget from `25fc4cd`, and ground-goal screening with
the height scope correction from `bf66cc0`. Combat logic, resource rankings,
upgrade choices, tactical costs and the global 32 ms decision target remain
those of the respective reviewed components. Resource-progress, incoming-ray
recovery, evasion, spacing and hidden-attacker defense experiments are not added.

The native terrain kernel preserves the original terrain-ray formulas. The
navigation asset preserves the original directed cell and edge predicates.
Ground reachability metadata was regenerated against this combined navigation
asset and corrected helper source. Its graph payload is unchanged; fingerprints
bind the actual combined inputs. All builders run offline, not inside a match.

## Additional integration correction

A conditional integration replay exposed a held-goal transition problem. A goal
selected while the mech was above the helper's ground-height scope could remain
active after returning down. At C1 40.3–41.1 s, nine selected goals were then
classifiable as NO, but ordinary goal expiry had not triggered a new selection.

The controller now marks a held ground objective provisional after leaving the
height scope. Before reusing a safe objective when the scope applies again, it
queries that objective within the existing selection deadline. NO triggers new
selection; YES clears the pending flag; UNKNOWN retains the objective and the
pending check for a later observation. A replacement after NO also stays pending
until explicitly verified. Normal expiry and mode changes still select first.
Resource and engagement branches do not enter this revalidation path. Missing
graph metadata preserves the original behavior.

An independent review caught the need to retain the flag after an unverified
replacement. Eight transition regressions now cover that case, returning to
ground, valid objectives, exhausted/unknown queries, expiry, resources and absent
metadata. This does not add general 3D navigation or certify aerial trajectories.

## Restricted Linux validation

Image: `labubu-score7:integrated-routing`, manifest
`sha256:885072651214184873d6374d38ba766b7c9b9f6a9a89d335238e99bb9c2b12c0`.

- **174 tests pass** inside Linux, with the native library required.
- **Official checker: 300/300 timely**, no bad lines, wrong ticks, stale queued
  answers, or late responses. Ready 3,140 ms; response p50 10.1 ms, p90 19.1 ms,
  p99 29.0 ms, maximum 35.3 ms.
- Checker and child bot both execute inside Linux with the actual `/arena`,
  one CPU, 512 MB, no network, read-only root, uid 65534, 128-process limit and
  a 64 MB temporary filesystem. The wrapper verifies 259 prisms, 774,680 terrain
  samples and all eight loaded Python source files against the reviewed tree.
- Replay additionally asserts the native kernel and both binary caches loaded,
  and byte-matches both assets. Its writable audit output mount is outside the
  production bot and differs from the checker sandbox.

## Conditional C1 replay

All 1,045 recorded observations are processed in order. The trace cannot react
to changed commands; these results are neither simulated games nor score gains.
Timing-sensitive choices and measurement overhead remain.

| Metric | Entire trace | 38.6–54.1 s interval |
|---|---:|---:|
| Completed-route / route-required frames | 605 / 663 | 104 / 107 |
| Tactical fallback frames | 7 | 1 |
| Search expansions | 17,582 | 835 |
| Mean navigation ms | 2.04 | 3.14 |
| Action p99 / max ms | 31.44 / 32.25 | 31.46 / 31.95 |
| Actions over 50 ms | 0 | 0 |

Posthoc classification of the interval's 156 selected goals gives **144 YES,
12 UNKNOWN, zero NO**; all lie inside the existing predicted circle. UNKNOWN
corresponds to the recorded airborne interval. The earlier nine-NO held-goal
window now selects a ground-route witness. These are guarantees of the tested
representation on these states, not universal physical reachability claims.
Different variants choose different goals, changing the route-required
denominator. Single replay percentages are not controlled statistical estimates.

## Separate cube-stall replay

An independent full 681-observation prefix used the frozen reachable private
trace, with this exact image and all runtime assertions. In its 59–62.3 s
collection stall, fallback frames fell from 33 in that comparison's fb3 control
to one, and completed geometry checks rose from one to 86. At 59.0 and 60.3 s,
the integrated chooser had 13.6/14.3 ms available for its moving third candidate;
the control had only 1.2/1.8 ms and timed out. Zero outputs fell from 33 to nine.

Changed movement commands interact with the fixed recorded positions: the
existing stuck detector subsequently blacklists the cube and later goals change.
Several later zero outputs are intentional recovery holds. Therefore this replay
supports relief of geometry starvation, not a successful real pickup, earlier
collection, prevented damage or higher placement. No new collection-stall policy
is introduced on this evidence. All 681 actions are below 50 ms; p50/p99/max
are 12.01/31.17/39.60 ms.

## Provenance and scope

Normalized production `bot.py` SHA256:
`6c1bb4d6ffd0c1c219e9f5d70c4045554e970170f89ac5749cc7b01bb7517fa6`.
Navigation asset SHA256:
`06e12324b3b4c9b315acd141ba3b8061a6a19bee2b1e1dea88539a881a0f4183`.
Reachability asset SHA256:
`d820f75d87e05394f3c0cdbaf9dcc1f1497adef65b609449b8837a774b0b467b`.

Local audit artifacts include `integrated-routing-reviewed-linux-tests.log`,
`integrated-routing-reviewed-checker.log`, `integrated-routing-reviewed-c1.json`,
`integrated-routing-reviewed-c1-witnesses.json` and the asserted replay driver
`integrated_route_replay.py`. Earlier `final-c1` files precede the provisional-goal
correction and are not validation of this final version. Component validation
documents describe their isolated revisions, not additional combined score runs.

No official score or live match result is claimed for this combined revision.
