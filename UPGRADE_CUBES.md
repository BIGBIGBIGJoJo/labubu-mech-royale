# Post-cap cube utility experiment

Base: selected aiming source `53d8d79502763325184252761ccc9ff7bbf5081e`.
Branch: `goal/upgrade-cubes-seven`. This is a controlled standalone experiment,
not a demonstrated improvement. No game or official submission has tested it.

## Change

The only runtime change removes the flat six points per cube beyond the
configured HP/damage stat cap from `Bot.resource_goal`:

```python
benefit = 32 * useful + (25 if threshold else 0)
```

Useful cubes still contribute 32 each. Recovery healing still depends on those
useful cubes. Crossing any configured upgrade threshold still contributes one
25-point bonus, including when a group crosses several thresholds. Existing
offers, upgrade selection, automatic pickups, objective continuity, other
resources, collision/navigation, firing and all other weights are unchanged.
There is no hard count cap or body-growth penalty.

The hypothesis is that this removes some unnecessary surplus pursuits and
reduces willingness to travel for an upgrade. It can also forgo valuable
upgrades; the experiment does not assume those opportunities are worthless.

## Observed-state evidence and tradeoffs

The prior read-only audit compared complete resource choices on 38 recorded
states, reconstructing loot memory and restoring recorded prior resource,
recovery, stuck/blacklist and movement state. It changed only the six-point
term in memory. Resource scoring source is identical across the selected base
and both traces. Original full-choice reconstruction matches the recorded
resource in 37/38 states; reactive 117.0 is the documented exception. Calls had
no optional-work deadline and therefore are not timed full-policy replays.

| Actual private state | Original score | Candidate score | Conditional decision |
|---|---:|---:|---|
| Kernel 129.9: 10 cubes, ten-cube pile 43.275 m away, crosses 15 | 62.497 | 2.497 | Still selects the whole pile |
| Kernel 141.4: 20 cubes, two remembered cubes 68.982 m away, crosses 21 | 0.829 | -11.171 | No resource admitted |
| Kernel 146.7: 32 cubes, three visible cubes 4.148 m away, no threshold | 15.843 | -2.157 | No resource admitted |
| Reactive 101.3: 12 cubes, five-cube pile 69.410 m away, crosses 15 | 18.907 | -11.093 | No resource admitted |
| Reactive 104.4: same count/group, now 41.908 m away | 33.208 | 3.208 | Still selects pile |
| Reactive 126.4: 22 cubes, ten-cube pile 4.524 m away, held, crosses 28 | 92.647 | 32.647 | Still selects whole pile |

The retained kernel 10-to-20 and reactive 22-to-32 piles demonstrate why this
is not general oversized-body prevention. Their actual corresponding radius /
height changes are 3.75/13.5 to 5/18 m and 5.25/18.9 to 6.5/23.4 m. No direct
HP/damage benefit exists above ten in these configurations, but upgrade
benefits remain. No smaller final body is established by the comparison.

The initial kernel second-pile decision knows only two remembered cubes, not
the eventual seventeen-cube collection. Rejecting it could delay or forgo the
actual later threshold-21 servos, threshold-28 armor and threshold-36 servos.
The first pile's threshold-15 laser damage upgrade remains valued. Both
nanites stacks in that trace were acquired before the stat cap.

The reactive trace's rejected longer pursuits led to actual threshold-15 laser
damage, threshold-21 reactor and threshold-28 laser damage offers. These have
real benefits. Later closer snapshots still qualify; at some intermediate
states the existing drop objective instead wins. The audit does not assume
the same offers, later positions or collection would occur after an earlier
choice changes.

The three-cube group at count 32 would reach 35, one short of threshold 36.
Its future value is not zero. At the next recorded count of 34, the same local
group crosses 36 and becomes positive again. Automatic pickups and delayed
actions are not simulated; a rejected objective is not proof of prevented
collection.

Other explicit limits:

- A held, close, no-threshold objective may remain positive from the unchanged
  ten-point continuity bonus.
- Large and small groups crossing any threshold receive the same 25 bonus;
  the existing coarse threshold heuristic is not an expected upgrade value.
- Resource score is not a route or post-pickup clearance certificate.
- Private outcomes are not official score evidence for this change.

Full audit artifacts live outside the repository at
`work/game-interface-audit/POSTCAP_FLAT_UTILITY_AUDIT.md` and
`POSTCAP_FLAT_UTILITY.json`. The relevant trace hashes and scalar cases are
retained in `tests/fixtures/postcap-utility.json`.

## Focused validation

`tests/test_upgrade_cubes.py` uses official schemas/configuration and the
existing flat controlled arena to isolate valuation. Its recorded scalar
fixtures preserve count, group size, travel and prior-objective continuity;
they are not original-map or alternate-game fixtures.

Eight focused tests cover the five recorded scalar cases, pre-cap value and
healing, a cross-cap bundle's last useful cube and healing, absence of phantom
post-cap healing, one bonus across multiple thresholds, no invented future
cube/offer value, unchanged current offer choice, preserved continuity and
an unaffected weapon alternative. Observation equality confirms valuation
does not simulate automatic pickup.

Host validation before source review: eight focused tests and 16 existing
economy regressions pass. Root and independent source review approved this
exact one-line experiment for the following runtime gate.

## Restricted Linux validation gate

Immutable runnable image:
`sha256:4c00ccf824d14e4a29a731548e1f720338e21039b40cefab837b6a87880d9339`.
The reviewed uncommitted bot's normalized-LF SHA-256 is
`f7f2a9953e017ca00f929ccf182d4a95fd376aa9f3d11d5f006087d600a1b503`.
The other ten Python/binary runtime entries match selected source `53d8d795`
exactly. The terrain library SHA-256 is
`61973f3bcbbcacfabb5f543e3fe12c47b7d34d31d6c7d48e9932b051a4211dc0`.

All checks use linux/amd64, one CPU, 512 MB memory and swap, a 128-process
limit, no network, read-only root, UID 65534 and a 64 MB temporary directory.
Initialization asserts the actual 259-prism / 774,680-sample map, loaded
native terrain kernel, both binary caches and original Python movement map.
Every packaged Python/cache file is compared to the reviewed source.

- Full Linux suite: **225 tests passed**, zero failures, errors or skips.
- Official checker: **300/300 answered**, zero 50 ms misses, wrong ticks,
  stale responses or malformed lines. Answer times: p50 9.5 ms, p90 17.5 ms,
  p99 26.5 ms, maximum 29.6 ms. Ready time was 3,145 ms.
- The checker ran inside the immutable image as
  `python3 -u /kit/check/check.py --map-dir /arena -- python3 -u /bot/bot.py`.

Six original-map recorded-memory snapshots then ran the unchanged candidate
and baseline `resource_goal` methods with a fresh 4 ms optional-work deadline,
three trials each with alternating order. `Bot.update` consumed only preceding
actual observations; recorded recovery, prior resource, stuck/blacklist and
last movement were restored identically. These are resource-phase calls,
not complete `Bot.act` or counterfactual chronological replays. No unrecorded
goal expiry or navigator search state was invented. No snapshot has an active
resource lease.

| Snapshot | Candidate choice, all three trials | Candidate ms range | Baseline ms range |
|---|---|---:|---:|
| Kernel 129.9 | Retain cube 5091, ten-cube threshold pile | 0.756-1.323 | 0.836-1.006 |
| Kernel 141.4 | No resource | 0.280-0.370 | 0.275-0.299 |
| Kernel 146.7 | No resource | 0.330-0.423 | 0.335-0.420 |
| Reactive 101.3 | No resource | 0.184-0.275 | 0.190-0.255 |
| Reactive 112.6 | No resource | 3.229-3.767 | 3.269-3.681 |
| Reactive 126.4 | Retain cube 5071, held ten-cube threshold pile | 4.047-4.389 | 4.029-4.396 |

All 18 candidate calls agree with the prior unbounded conditional choices;
all 18 baseline calls agree with the recorded resource. The dense 126.4 call
can exceed 4 ms in both versions because the existing method checks the
deadline between candidates and completes already-started work. Four
milliseconds is not a hard execution bound. The full checker provides the
separate end-to-end timing result above; these snapshots do not establish
full-match timing, altered acquisition, health or score.

Audit artifacts outside the repository:
`upgrade-cubes-runtime-manifest.json`, `upgrade-cubes-linux-tests.json`,
`upgrade-cubes-linux-tests.txt`, `upgrade-cubes-checker.txt`,
`upgrade-cubes-budget-witnesses.json` and `upgrade-cubes-budget-witnesses.txt`
under `work/game-interface-audit`. They retain source/map/trace hashes and
driver provenance. No source freeze, private match or official submission
was run for this gate.

## Continuous-state chronological validation

After the gate was approved, the unchanged immutable image ran three full
original-observation chronologies with a fresh `Bot` per trace. Existing
`reactive_recovery_prefix.py` called `Bot.act` without hooks or extra work
inside its timer. The same restrictions, original map, native terrain,
Python movement, source equality and both-cache preflight applied. Exact
selected-53d integrated/kernel baselines were reused; a new exact-53d
reactive baseline ran under the same restrictions. All four completed.

| Trace | Frames | Candidate p50 / p99 / max ms | Baseline max ms | Nonzero MOVE baseline/candidate | Fallback baseline/candidate |
|---|---:|---|---:|---:|---:|
| Integrated | 1,594 | 23.004 / 31.395 / 33.147 | 31.805 | 1,296 / 1,298 | 16 / 17 |
| Kernel | 1,723 | 14.179 / 30.969 / 33.374 | 32.226 | 1,637 / 1,637 | 2 / 3 |
| Reactive | 1,480 | 19.930 / 31.236 / 36.793 | 35.348 | 1,369 / 1,365 | 6 / 7 |

All 4,797 candidate calls and 1,480 newly run baseline calls have zero errors
and zero 50 ms misses. Candidate calls above the internal 32 ms target number
3 / 2 / 1 respectively; the baseline counts are 0 / 1 / 2. These single
deadline-limited runs do not establish a timing improvement. Fallback counts
increased by one per trace and movement is not generally increased.

Every aim, fire, reload, pick, take and drop command and selected target is
identical to its exact-53d reference across all 4,797 candidate frames.
Observed offers remain the original inputs: one integrated, eight kernel
and seven reactive offer IDs, with identical picks. The comparison neither
invents new offers nor asserts the same offers would occur after changing
real gameplay.

The intended resource change persists with continuous controller memory:

- **Kernel:** post-cap cube-objective frames fall from 90 to 73. Resource
  identity changes on 51 post-cap frames: 17 cube-to-none and 34 changes
  between cubes. No-cube spans are 141.4-142.7 (14 frames), 143.0-143.1
  (two) and 146.7 (one). The first 10-cube threshold pile remains selected
  at 129.9. At 141.4 the distant remembered two-cube objective is rejected.
  Closer cubes become eligible at 142.8; threshold collection is not banned.
  At count 32, the no-threshold group is rejected at 146.7; the actual next
  count of 34 restores threshold eligibility at 146.8.
- **Reactive:** post-cap cube-objective frames fall from 201 to 74. Resource
  identity changes on 128 post-cap frames: 69 cube-to-none, 58 cube-to-drop
  and one change between cubes. The distant pile at 101.3 is declined through
  103.9 (27 frames), then admitted at the closer recorded position at 104.0.
  The 112.6 distant pursuit is declined through 116.4 (39 frames). Further
  no-cube spans are 116.7-116.9 (three), 117.8-122.3 (46), and 122.6-123.7
  (12), including an already-existing drop alternative. Cube 5071 becomes
  selected at 123.8 and remains selected at 126.4; the ten-cube pile is still
  allowed. This does not prove avoidance of the actual 22-to-32 size growth.
- **Before the cap:** kernel resource/mode/goal/action choices are identical.
  Reactive resource/mode/goal choices are identical, including both sides
  of the actual 1-to-12 crossing at 100.9/101.0; eight movement and one boost
  commands differ elsewhere before the cap. Integrated never reaches the
  cap and has no changed cube objective. A conservative superset of its
  last-45-second cube memory proves the removed term is zero throughout.
  Its ten non-cube resource and eight mode differences are therefore not
  claimed as a valuation effect; deadline/state variation is present in
  these single runs. The per-frame artifacts retain every difference.

Total normalized goal changes versus the reference are 35 / 51 / 163;
movement-command changes are 81 / 44 / 191; boost changes are 12 / 6 / 8.
The raw observations still contain the original positions, HP, cube counts,
weapon states, offers and events even after a changed command. No smaller
final body, extra healing, avoided damage, preserved upgrades or higher
placement is established. The verified conclusion is narrower: the one-term
experiment declines several sustained distant surplus pursuits while
retaining useful and nearby threshold opportunities, within the tested
runtime envelope.

Full artifacts are `upgrade-cubes-4c00-{integrated,kernel,reactive}.json`,
`upgrade-cubes-4c00-reactive-baseline.json` and corresponding logs, with
`upgrade-cubes-chronology-comparison.json` retaining all per-frame resource,
mode, goal and action differences and source/trace/artifact hashes. The
comparison script includes the explicit fixed-future limitation. No further
runtime edit, private game or official submission was made during validation.
