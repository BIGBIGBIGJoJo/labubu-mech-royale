# Preserve recent damage-facing during an unseen-attacker reload

Isolated base: `39b6d509af8e82b0ceb9e1c430dd964674d7488e`.
No spacing, native terrain, scheduling, navigation or other candidate is combined.

## Reproduced problem and narrow change

The bot already selects a recent damage bearing when it has no target or cannot
fire. A later recovery/reload override calls `defensive_yaw`. If that optimizer
has no LOS-qualified inputs, it returns actual torso yaw and erases the useful
selected bearing. The next command therefore asks the mech to hold its current
orientation while an unseen attacker continues shooting.

In the second spacing private trace, 54.3–56.3s contains 21 consecutive instances.
The approach-spacing feature itself never activated: the bot never held
lightning. This facing issue belongs to the shared baseline.

The fix passes the already-selected recent damage yaw as an optional fallback
to `defensive_yaw`. Only its existing `if not incoming` branch uses that value.
Thus the optimizer's exact LOS predicate remains authoritative, including NPC
inputs; there is no second visibility filter. The fallback is populated only
inside the original recent-bearing selection (less than three seconds and a
non-null bearing). The visible-threat optimizer, firing/charging/reload gates,
pitch override and default behavior for other callers remain unchanged.

## Regression and full-prefix replay

The fixture `tests/fixtures/hidden_reload_bearing.json` contains the 21 observed
frames, their recorded commands, expected recent bearings and source trace hash.
All 21 assertions fail against the original facing behavior and pass with the
fix. The additional seven tests cover zero-radian bearings, nonempty but occluded
threat lists, stale/missing bearings, visible mech/NPC optimizer inputs, active
firing, existing laser charge and the exact 0.3s reload boundary.

Both baseline and candidate were run through the complete 613-observation prefix
with the real map in restricted Linux. The baseline reproduces all 21 erroneous
hold-yaw commands; the candidate chooses the recent bearing on all 21.

| Actual comparison on the same 613 observations | Changed commands |
| --- | ---: |
| Aim | **21**, all at 54.3–56.3s |
| Fire | **0** |
| Reload | **0** |
| Weapon take/drop | **0** |
| Upgrade pick | **0** |
| Movement/boost | 53 |

Movement differences begin at 3.5s, before any patched aim decision, in the
existing deadline-sensitive searches. This is not a deterministic full-policy
equivalence claim. Neither replay changes recorded positions, incoming attacks,
or opponent reactions.

## Turn direction and rate evidence

The fixture's actual torso yaw and damage bearing use the same world-yaw frame
(`protocol.md`, self.aim and damaged-event definitions). Its live turn rate is
4 radians/s, physics frequency 20Hz, and decision interval two physics ticks.
Therefore the protocol permits at most **0.2 rad per physics tick**, or 0.4 rad
over a held 0.1s decision interval. None of these frames has an active own charge.

For all 21 frames, the corrected command's wrapped yaw delta from the observed
actual yaw is negative, from -2.345 to -0.893 rad. A one-physics-tick slew capped
by the recorded rate is -0.2 rad in every case and strictly reduces bearing error
by 0.2 rad. Example: at 54.3s, actual yaw 2.142 and bearing -0.203 have error
2.345 rad; the original command requests no turn, while the corrected command
requests a clockwise turn whose next modeled yaw is 1.942, error 2.145 rad.

This is a rate-limited projection from each actual recorded state, not an instant
turn or a counterfactual game. Private input delay, subsequent enemy movement,
occlusion and future commands are not simulated. No prevented-hit, armor-saving,
survival, placement or score claim is made.

## Runtime validation

- **132 tests pass** on the host and inside restricted Linux.
- Fresh official checker and bot both launched inside Linux with the real
  `/arena`: **300/300 timely**, zero errors, late replies, wrong ticks or stale
  replies; ready 3220ms; p50 11.5ms, p99 32.4ms, maximum 33.4ms.
- Full-prefix baseline: p50 20.45ms, p99 31.80ms, max 35.20ms.
- Full-prefix candidate: p50 20.76ms, p99 31.82ms, max 33.10ms.
- Both prefixes: 613 actions, zero exceptions and zero computations over 50ms.
- Restrictions: one CPU, 512MB, no network, read-only root, uid65534, 128-process
  limit and 64MB temporary filesystem. Replay asserts all 259 map prisms.

Image `labubu-score7:hidden-defense`, manifest:
`sha256:f05c7b7a076f33144a5882ded27251b73ccc45e7656fa94a4bb6257b645bb0ff`.
Image Python source hashes match the tested worktree. `bot.py` SHA256:
`69ff8349aba68e17d3d5918768523fd49aac95302624443bf1782f9300547bfb`.
Python runtime manifest SHA256 (sorted `sha256  filename\n` for top-level files):
`05426973282f25f7fba09400a9c75a7c71dcacf59fc0c4115a53576ed4a28dd9`.

## Local evidence

Trace: `spacing-v2-f978f47-20261121-183014/trace.jsonl.gz`, SHA256
`0b7a2dfa444da95ef826bcabce094eec2ce62405b02db90faff9fa3796f5f9a1`.
The complete private trace remains outside the repository; only the regression
window is included. Audit-directory files:

- `hidden-defense-baseline-replay.json` and `hidden-defense-candidate-replay.json`.
- `replay_hidden_defense.py`: full-prefix capture plus labeled rate projection.
- `hidden-defense-linux-tests.txt`, `hidden-defense-official-check.txt`.
- `spacing-v2-f978f47-20261121-183014/SPACING_SECOND_DIAGNOSTIC.md`.

No new private game was launched to validate this candidate. The source change
was reviewed before freeze; official or live performance remains unmeasured.
