# Historical, unsubmitted NPC experiment

This experiment was paused when the user changed the strategy to equal-class
nearest-enemy pursuit. Runtime bde124e passed 148 tests and the real-map Docker
checker, but the optional search was starved of time in recorded opening
replays. Its private win had no observed NPCs, so did not exercise the change.
The subsequent budget revision was not revalidated or submitted. None of this
extra resource-only discovery code is included in the pursuit candidate.

# NPC farming range experiment

This plan precedes the implementation. The candidate starts from the retained official best, `39b6d509af8e82b0ceb9e1c430dd964674d7488e` (4.75). It changes only elective NPC farming discovery from 55 m to a continuous 140 m. It does not include the first-magazine, drop-memory, later combat, or navigation experiments.

## Recorded motivation

A work-only audit of 20 completed private matches examined 22,108 policy observations. Of 1,711 listed NPC observations at 60–140 m, 969 passed the healthy/non-recovering/non-urgent/gun, current mech exposure, NPC gun range/line-of-fire, ground endpoint and full-body direct collection checks. Existing resource scoring preferred 248 of these over the current resource; 226 also had no recent weapon hit or another listed NPC within 45 m of the target. These are repeated observations, not independent games or proof of safety.

Those 226 observations are an illustrative subset, not additional runtime gates. The experiment retains the baseline farming gates; wounded or multiple nearby NPCs remain possible. The audit checked all listed mechs for current map line-of-fire within 140 m, while runtime retains the existing nearest-16 threat-record gate. Neither absence from that subset nor absence from an observation proves that an enemy is absent.

One opening had a full-health, zero-cube bot and a 350 HP NPC for 52 successive observations from 0.0–5.1 s. Distance fell from 104.5 to 63.3 m. At the first observation, the unchanged NPC score was 21.72 and no other resource had positive utility. Another recorded opening had 50 successive observations from 3.3–8.2 s: a healthy zero-cube bot, an NPC at 138.9–112.8 m, and no positive competing resource. Its initial score was only 3.81. These current observations had a clear map ray and direct body-sized collection segment. The latter match used the baseline policy plus the separate drop-memory experiment, which scored 4.63 officially and is not part of this candidate.

The official NPC drops two cubes, but observed pairs sometimes separated by more than the existing 3.5 m cube-cluster radius. At zero cubes, the current scorer values a clustered pair at 89, or an isolated first cube at 57; it subtracts 0.52 per metre. Thus an isolated first cube beyond approximately 109.6 m can have nonpositive utility even without exposure. A far kill can consequently be abandoned. At the 104.5 m opening, even one isolated first cube has positive current-position utility before other resources appear; at 138.9 m it does not. Approach toward the existing 30 m NPC standoff can improve collection economics, but the recorded observations do not establish a counterfactual kill, approach, or collection. The experiment retains the existing 87 NPC benefit and HP/160 dwell proxy so that discovery range is the isolated lever. Repricing farming, predicting future drops, and committing to collection are deferred.

The official practice score rewards placement, not damage or kills directly. More elective farming can expose the bot or delay other work. Private observation counts and geometry checks do not predict an official score increase.

## Implementation boundary

- Keep global `threats`, defensive NPC targeting, combat, upgrades, recovery, and movement unchanged. Supplemental NPC records exist only inside `resource_goal`.
- Keep the original at-most-55 m farming loop and its order unchanged. Reuse its current threat records for 55–60 m; discover additional currently listed NPCs beyond 60 m, up to 140 m. The small 55–60 m extension prevents a gap as the bot approaches.
- Retain healthy HP at least 80%, below cube stat cap, non-recovering, no current threat-record mech with map line-of-fire within 140 m, blacklist, exposure, future-zone completion, resource competition, and caller urgent-zone gates.
- New farms beyond 55 m also require a held gun, its observed range, a grounded bot, an available map, current center/top line-of-fire, a body-sized clear ground endpoint, and a direct `move_clear` collection segment. The ground check models supported travel and allows drops; it is not a full future trajectory or future enemy-safety guarantee. Listing an NPC plus a clear map ray does not prove fresh visual contact.
- Run supplemental work after existing resource/drop evaluation, preserving its budget priority. Examine at most the official 12 NPCs, nearest first; reuse current threat line-of-fire where available. Test at most two new collection sweeps, require 2.5 ms remaining before optional geometry, and respect the existing resource deadline. A query already in flight can finish after the cooperative deadline. Skip any candidate whose optimistic unchanged score cannot beat the validated incumbent.
- Preserve existing `add` scoring and exposure for admitted candidates. Do not cache NPCs, chase disappeared actors, alter baseline near-farm admission, or add an unobserved map mode.

## Validation before publication

Focused tests cover opening admission, actual `Bot.act` target/navigation integration, continuous 60→59.9→55 m admission, unchanged near behavior, stronger competing resources, actual gun range, blocked rays/endpoints/collection segments, full grown-body dimensions, recovery/HP/cap/mech/zone gates, unavailable map/airborne state, blacklist, bounded scans, and expired/tight deadlines. The original full suite must pass.

Work-only validation will replay recorded opening states with the real map and time a dense 12-NPC clear-path case through the full policy. Root will run the restricted container, stress stream, and a private diagnostic before considering an official submission. A private match is diagnostic evidence, not an official result or a controlled score comparison.

## Implementation status

The isolated implementation adds 44 lines inside `resource_goal`, after the existing drop loop. The original 124 tests and 24 new focused tests pass (148 total). Production source is frozen for independent geometry/timing review and container/private validation; those later checks and any official outcome belong in `VALIDATION.md`. No recorded private payload was added to the test suite; its controlled observations use the official sample schema.

## Necessary budget correction, planned before the revision

The first frozen source (`bde124e`) did not select a far NPC in 156 full-policy calls over the recorded 0.0–5.1 s opening prefix: the existing resource phase had already spent the 4 ms allowance before the optional tail. A fresh dense 12-NPC case exercised the branch, so isolated admission tests did not reveal this prefix-dependent starvation. Its private run and timing results describe that first source, not the correction below.

Keep the original resource loops limited to at most 4 ms from entry, retaining their evaluated candidates and order. The caller allows up to 7.5 ms for the complete resource phase, still capped by the existing overall deadline minus 17 ms. Only the supplemental NPC tail can use the additional allowance; its two-sweep cap and 2.5 ms admission reserve remain. If the overall deadline leaves less time, existing work retains priority and optional farms are skipped. The complete policy still has its original 32 ms cooperative deadline. This allocation is required to make the new discovery mechanism reachable; it does not expand general resource scanning or any other search.

Structural tests will force existing resource work to reach its original allowance, verify that its candidates survive and later existing resources are not scanned, then verify that the optional tail can use the extra allowance or skips when it is unavailable. Independent replay must confirm actual full-policy selection over the recorded prefix before final validation.
