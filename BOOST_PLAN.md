# Separate movement experiment: sustained boost and recharge

This is a separate candidate after the submitted route/reload fixes. The latest
measured selective follow-up score is 2.29 (its prior version scored 2.46), the retained best is 4.75, and the goal remains
6.0. Do not attribute a score improvement to this experiment before evaluation.
It changes movement availability, not farming or enemy-fire permission.

## Evidence and proposed policy

The current movement planner admits boost whenever energy exceeds 35 (12 during
urgent rotation). Under sustained demand this can repeatedly interrupt the
documented 0.6-second energy-regeneration delay. A reproducible work-only model
found that waiting to recharge from approximately 35 to 65 supports longer bursts
and less restart overhead. It contains no enemies or map and is not a game
simulator or a prediction of competitive improvement.

Add a READY/RECHARGING latch using observed energy. Ordinary boost may run from
the upper threshold down to the lower threshold, then wait for the upper
threshold again. Reserve the next held action's upgraded boost drain and any
lightning shot actually planned by the weapon controller. Clamp the upper
threshold to current capacity without silently reducing the lower reserve.
Use observed energy rather than assuming that a requested action executed.

The latch only controls candidate availability. It never forces boost, ignores
terrain, chases an unauthorized enemy, or changes the existing route/risk scores.
Keep the urgent route correction already validated in the preceding candidate.

## Emergency exceptions

Permit an immediate, collision-checked boost escape during recharge when the
existing trajectory comparisons show a material avoidance benefit against an
incoming projectile or aimed beam. A genuinely close pursuer or an immediate
zone emergency can also justify an exception. Ordinary future-circle rotation,
recovery, or preferred spacing alone must not bypass the recharge latch.

The root controller supplies immediate zone danger and planned firing energy;
the tactical planner evaluates directional hazards within its existing bounded
budget. Emergency use does not reset the latch to READY. Elective FINISH retains
its final energy-reserve check. Mortar impact drain affects the victim and is not
a firing-energy cost.

## Verification

Test latch boundaries, idempotent observations, upgraded stats, external energy
loss, canceled commands, low capacity, and lightning spending. Verify emergency
escape, charging slowdown, collision rejection and the existing urgent-rotation
regressions. Compare the actual planner's decisions on controlled energy and
hazard fixtures, then run full regression, stress and restricted Docker checks.
Private diagnostics remain distinct from the official score. Submit a validated
candidate only after the preceding result is known and the objective remains unmet.

Source mechanics: [official protocol](https://www.joinbuilders.org/buildathon/tracks/builders/files/protocol.md?inline=1).

The actual tactical selector was also run in a controlled straight-line energy
model. With immediate actions, sustained boost duty rose from 13.10% to 43.40%
and mean speed from 12.50 to 15.09 m/s; the ordinary reserve stayed at least
35.4. With the private interface's measured 0.3-second input delay, the same
comparison was 36.0% to 45.5% and 14.51 to 15.25 m/s. Queued commands could
overshoot the reserve to 30.1 in that delayed case. These measurements have no
enemies, weapons or terrain and do not predict an official score.

A separate schema correction accepts the documented `npc` projectile kind in
finish safety's straight-projectile danger check. Previously, even a harmless
NPC bullet vetoed entry as an unknown hazard. The exact observed harmless bullet
and an approaching NPC bullet have regression coverage. Unknown projectile kinds
continue to withhold finish permission.
