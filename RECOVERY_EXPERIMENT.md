# Recovery incoming-exposure experiment

Isolated from `39b6d509af8e82b0ceb9e1c430dd964674d7488e` on
`goal/recovery-seven`. No game or official score has been run for this candidate.

## Confirmed problem

Baseline `position_cost` scores protection using our muzzle to the enemy's
center. That outgoing ray can be blocked while an enemy-to-our-upper-body ray
is clear. In the C1 private trace (`correctness-ab878-20261121-163846`), the
controller repeatedly assigns zero exposure cost to its current recovery
position at 95, 97, 99, 100, 101 and 102 seconds. Three of five offline incoming
body samples are clear. At 101 seconds it stands at `[47.76,-51.33,2.45]`; the
recorded laser at 102 seconds deals 401.44 HP damage there.

Static geometry also contains reachable alternatives. At 95 seconds the existing
bounded 12-candidate generator offers `[-11.072,-76.604,-0.0097]`, 52.6 m away:
the endpoint is clear, its direct walking segment is clear, and all sampled
incoming rays are blocked. Its old cost is 11.56 from travel, so the incorrect
zero-risk origin beats it. The issue is not simply absence of geometry candidates.

## Narrow change

- Recovery position scoring uses enemy muzzle to our upper center, center, and
  two upper width samples. Own dimensions use live stats and cube growth once.
  Enemy geometry uses configured dimensions and observed cube growth.
  Its source is the central configured muzzle height, without horizontal barrel
  extension. This is a sampled exposure model, not an exact firing trajectory or
  a guarantee that the whole body is protected.
- A clear ray immediately establishes exposure; remaining samples are skipped.
  Width sampling is optional in the reused helper, so its outgoing API retains
  its original behavior. Only recovery scoring calls the new variant.
- An exhausted deadline/ray budget, unknown geometry, or unmodeled mortar path
  remains uncertain and receives exposure cost. It never becomes protected.
- Origin and candidate goals use the same incoming test. Each recovery scan
  rescans the origin and previous selected goal, then rotates the remaining
  candidate order. Only resolved candidates advance the cursor; a potentially
  protected candidate interrupted by the budget is revisited first next time.
- The scan retains existing deadlines and adds a 64-new-ray cap per observation.
  Upper body is checked first to avoid two queries for the common low-cover case.
- Firing, target selection, resource policy, movement execution and non-recovery
  position scoring remain baseline behavior. This is not a global shooting gate.

The initial incoming-only change, without the rotating scan, failed its actual
prefix replay: only 3–5 near candidates were repeatedly evaluated, while useful
cover remained late in the list. The bounded scan addresses that starvation.

## Full-prefix evidence and limits

The entire C1 observation prefix was replayed inside the restricted Linux image,
preserving prior controller state and its deadlines. This is fixed-observation
conditional evaluation, not a new match or proof of damage avoided.

The implemented controller selects protected candidates in the actual replay:

| Selection time | Distance | Route evidence | Nominal walking time |
|---|---:|---|---:|
|86.3 s|47.2 m direct distance|Completed validated ground route, about 177 m|15.12 s|
|89.9 s|44.6 m direct distance|Completed validated ground route, about 103 m|8.81 s|
|93.7 s|41.8 m|Direct segment and endpoint clear|3.57 s|
|96.2 s|51.9 m direct distance|Completed validated ground route, about 56.7 m|4.84 s|

At 93.7 seconds the selected direct destination is
`[14.520,-73.386,0.740]`. Nominal arrival is about 97.3 seconds, before the
recorded 102-second laser. These times divide geometric walking distance by
observed walk speed; acceleration, tactical detours, future enemy motion and
incoming fire are not simulated. Static route proofs validate each path segment
plus its connections to actual start and goal, using cube-scaled dimensions.

Material limitations remain: a previously protected endpoint can become exposed
as an enemy moves (observed at the 95-second checkpoint). At 101–102 seconds the
selected covered endpoints have no completed route in an 80-call bounded static
audit. Candidate travel cost remains Euclidean, which understates detours. Body
samples also do not prove complete shielding of the whole collision cylinder.
The experiment therefore establishes corrected geometry and timely reachable
selections, not guaranteed escape or a scoring improvement.

## Recovery audit across five traces

Protocol health rules require no damage dealt or taken for the regeneration
delay. Accounting uses `hit` and `damaged` events, including NPCs and crates;
shooting commands that miss are not treated as damage. Event time is observation
time and has up to one decision interval of uncertainty.

| Trace | Recorded regen during recovery | Relevant finding |
|---|---:|---|
|Baseline 39b|835.21 HP|Early retreat heals successfully after reaching sampled cover; late close lightning shorts are valuable defensive fire.|
|C1 ab878|0 HP|Outgoing hits at 96.0/96.2/96.7/97.0 s postpone eligibility from 99.6 to 102.0 s, when the next laser lands.|
|Aim 2dba505|0 HP|Only about 1.9 s of recovery before the final observation; too short for its 5 s delay.|
|Navigation fc474fd|121.5 HP|Three quiet incoming windows are extended by outgoing hits on a distant enemy.|
|Rotation 230f9b5|389.26 HP|Successful quiet regeneration starts at 82.3 s; later contact with another enemy ends it.|

C1's delayed eligibility spans 2.4 s / 108 HP of configured regeneration capacity
under the unchanged incoming schedule. Navigation has analogous 2.3, 2.2 and
1.5-second deferrals. These figures are timing-accounting opportunities, not
counterfactual damage saved: shooting can affect enemies and lightning suppresses
lasers. Baseline close-range hits at roughly 35–45 m should therefore not be
blanket-suppressed. This candidate leaves all existing fire rules unchanged.

All recovery-period outgoing hits in these five traces target mechs. Cube pickups
are separately accounted: baseline and C1 each gain 168 HP/max HP from three
cubes; rotation gains 112 from two. Upgrade events provide no immediate observed
healing. Baseline nanites changes its regeneration delay/rate to 3.5 s/72 HP/s;
other inspected recovery windows use 5 s/45 HP/s. No crate hit with missing HP
appears in these five traces, so crate-related timing is protocol-based here.

## Validation artifacts

- 153 tests pass, including incoming/outgoing asymmetry, width exposure, 3D cube
  scaling, conservative deadline behavior, bounded scan progress and the actual
  C1 generator/safe-goal fixture. Existing firing tests continue to pass.
- `git diff --check` passes.
- C1 restricted Linux replay: 1,045 observations, zero errors; p50 30.27 ms,
  p99 34.30 ms, maximum 42.17 ms. Maximum 18 fresh cover rays in a search.
- Diagnostics outside the repo: `recovery-audit.json`,
  `recovery-geometry-audit.json`, `recovery-c1-linux-conditional.json`, and
  `recovery-early-route-proof.json` in `work/game-interface-audit`.
- Docker image: `labubu-score7:recovery`; the official checker output is recorded
  in `work/game-interface-audit/recovery-linux-check.log`.

Historical broad selective-fire variants scored 2.29–2.69 and bundled firing and
movement changes. They do not evaluate this isolated recovery geometry change.

Final restricted Linux official checker: 300/300 timely, no late/wrong-tick/bad
lines; p50 12.6 ms, p99 35.6 ms, maximum 44.5 ms, ready 3576 ms. Run with
network disabled, 1 CPU, 512 MB, read-only root and an unprivileged user.

Runtime manifest SHA256: `1d745bb4a615c31061418ed2f4bdbd050562ecc66b5c56cf7b93cab52ee733d1`.
