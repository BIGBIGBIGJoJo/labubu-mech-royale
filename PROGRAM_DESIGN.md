# Nearest-enemy pursuit: program design

The requested strategy is greedy and aggressive: approach the nearest enemy
quickly, use the available weapons together, reload during safe gaps, and heal
when health is low and no enemy is nearby. The user explicitly selected equal
treatment of enemy mechs and NPC drones, and current weapon reach as the meaning
of nearby. The official target remains **6.0**; the best verified score is 4.75.

The initial pursuit candidate started from exact best source `39b6d50`. It
scored 4.21 as `919f826`; the current isolated spacing follow-up starts from
that pursuit commit. The best 4.75 entry remains selected. SPACING_PLAN.md
describes the gun-only versus mech spacing revision. The first-magazine and
drop-memory experiments scored 4.58 and 4.63 and are not included. A later NPC
farming experiment was not submitted; its optional search was starved of time
in real opening replays. That experiment remains separate from this pursuit
design.

## Orchestration strategy agent

Select the nearest currently reported living mech or NPC using distance, with
stable tie-breaking only. Keep pursuit intent separate from permission to fire
through a physically clear shot. Treat an enemy within the geometric reach of
a held weapon as nearby even while that weapon is empty or cooling down, so a
reload does not make danger disappear.

Prioritize urgent zone access, nearby combat, quiet low-health recovery,
nearest-target pursuit, then resources and exploration. Resource goals must
not replace a pursuit target; immediately reachable pickups can still be taken.
Use the shared nearby-enemy signal to control recovery and optional reloads.
See ORCHESTRATION_PLAN.md for the precise contract and regressions.

## Movement strategy agent

Approach the selected target promptly using bounded ground navigation and
weapon-aware spacing. Give pursuit its own boost preference: the baseline's
ordinary boost penalty exceeds the progress benefit in a straight six-tenths
of a second rollout, so ordinary pursuit often walks even with available energy.
Retain energy, collision, projectile, beam and zone checks. Never represent a
pursuit as an urgent zone escape merely to force boost.

Approach distances are explicit engineering parameters, not claims of optimal
play. Movement should make the loadout useful without entering another body or
an unsafe self-splash distance. See MOVEMENT_PLAN.md.

## Fire strategy agent

Coordinate the held weapons through their shared torso aim, using actual
weapon statistics, target motion and world geometry. Nearby combat must not
be suppressed solely because health crossed the recovery threshold. Retain
the urgent-zone movement constraint on expensive charging.

Both optional partial-reload paths must obey the no-nearby-enemy rule. An empty
magazine still needs reloading to restore firepower. Reload readiness, laser
charge/release, lightning energy and mortar arcs remain governed by the protocol.
See FIRE_PLAN.md for the concrete API and tests.

## Evidence and evaluation

Actor listings can persist after visual contact is lost. A currently reported
position is not proof of fresh visibility, a clear shot or a traversable route.
Use explicit geometry checks and bounded work, and document any remaining
observation limits rather than treating remembered coordinates as guaranteed.

The process remains one deterministic Python bot, with no runtime network or
model calls. It must answer within 50 ms under one CPU and 512 MB. Test the
controller stages, integrated pursuit decisions, real-map timing and the Linux
container, then freeze the source for private diagnostics and official scoring.

Official practice points are mean `16 - place` over 48 matches. NPC farming and
mech kills can help through power and elimination, but do not directly add
practice points. Report private kills and placement separately from the official
score. Preserve every submitted commit and retain the highest accepted entry
unless the user explicitly selects another.
