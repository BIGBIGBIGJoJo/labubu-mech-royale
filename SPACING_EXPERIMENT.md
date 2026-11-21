# Isolated lightning approach experiment

Base: `39b6d509af8e82b0ceb9e1c430dd964674d7488e`, branch `goal/spacing-seven`.
This candidate has no aiming, navigation, economy or rotation changes from the
other experiments. No private match or official score has been run for it.

## Intended behavior

The baseline walks its gun/lightning mech toward a gun/laser opponent whenever
HP exceeds 70%, then switches back to its 120m gun spacing below that threshold.
The recorded baseline encounter at 43–50s lost 948.47 HP while closing from 153.87 m
to 79.04 m and reversing. This trace demonstrates the behavior; it does not prove
that a different policy would have avoided all that damage.

This candidate changes only the choice between baseline 120 m gun spacing and
baseline 33 m lightning spacing for own gun+lightning versus enemy laser(+gun).
Target selection, gun firing, recovery, looting, other loadouts, and movement
execution retain baseline policy. Rejecting the close approach retains the
ordinary gun range controller; it is not a global ban on pursuit or gunfire.

`spacing.py` estimates a conditional engagement budget:

1. Time to lightning range includes current height, cooldown, and yaw turn.
   It reports the constant-velocity relative estimate, but budgets travel
   without crediting an enemy's current motion toward us. Receding velocity
   does count against reaching the target. No boost approach is assumed.
2. An ideal outgoing schedule uses live gun ammo/reload/cooldown, projectile
   flight time, lightning cooldown/energy, and observed cubes. It retains energy
   for boosting during one configured full-charge laser cycle.
3. Incoming uses configured enemy weapons and observed cubes, own armor/front
   arc, a ready/full enemy gun, and observed laser beam phase when available.
   It deliberately schedules full laser damage at minimum-charge intervals.
4. Each ideal future lightning hit shorts the laser for its configured duration.
   Laser capacity resumes after the last short and minimum charge. Simultaneous
   first contact/release counts the incoming beam. Confirmed own hit events with
   `effect=short` persist across observations; an event's earliest possible time
   under-credits its remaining duration.
5. Missing, nonfinite, zero or negative enemy HP declines entry with `unknown_hp`;
   hidden HP is not estimated.
6. Entry needs positive projected health after the ideal finish plus one enemy
   gun+laser burst in reserve. Continuing the same target needs positive projected
   health without that extra burst. This replaces the 70% discontinuity only in
   the modeled matchup. Baseline recovery still takes precedence and clears the
   commitment. Loss of LOS, multiple visible threats, exhausted energy budget,
   or an unreachable target rejects commitment.

## Facts versus model choices

Protocol 184–191 describes live own stats, observed enemy fields and beam ages.
Protocol 293–306 describes armor, weapons and lightning short. Enemy upgrades,
magazines, laser charge age and exact cooldowns are not observed. The model's
ready/full magazine and base statistics are assumptions, not hidden-state facts.

The future model assumes straight-line travel, unchanged current elevation,
exposed LOS, front-facing damage unless currently facing away, all outgoing and
incoming shots hitting, and the target receiving our lightning. Obstructions,
interception by another lightning target, dodging, aim limitations, unknown
upgrades and future movement can invalidate it. It gives no regeneration credit.
The 20 s horizon, one-burst entry reserve, no-extra-burst continuation, no credit
for enemy approach, and one laser cycle of boost energy are policy choices.

In particular, incoming is a base-config capacity estimate, not an absolute
worst-case bound. Enemy 8's observed 55.23 gun hits exceed the 48.024 base-config
cube/armor estimate; unknown upgrades can increase real damage. The recorded
case is rejected even with that underestimate.

Diagnostics include incoming with conditional future short and without it.
The latter is a sensitivity check, not a second simulated match or a forecast
of damage after every lightning misses. Its outgoing finish horizon remains the
same ideal-hit horizon, which would also be optimistic if lightning missed.

## Fixed-observation evidence

The regression fixture is copied from the authorized baseline private trace
`baseline-39b-20261121-162954/trace.jsonl.gz`. The four rows below feed recorded
states into the model. Policy evaluation on this unchanged trace is conditional;
different movement would change later observations in a real match.

| t | HP | Range | Contact budget | Ideal finish | Incoming with short | Without future short | Entry margin with short |
|---|---:|---:|---:|---:|---:|---:|---:|
|43|1568|153.87m|9.31s|10.81s|3026|3362|-1842|
|46|1568|95.01m|4.27s|6.77s|1969|2305|-785|
|47|1066.15|79.04m|2.91s|5.41s|1009|1681|-327|
|50|619.53|106.99m|5.30s|6.30s|1873|1873|-1638|

All four model calls reject entering the close fight. In the full bot, at 50s the
unchanged recovery policy takes precedence, so the spacing model is not called.
At43s it uses the ordinary range/strafe controller; at 46s it requests increased
separation before the baseline's 70% health threshold would have triggered.

Positive fixtures retain close healthy engagements and wounded prey. At35m,
1568 HP versus 1624 HP, conditional short leaves a +608 HP entry margin; disabling
future short changes that margin to −401 HP. An already committed940/1568 HP mech
against 1321 HP at close range continues with positive margin, while a fresh entry
at the same health requires the extra burst reserve. A 95 m / 250 HP prey can be
approached because its ideal gun finish precedes contact.10energy is rejected.

## Validation

- 146 unit/integration tests pass, including 22 new approach tests.
- `git diff --check` passes.
- Final image: `labubu-score7:spacing`, image ID
  `sha256:9bf1297b8e77efd50ced22234407fc86267d30228623813a3e4276d0edf63979`.
- Runtime manifest SHA256:
  `fc71a8e5d101a04753b01cce89b0e60e749b2c8e94b29af172e308bc33512a77`.
- Fresh official checker runs inside Linux with 1 CPU, 512 MB, network disabled,
  read-only root, unprivileged user and real mounted arena: 300/300 timely,
  0 late/wrong-tick/bad lines; p50 11.4 ms, p99 32.2 ms, max 32.9 ms; ready 3002 ms.
- The offline restricted-image diagnostic verifies 259 map prisms and replays all
  1683 recorded observations with zero exceptions/invalid actions. Final policy
  p50/p99/max: 18.03/32.64/34.77 ms; model-only: 0.215/0.551/0.623 ms.
  Of 593 applicable engagement decisions, 5 entered and 36 continued; 552 kept
  ranged spacing (501 health budget, 24 unreachable, 27 multiple threats).
  This is a conservative candidate whose scoring effect remains untested.
  Its machine-readable result is outside this repo
  in `work/game-interface-audit/spacing-linux-conditional.json`.

Previous selective/no-chase experiments scored 2.29–2.69 and also changed firing
authorization; pursuit variants scored 4.21/4.08 and bundled other changes. Those
scores do not isolate this hypothesis. This candidate deliberately preserves
gunfire and uses a single baseline-derived movement change for a new comparison.

A later experiment could optimize a mixed walk/boost approach using energy and
short timing. At the 43 s state, assuming the enemy stops, boosting the entire
108.9 m gap at 19.5 m/s costs about 95 energy before any lightning or escape reserve.
Thus simply enabling full boost is not justified. No such change is included.
