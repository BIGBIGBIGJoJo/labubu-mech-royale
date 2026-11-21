# Conditional laser-warning boost experiment

Base: `39b6d509af8e82b0ceb9e1c430dd964674d7488e` (reported official score 4.75).
This branch has no new match score. Replays below do not react to changed actions.

## Runtime change

The ordinary movement controller admits boost only above 35 energy, or above 12
when rotating urgently. In two recorded encounters that reserve excluded a
geometry-valid boosted action while the existing current-aim laser cost already
recognized danger.

This branch only relaxes that admission gate when all these conditions hold:

- The ordinary gate is closed and the mech is grounded.
- Energy can pay for the configured physics ticks in one decision interval
  (`boost_drain * physics_dt * decide_every`; 1.7 energy in the observed config).
- One of the existing top-three threats is visibly charging and has the existing
  positive LOS flag.
- The existing laser warning cost is positive on the unboosted navigation rollout.

The usual candidate ranking, remaining-energy penalty, own laser charging speed
penalty, collision validation, and deadline remain unchanged. Opening the gate
does not force a boost. `tactical.emergency_boost` records admission; the returned
action's `boost` records selection. Combat, fire policy, targets, goals and economy
source are identical to the baseline.

## Conditional evidence

An initial paired probe captured baseline controller inputs after a complete
observation prefix, then compared the unchanged scorer to the gate variant at
identical inputs and with the same timing budget. All three alternating-order
repeats selected a valid boosted action at economy 27.4/27.8s and recovery
55.6/55.8s. At recovery 53.1s the gate opened but the scorer chose walking.

The production-image full-prefix replay preserves the bot's own internal state
through every observation. The bot receives no future beam data. Only after all
actions are chosen does `check/evasion_replay.py` compare their constant-action
rollout with a later recorded beam, extended to the configured full range rather
than stopped at its old hit endpoint. Clear means horizontal body miss exceeds
the cube-scaled radius plus a 0.1m diagnostic margin.

| Trace / decision | Baseline walk miss | Candidate run 1 | Candidate run 2 |
| --- | ---: | ---: | ---: |
| economy 27.4s, radius 2.5m | 2.37m, hit | boost, 6.29m, clear | boost, 6.29m, clear |
| economy 27.8s, radius 2.5m | 2.31m, hit | boost, 3.03m, clear | boost, 3.13m, clear |
| recovery 53.1s, radius 3m | 0.36m, hit | walk, 0.22m, hit | walk, 0.22m, hit |
| recovery 55.6s, radius 3m | 2.04m, hit | boost, 5.42m, clear | boost, 2.97m, hit |
| recovery 55.8s, radius 3m | 2.06m, hit | boost, 3.17m, clear | boost, 1.99m, hit |

All selected warning actions passed the full 0.6s geometry rollout in these
replays. Admission occurred on 4 economy frames per run (4/3 selected boosts)
and 16 recovery frames per run (13/13 selected boosts). Modeled remaining energy
was at least 18.3. This is retained energy under the existing movement model;
it does not forecast simultaneous weapon energy expenditure or enemy retargeting.

The two recovery runs chose different earlier goals/navigation under the existing
wall-clock budgets. Both selected valid boosts, but only one cleared the later
recorded ray. This limitation is part of the result. The experiment does not
establish higher survival, damage, or official score.

Recorded laser hit times are 28.0s, 53.7s and 56.2s. With beam age 0.1s and
physics dt 0.05s, the evaluated emission is the first physics frame after the
prior decision. A held action and fixed future enemy ray are evaluation
conditions, not observable facts available to the policy. The unchanged online
warning uses the enemy's current aim and central configured muzzle height; it
does not predict enemy turning or add the barrel extension. This branch retains
the existing outgoing LOS flag and top-three threat limit. A ten-trace audit
found no damaging laser episode explained by those filters dropping a visible,
positive current-aim warning, so neither filter was broadened here.

## Validation

- 131 unit tests pass, including actual selected boost, absent/aim-away/occluded
  warnings, whole-decision energy, airborne rejection, collision rejection,
  charging slowdown, and preservation of the ordinary urgent boost behavior.
- Fresh official kit checker launched inside Linux with the real `/arena` mount:
  300/300 timely; zero errors, late answers or wrong ticks; ready 3075ms;
  p50 11.1ms, p99 34.6ms, max 35.4ms.
- Container restrictions: 1 CPU, 512MB, no network, read-only filesystem,
  unprivileged user, 128 process limit, 64MB temporary filesystem.
- Real-map replay asserts the map is available with all 259 solid prisms.

| Full-prefix replay | Observations | p50 / p99 / max ms | Errors / over 50ms |
| --- | ---: | --- | --- |
| candidate economy run 1 | 304 | 22.77 / 33.45 / 39.13 | 0 / 0 |
| candidate economy run 2 | 304 | 22.52 / 32.25 / 33.65 | 0 / 0 |
| candidate recovery run 1 | 593 | 13.19 / 32.00 / 33.31 | 0 / 0 |
| candidate recovery run 2 | 593 | 13.51 / 32.81 / 33.68 | 0 / 0 |
| baseline economy control | 304 | 22.89 / 33.38 / 34.56 | 0 / 0 |
| baseline recovery control | 593 | 13.82 / 32.41 / 33.20 | 0 / 0 |

Trace identifiers: `economy-297966f-20261121-172726` and
`recovery-e7c6248-20261121-174602`. Local raw diagnostics are the corresponding
`evasion-replay-*.jsonl`, `evasion-control-*.jsonl`, and `evasion-gate-probe.json`
files in the workspace audit directory. No private trace is embedded in this repo.

Reproduce with a provided trace and matching map:

```text
python check/evasion_replay.py --repo . --trace TRACE/trace.jsonl.gz --map-dir arena --runs 2
```

Runtime `tactical.py` SHA256:
`2d5cc71f9588de53ea3a2bb023721de6be256bed3e66f8cc4af0fbeeda9db484`.
Runtime manifest SHA256 (sorted `sha256  filename\n` for top-level Python files):
`a493ecc74f630fb54428f2e5e12bb5e0e543f7f197d48df8872f75d931d0228a`.
