# Historical experiment document

This file records earlier experimental branches. The current controlled
experiment is described in PROGRAM_DESIGN.md and DROP_MEMORY_PLAN.md. Its runtime
does not include all mechanisms proposed or tested below.

# Separate candidate: finish commitments and sustained self-defense

Target: 6.0 official practice points. Best historical score: 4.75. The two
scored selective policies returned 2.46 and 2.29. This candidate follows the
confirmed user policy: safe farming, no first attack on quiet mechs, attributed
self-defense, and safe short finishes against weakened enemy-fight participants.
It follows the separately frozen boost/NPC commit `54c9f5f`, submitted as
BB-C709FC88. That official result was still pending during implementation.

## Fire agent

Keep strong attacker attribution for at most eight seconds. During the first
three seconds retain the existing return-fire behavior. Later continuation
requires current visibility, a usable weapon, and an enemy still facing within
0.25 radians of us or moving toward us faster than 1.5 m/s. These observations
cannot establish an attacker or refresh its attribution clock. Recovery keeps
the shorter min(3 seconds, current regeneration delay) limit.

Return an explicit set of currently authorized actors. Permit predicted
collateral only among the selected target and fresh, visible, strongly
attributed attackers. A quiet actor stays protected. Physical first-hit
reachability remains distinct: another authorized body can still stop a bullet
from reaching the intended target. Apply the same set to damage estimates and
the final weapon guard.

Enter a finish only with fresh attributed external fight evidence, current
visibility, known weakened health, a checked escape, and conservative kill time
within the current safety allowance. Give that entry a fixed deadline of at
most two seconds. Continue after the original evidence expires only while
visibility, safety, health and remaining kill time still pass. Healing, missing
visibility, insufficient remaining time, recovery or a defensive override ends
the commitment. Own hits and repeated proof cannot extend or restart it.
Retargeting a lower-health eligible participant keeps the same deadline.

## Movement agent

Retain the separately verified boost latch, emergency escape, zone routing and
terrain checks. Finishing does not authorize a chase or consume the escape
reserve. This candidate changes fire permission, not movement preferences.

## Orchestration agent

Enable the reviewed policy explicitly in the root controller. Thread authorized
actor IDs into weapon guards and expose the fixed deadline and entry evidence
time in diagnostics. Preserve independent NPC/crate permission and unavoidable
held-laser release behavior. Port focused tests from the isolated prototype,
including the recorded missed laser finish at 51.7 seconds and all abort cases.

Run the full regression suite, real-map dense stress, restricted Docker checker
and a private diagnostic. Compare observed permission/abort behavior; private
placement is not an estimate of coordinated practice score. Preserve exact
submitted source and record the official result before claiming improvement.

## Evidence limits

In a recorded private observation, enemy 8 had 255 HP at approximately 196 m,
our bot was at full health and energy, and the conservative laser estimate was
0.75 seconds. The prior permission expired before it could begin. The prototype
accepts entry at 51.7 and continuation at 52.0 under the fixed deadline 53.7.
This is a counterfactual decision test, not a demonstrated kill or score gain.

In another private trace, eight-second defense would add 38 observations of
permission, but none produced an additional immediate gun trigger under frozen
ammo, reload, cooldown and aim states. A competitive benefit remains unproven.
