# Pursuit orchestration plan

Written before implementation. This candidate starts at exact retained best `39b6d509af8e82b0ceb9e1c430dd964674d7488e` (official 4.75). The updated request is to move quickly toward the nearest enemy, use the greatest practical firepower, reload when no enemy is near, and heal at low health when no enemy is near. Target score remains 6.0. The official placement score and the requested aggressive behavior are separate evaluation criteria; kills alone are not the official score.

## Confirmed decisions

The user answered both choices before dependent implementation:

1. Rank living mechs and NPCs equally by current reported horizontal distance. Remove the old 60 m NPC discovery exclusion. Exact ties prefer the current target, then actor ID; HP and threat do not change priority.
2. Nearby enemy uses the current equipped weapons' geometric usable range, including the observed body/pitch envelope and current map-clear threat ray. Ignore cooldown, ammo, energy and current facing when deciding whether an enemy is nearby; those affect readiness rather than location. Final firing still requires the actual weapon solution.

The same definitions drive targeting, recovery, partial reload and telemetry. A reported occluded position may guide pursuit but does not alone qualify as nearby under the agreed map-clear rule. The protocol can retain reported actors, so map clearance is not a claim of fresh visual contact. Evaluate the documented maximum 27 other living actors with shared geometry results; retain NPCs' lower intrinsic tactical risk because equal target priority does not imply equal incoming damage. If a timing limit later requires incomplete assessment, expose it and conservatively veto quiet recovery/partial reload rather than claiming no nearby enemy.

## Baseline differences that require deliberate integration

The baseline selects only targets with current map line-of-fire and within its largest non-mortar weapon range, then ranks threat, woundedness, continuity and distance. That is not nearest-enemy pursuit beyond range. Its resource choice can override an already selected enemy. Its recovery state starts below 55% HP, or below 82% with two visible enemies, and can suppress fresh laser charging even against a nearby enemy. Its combat code partially reloads both when idle/unauthorized and when an invalid gun solution has three or fewer rounds. All four behaviors need explicit reconciliation with the updated request.

The historical aggressive candidate restored proactive targeting but retained weighted target ranking, long-range spacing and resource overrides. Its 4.63 official result does not prove a particular mechanic was responsible. Do not import that entire stack or its old selective permission rules. Preserve baseline geometry and combat correctness unless a separately reviewed change is necessary for this policy.

## Shared decision contract

Root should compute one decision for each current observation:

- `pursuit_target`: the nearest eligible current actor under the user-approved class priority; may be beyond firing range or temporarily occluded.
- `fire_target`: the selected current actor passed to final physical weapon checks, or none when no enemy is geometrically nearby. This is not a claim that a shot is valid. Keep the nearest target rather than switching to an unrelated easier shot; actual trigger decisions remain subject to each weapon's physical solution. Passing no fire target during distant/occluded pursuit permits the normal quiet ammunition top-up while retaining pursuit navigation and aim.
- `nearby_enemy`: the agreed distance/reach predicate evaluated independently of temporary weapon readiness. The chosen target is not the only actor relevant to this safety gate.
- `mode`: ROTATE, FIGHT/PURSUE, RECOVER, RESOURCE or SEARCH, with a concrete reason.
- `allow_fire`, `allow_partial_reload`, and `movement_goal`: derived from that same decision, not separately guessed by the combat and movement modules.

Eligibility requires a living hostile in the current observation, the selected enemy-class rule and usable observed position. Do not fabricate a firing target from memory. An unavailable immediate shot does not erase a valid pursuit target. Unreachable or invalid body-sized approach goals must be rejected or replanned by movement; proximity alone is not permission to force a route through terrain. Equal-distance ties can preserve the incumbent then use actor ID for deterministic behavior. Any wider target-switch hysteresis would be an additional policy choice, not literal nearest ordering.

Missing optional HP does not mean dead. An authoritative kill event for another mech slot 0–15 records that slot as eliminated for this match and excludes its retained listings from both pursuit and proximity; there are no battle-royale respawns. The bounded set resets with the Bot constructor. Do not infer NPC death from disappearance or unconfirmed damage; only explicit nonpositive HP excludes such a currently reported NPC.

## Arbitration

| Priority | Movement intent | Fire and reload |
|---|---|---|
| Urgent zone escape | Navigate into the future safe circle using body-sized verified movement; pursuit and resource detours cannot override it | Fire at a usable current target when compatible with escape. Avoid starting a movement-slowing charge that defeats needed escape. Empty-magazine reload remains permitted. |
| Enemy nearby | Pursue or fight the nearest eligible target, using the fire agent's useful weapon band and movement agent's collision/zone checks | Proactive fire with every simultaneously usable weapon. Low HP alone does not impose quiet-healing fire suppression. No partial-magazine reload merely because aim, LOS, cooldown or target readiness is temporarily poor. |
| Low HP, no enemy nearby | Seek a reachable protected position and permit regeneration before pursuing a distant enemy | Stop discretionary damage that resets regeneration and avoid new charges. Partial reload is permitted; empty-magazine reload remains permitted. |
| Current target, no healing need | Fast verified pursuit toward useful weapon reach, then fight without a loot detour | Fire whenever actual range, leading, aim slew and weapon readiness allow. Partial reload is allowed only if the shared nearby predicate is false. |
| No target and no healing need | Useful resource or in-zone search position | Existing safe resource behavior may run. No fabricated enemy target or hidden-mode assumption. |

Retain the baseline 55% recovery entry and 93% exit as HP hysteresis, gated by no nearby enemy. Keep the underlying healing need across an intervening nearby fight so it can resume when the enemy leaves. Remove the baseline “two enemies and HP below 82%” recovery trigger. When an enemy becomes nearby, recovery fire suppression ends immediately. Passive healing still requires the actual regeneration delay without dealing/taking damage, so far incoming fire may require seeking better cover rather than standing still.

## Firepower and reload details

“Highest firepower” means using the currently available, physically valid damage opportunities under shared aim, observed range, ammo, cooldown, charge, energy and collision rules. It does not mean blindly holding every trigger. Gun plus laser may fire together only when both solutions align; mortar cannot share an incompatible pitch; lightning follows its actual primary-target and energy rules. The fire agent defines the useful combined-weapon band for the movement agent. Do not change upgrade rankings or unrelated weapon mechanics in this candidate without a separate plan.

Both partial reload paths in baseline `Combat.plan` need the same explicit gate: the idle/unauthorized top-up and the invalid-solution/at-most-three-round top-up. Empty magazine reload is mechanically necessary even with an enemy nearby. A reload already in progress cannot be treated as canceled merely by sending `reload=False`.

A previously held laser has no cancel command. Entering recovery or urgent escape can release it even with a false trigger. Preserve deliberate actual-aim handling and report this emission correctly; do not redirect a forced release to an unrelated scan bearing.

Share the near-envelope helper's two-millisecond optional budget across actors, capped to preserve the rest of the full-policy allowance. A bounded mortar assessment may return unverified rather than false; treat that state as nearby for reload/healing protection and expose incomplete assessment in telemetry. Direct near checks reuse the already evaluated threat ray; final gun/laser/lightning/mortar firing retains its own actual muzzle/path checks.

## Resources during pursuit

A visible target must not lose pursuit priority to a better scalar resource score. During pursuit, permit pickup/take commands for useful items already within the official horizontal and vertical collection limits; do not replace the pursuit goal. A later implementation may allow pickups proven to add no detour to a verified route, but a mere small distance does not establish zero delay. Crate farming, an NPC farm distinct from the selected combat target, drop capture and corpse-loot detours wait until no current target or a separately authorized recovery need allows them.

An NPC selected by the equal-class nearest rule is a combat target, independent of the old optional-farm 55 m limit. No NPC farming-range experiment or drop-memory experiment is included. While any current pursuit target exists, do not call optional resource scoring; a quiet low-health bot with a distant target seeks recovery cover instead. With no target, existing resource scoring may still select useful healing cubes or a repair drop during recovery.

## Validation

Tests should exercise actual `Bot.act` arbitration, not just an isolated selector:

- Nearest current eligible enemy wins under the answered class rule; quiet proactive targets need no prior damage evidence. A current enemy beyond gun range still produces verified pursuit.
- Temporary reload, empty ammo and cooldown do not redefine “near.” Occlusion can make the shared map-clear predicate false; retain the reported target for pursuit and permit quiet reload/recovery under that agreed rule. Test live weapon range boundaries and bounded unknown mortar assessments.
- Nearby enemies at low HP permit useful firing and prevent elective healing; low HP with no nearby enemy suppresses damage and seeks recovery. A far enemy cannot indefinitely prevent the requested quiet healing unless the chosen near rule includes it.
- No partial reload near an enemy through either combat code path; empty-magazine reload always works. No enemy near permits a useful top-up.
- A pickup already within take range can be taken without changing pursuit direction; a nearby valuable cube, crate, drop or NPC farm cannot override nearest-enemy pursuit.
- Urgent-zone movement, body collision, failed routes, projectile avoidance, held-laser release and observation immutability remain enforced.
- Test dense current-actor cases and full-map runtime under the official limit. Run the complete baseline-derived suite and the restricted container checker before any official submission.

Private diagnostics should record target rank/distance, approach displacement, time in usable range, per-weapon readiness/fire/reload, actual damage, regeneration, cube pickups, zone damage and stalls. An observed decision or geometry replay is not a counterfactual kill; random private placement is not evidence of a controlled official score change.

## Bounded visibility revision, planned before implementation

The first integration passed 199 tests and completed nearby assessments in 625 recorded one-second samples. A separate real-map dense 27-actor test exposed the cost of checking every world ray: typical threat batches took 24–26 ms, and an outlier reached 95.85 ms. Those measurements describe the unbounded-ray revision, not the bounded version below. A fixed actor-count cap alone does not bound wall-clock work.

Keep all 27 cheap current-actor records and exact nearest ordering. In actual `Bot.act`, world visibility work may start only before six milliseconds from the beginning of the decision; check the deadline before each center and upper-body ray. Preserve explicit clear, blocked and unknown status. An unchecked actor is never dropped from pursuit, and unknown visibility never becomes verified clear for movement or firing. Standalone threat evaluation without a deadline retains complete checking for focused tests.

For nearby assessment, cheaply reject only actors definitely outside every held weapon's conservative range envelope. A mortar may remain possible because a narrow horizontal bound would be unsound across elevations. An unknown potentially-in-range actor conservatively blocks quiet healing and partial reload and sets incomplete-assessment telemetry. A later verified nearby actor can resolve the Boolean question positively. Actual firing still uses Combat's full muzzle/trajectory checks. Preserve full intrinsic tactical danger for unknown actors; do not apply the blocked-ray reduction or divide already-unattenuated risk by that reduction.

Instrument total threat-phase time, world-ray count, maximum individual ray time and unknown-record count. The deadline is cooperative: a single already-started map ray cannot be interrupted. Tests must prove checks occur before both center and top rays, all actor records survive exhaustion, unknown nearby actors block quiet actions, definitely out-of-range unknowns do not, and default standalone semantics remain complete. Rerun affected dense timing before claiming this revision meets the runtime limit.
