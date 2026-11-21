# Historical experiment document

This file records earlier experimental branches. The current controlled
experiment is described in PROGRAM_DESIGN.md and DROP_MEMORY_PLAN.md. Its runtime
does not include all mechanisms proposed or tested below.

# Aggressive orchestration candidate

This plan was written before implementation and now documents aggressive-v1.
The user requests greedy, aggressive play with as many kills as possible and
an official target of 6.0. This supersedes no-first-attack and external-fight
requirements. Prior selective candidate `01df3dc`, receipt BB-AC10AB33, scored
2.69; historical best `39b6d50` remains 4.75.

## Objective and official constraints

Official score is mean `16 - place`, not kills: 6.0 corresponds to mean placement 10.0; 4.75 corresponds to 11.25. Report both kills and placement, without inventing a combined score. Repeatedly remove opponents and collect useful resources while remaining alive for further kills.

Practice comprises 48 matches against 15 cooperating house bots: four easy, four medium, four hard, three expert. They share visibility, never fight each other, and send weaker hunters first, with more joining as opponents disappear and all joining late. Seeds are private and fixed; slot/spawn vary. Precise hunter thresholds and targeting internals are unpublished. Do not infer a hidden mode, seed, or safe opening interval. FFA finals/private games differ.

Killed mechs drop their cubes plus two. Cubes add HP and damage through the ten-cube stat cap, unlock upgrades, and increase size without a cap. More cubes do not mean unlimited damage scaling. Drop capture gives three cubes and full HP/energy after its uncontested capture clock. Base regeneration requires five seconds without dealing/taking damage; continuous low-value shots can prevent healing. Timeout survivors rank by HP. These rules support aggression plus deliberate recovery rather than exposure at any cost.

Sources: [official rules](https://www.joinbuilders.org/buildathon/tracks/builders), [protocol](https://www.joinbuilders.org/buildathon/tracks/builders/files/protocol.md?inline=1). Published quota is four submissions per hour; the board retains each team's best practice score. Every submitted commit must remain public. Runtime: 50 ms/action, 1 CPU, 512 MB, no network, restricted filesystem.

## First candidate scope

Use current verified mechanics with the broad proactive policy of the 4.75 baseline. That baseline selected current reachable targets without requiring a prior hit, approached its weapon band, favored wounded/nearby/continuous targets, and preserved quiet healing. Selective scores 2.46, 2.29 and 2.33 do not identify which individual change caused the decline. Private wins are not official strength estimates.

Retain cube-scaled collision, partial-route/failure handling, actual firing-ray checks, leading, weapon scheduling, laser charge semantics, quiet-reload protection, energy hysteresis, urgent-zone progress, stale resource hazard memory and drop semantics. Include the validated recovery escape fallback as a separately documented change, without attributing its effect to aggression.

Initially retain the measured 120 m gun / 150 m laser spacing. These are policy settings, not weapon ranges. Earlier local avoidance scenarios favored these over 70 m (`work/range_benchmark_results.json`). Removing the approach ban is already substantial. Movement agent agrees narrower 80–110 / 110–140 m bands remain an unvalidated follow-up. Preserve conditional lightning entry, continuous energy checks, and the opposing-mortar rush refusal.

## Agent contract

The root enables `AggressiveEngagement(config, line_of_fire=None).select(obs, candidates, recovering=False, deadline=None)`, returning an `AggressiveDecision` for a selected target. It carries mode, current target, allow_fire, reason, finish_eta, finish_weapon and authorized_ids; an observation-only result may use the base Decision. All current hostile mech IDs may be attacked. Evidence age, attributed damage and fixed evidence leases do not gate offense. Missing actors remain hazard memory, not firing targets.

The existing finish ETA is a bounded short-kill estimate, not general fight duration. `None` must not exclude a healthy enemy merely because it takes longer than two seconds. Prefer a physically usable short kill; otherwise use the measured baseline's risk/wounded/distance/continuity ranking plus readiness and reachability. Minimum HP alone cannot justify selecting a target behind a wall or beyond a usable weapon.

PURSUE/FIGHT/EXIT are conceptual priorities expressed through the root's current `state`, `mode`, `goal` and `spacing_target` fields, not a separate intent API. Positive approach is permitted along verified routes; urgent zone movement and escape override it. With no usable firing target, a current LOS enemy can guide pursuit without receiving an unavailable shot. All-enemy permission does not make bullets pass through bodies or lightning select a farther actor. Preserve first-hit/nearest-target physics, laser pierce and self-splash constraints. An intervening enemy may itself be a productive target.

Root owns arbitration, recovery fire, resources, telemetry and explicitly enabling the new selector. Selective Engagement may remain for isolated legacy tests; it must not silently remain the root default.

## Priorities

| Priority | Movement | Fire |
|---|---|---|
| Urgent zone | Verified route into current/future circle; no pursuit/loot detour | Current reachable targets if firing does not prevent needed escape; avoid unsafe slowing charge |
| Immediate survival/recovery | Break exposure, find reachable cover or beneficial healing resource, regenerate | Active-pressure damage or credible short kill; stop discretionary long trades for a real quiet-healing opportunity |
| Short kill | Current position or ordinary collision/zone-aware approach, subject to existing recovery and energy behavior | Prefer current reachable target with verified short ETA; recheck each frame, no old evidence lease |
| Productive fight | Approach weapon band, then strafe/lead | Attack proactively; retain continuity unless a materially better short kill or immediate threat appears |
| Loot/farm/reload | Useful cubes, weapons and drops; safe farming when no productive exchange takes priority | Selected farm target with actual muzzle/pitch checks; partial reload only with threat separation/cover |
| Search | Useful in-zone resource/observation position | Scan; no fabricated current target from stale memory |

Recovery movement remains separate from firing. Recovery starts below 55% HP, or below 82% with at least two current LOS mechs, and ends at 93% HP or the tiny-zone terminal exception. During recovery, firing requires a verified short kill within 1.25 seconds while above 15% HP, a visible threat within 28 m, or weapon damage within the shorter of three seconds and the live regeneration delay. Otherwise the bot preserves quiet healing. The recovery short-kill resource priority shares the HP floor, so a declined critical-HP kill does not suppress a reachable healing cube. These thresholds are strategy parameters, not guarantees of survival.

Fresh laser charging during recovery additionally requires that the verified
finishing weapon is the laser itself, with ETA at most 1.25 seconds, HP above
15%, a grounded mech and no urgent rotation. A gun-only short estimate cannot
enable a nonlethal laser charge. This narrow exception permits a charge while
retaining recovery movement; urgent and airborne recovery retain the veto.
Already-held charges remain noncancelable and are handled by Combat.

The two-second short-kill estimate is a prioritization window, not proof of survivability. Selective FinishSafety remains separately tested but its admission gate is not used by the aggressive root. A fixed pursuit lease and a complete burst-plus-exit budget remain deferred proposals; neither is implemented in aggressive-v1.

Do not cancel every resource just because proactive selection always finds a distant mech. Preserve safe loose-cube/weapon/healing detours while attacking at range when compatible. A real short kill or immediate close threat can preempt them; crate/NPC farming requires aim/dwell and loses priority in an active mech exchange. Keep current exposure, occupancy memory, vertical reach, capture-clock and upgrade-cap checks initially. Measure resource starvation before broadening farming thresholds.

After a kill, recompute threats before collecting the corpse. Useful nearby loot improves the next fight; an exposed corpse or nearly captured enemy drop can be a trap. Do not follow stale targets through cover or leave the future circle merely to preserve continuity. Anonymous projectile ownership still informs evasion; it no longer gates attacking an observed enemy.

## Selective integration expectations replaced

The former root integration tests encoded the old policy. They have now been
replaced with 44 aggressive integration checks, covering the following changes
while retaining physical/runtime assertions:

- Explicit policy test must require the aggressive selector.
- Quiet-close no-first-shot, quiet-distant no-chase, first-shrink-not-unlock, unrelated/missing-attacker/zone/NPC-damage/anonymous-projectile/own-hit permission tests: current visible usable enemies may be selected without those evidence sources. Test evidence independence and no fabricated absent target instead.
- Quiet-third-mech protection and quiet-mech gun/lightning collateral suppression: replace with correct first interceptor, lightning primary/chain, laser pierce and mortar/self-splash behavior. All current enemies can receive damage.
- Fixed finish deadlines, consumed evidence, external-fight-only and expired-evidence root assertions no longer define offense. Replace with productive continuation, current LOS/readiness rechecks, target loss, and recovery/rotation movement priority. Keep legacy module tests isolated if desired.
- Lowest-HP external-fight tests become short-kill/readiness/reachability ranking with no beam prerequisite. An unreachable weaker target must not starve a usable target.

Retain/adapt farming, missing-target, empty reload, high-ammo reload near threat, quiet healing, emergency rotation, energy reserve, observation immutability and held-laser tests. A held laser cannot be canceled: an escape/healing abort should preserve a deliberate actual-aim release. False trigger is not zero emission. Quiet-enemy protection is superseded; unsafe aim redirection remains a physical problem.

## Validation

1. Preserve submitted source/receipt; implement on a separate candidate and document the behavior changes.
2. Actual Bot scenarios: proactive first shot without evidence; usable healthy target despite no short ETA; verified approach beyond band; blocked route; short-kill ranking; distant-target loot detour; no partial reload during viable exchange; active recovery versus quiet regen; rotation without pursuit; no stale target; held-charge abort; multiple enemy interception/chain.
3. Updated complete tests, dense real-map full-Bot timing, official 300-observation checker in exact restricted Docker runtime. Require schema-valid timely actions. Timing proves compliance, not game strength.
4. Authorized private diagnostic with exact source snapshot: record first proactive attack, target availability, fire/readiness/reload intervals, approach progress, short opportunities, damage/kills, useful cube thresholds, HP loss, regen, escapes, zone damage, stalls and latency. Different random FFA runs are not controlled practice comparisons. Recorded observations establish decisions, not alternate kills.
5. Submit the exact validated commit within quota. Record its receipt/result separately from completed selective receipt `BB-AC10AB33` (2.69); compare official 48-match score with 4.75 and 6.0. Retain the organizer-selected best if lower. Report kills when available without calling them the official score.

First measure restored proactive pressure and pursuit with tested mechanics. Further spacing, farming, recovery or ranking experiments need concrete evidence, rather than combining many speculative parameters before measuring this policy reversal.
