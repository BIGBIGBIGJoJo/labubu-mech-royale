# Historical experiment document

This file records earlier experimental branches. The current controlled
experiment is described in PROGRAM_DESIGN.md and FIRST_MAGAZINE_PLAN.md. Its runtime
does not include all mechanisms proposed or tested below.

# Aggressive movement plan

The user now prioritizes greed, aggression and kills, with an official-score target of 6.0. The previous quiet-mech and no-chase restrictions no longer apply. This plan preceded implementation. Aggressive-v1 now restores positive radial approach with existing weapon bands and includes the separately validated recovery escape. Current validation is recorded in VALIDATION.md.

## First candidate: restore pursuit without changing every physical parameter

The blanket `radial = min(0, radial)` clamp has been removed. The controller combines target radial velocity with range error:

`radial = clamp((target_radial_velocity + .6 * (distance - preferred)) / walk_speed, -1, 1)`

For an actively selected target, positive radial motion should now approach its useful weapon band. Negative radial motion still maintains spacing from a closing target. Keep the existing strafe component and verified map navigation/tactical trajectory selection. An unselected high-risk actor can influence avoidance but must not silently replace the pursuit target.

Keep the current 120 m gun and 150 m laser preferences for this first aggressive comparison. Restoring approach and attack admission is already a major behavior change. Shorter bands can increase offensive accuracy, but should be tested separately rather than coupled to the policy reversal.

Do not assume that positive high-level navigation produces approach: the local controller also prices inferred exposure. Add a regression where an otherwise viable distant target produces positive routed progress with no actual incoming projectile, and another where a real projectile/beam still changes the selected trajectory. If the first fails, investigate that exact score decomposition before changing tactical weights. The proven urgent-rotation weighting stays untouched.

## Orchestrator contract

Use one current observed target and an explicit movement intent. The following
record is a design sketch, not a runtime API. The current root uses `state`,
`mode`, `goal` and `spacing_target`; it does not implement `commit_until` or a
fixed pursuit lease. With no usable firing target it can pursue a current LOS
mech while Combat withholds unavailable shots.

```python
intent = {
    "mode": "PURSUE",       # PURSUE | FIGHT | EXIT | ROTATE | LOOT
    "target": actor,        # current observation, never an invented hidden actor
    "preferred_range": 120.0,
    "shot_ready_in": None,  # separate from whether pursuing is useful
    "short_finish_eta": None,
    "commit_until": None,   # simulation time, fixed for a burst episode
    "resource_detour": None,
}
```

When the selector has no usable firing target, the root can choose the highest-risk current LOS mech as a separate `spacing_target` for pursuit, including beyond current weapon range. This reference is explicitly logged and does not replace an existing selected firing target. Combat withholds shots until its actual range, aim, intercept, obstruction and readiness checks pass. No hidden or remembered actor becomes a pursuit target.

Movement uses the root's goal and returns the final direction and optional boost; route status and tactical diagnostics are logged separately. It does not independently change the firing scheduler. The root expresses this contract using existing fields rather than a new intent-record API.

## Weapon bands and favorable entry

| Loadout or situation | Initial movement behavior | Evidence and limits |
|---|---|---|
| Gun with no committed short-range weapon | Approach toward 120 m, then strafe while tracking radial velocity | Existing isolated base-body benchmark avoided 34/34 aimed gunshots at120 m, versus16–22/34 at70 m. This is not a match win rate. |
| Gun + laser | Approach toward150 m; account for actual charge movement multiplier | At70 m while charging, that benchmark avoided12–14/34 shots; at150 m,34/34. It omitted scenery, spread, opponents and input delay, and did not validate large cube-scaled bodies. |
| Gun + lightning | Use existing33/38 m committed bands only when `lightning_commit` is satisfied; otherwise retain gun spacing | Existing gate requires one visible opponent, energy>=55, adequate effective HP, no opponent mortar, and no imminent opponent repair. Removing the radial clamp finally allows that existing favorable entry to occur. |
| Weak target with a validated short kill | Prioritize its damage opportunity while using ordinary collision/zone-aware approach | The estimate checks weapon readiness/turning, range, ammunition and actual target hit path; it is not a complete burst-plus-exit safety budget. `finish_eta=None` means no proven short finish, not no offensive opportunity. |
| Mortar available | Maintain useful separation and lead the route through clear firing angles | The verified arc solver and self-blast checks remain authoritative. Mortar victim drain is not firing energy. Do not rush a mortar opponent into point-blank trades merely because its HP is low. |

Initial 120/150 distances are preferred points rather than safe-distance guarantees. Enemy lightning upgrades, own body growth, multiple threats and geometry can require more room. Use observed weapon stats when available; do not hardcode upgraded reach from a base value. Combat's actual hit geometry determines lightning reach rather than an independently invented centre/surface conversion.

Potential later experiment: gun80–110 m and laser110–140 m when healthy against a target that cannot punish the entry. Those are **unvalidated strategy parameters**, not recommended first-candidate changes. Repeat the projectile/charge benchmark at0,8 and23 cubes, then inspect observed hit damage and return damage before adopting them.

Possible later refinement, not active in aggressive-v1: anchor each burst's target,
start position and expiry, and evaluate a complete burst-plus-exit energy budget.
Current behavior instead rechecks observations, range, route and zone every
decision and retains existing energy limits; it does not prove a full exit budget.

## Greedy economy that supports kills

Target existence alone must not cancel every loose pickup. While pursuing a distant actor, keep short cube/weapon detours that preserve the route to a useful firing position. A near-complete kill outranks a crate; an unshootable distant target does not automatically outrank an uncontested cube next to the route. Root should compare expected time to collect, enter range, and deliver the next useful burst.

Prioritize early cubes while their HP/damage gains help fights, but account for uncapped body growth. The configured HP/damage cube bonuses cap at10; optional cubes above that still enlarge collision dimensions. Do not treat indefinite cube farming as unlimited combat scaling. Revalidate low bridges and cover clearance immediately after collection.

Use observed offer effects to compare weapon upgrades: immediate damage/rate and useful range, sustainable magazine/reload throughput, laser charge time, lightning efficiency/range, and servos that improve engagement uptime. Preserve emergency HP upgrades when they enable survival through the next engagement. Existing fixed upgrade ranking is a baseline; changing all upgrade weights should be a separate tested step, not an implicit consequence of aggression.

Keep a usable gun while obtaining a complementary weapon. Attack exposed NPCs/crates when no useful mech engagement is available, but avoid farming that occupies aim/reload while a reachable kill window exists. A contestable supply drop is a combat objective, not free healing; compare arrival and capture times against visible enemies and future-zone slack.

## Avoid expensive traps while remaining aggressive

- **Zone:** urgent rotation remains the first movement priority and overrides pursuit using the observed future-circle test. A complete routed arrival-plus-burst-plus-exit calculation remains deferred. The previously diagnosed fatal orbit traveled260 m with15 m net progress; restoring aggression must not undo its correction.
- **Geometry:** endpoint clearance is not route reachability. Keep `direct/ready/searching/unreachable` truthful, abandon exhausted or nonprogressing routes, and preserve failed-goal cooldowns. The eight-cube bridge regression remains mandatory: height12.6 m cannot pass under approximately11.46 m clearance.
- **Mortar/beam:** actual projectile sweeps, aimed beam exposure, self-splash, collision and zone costs keep their full existing treatment. Greedy offense should relax only a reviewed strategy preference, never pretend a known projectile is harmless.
- **Recovery:** regeneration is useful when it can actually start. Do not sacrifice an immediately feasible kill solely because HP crosses a generic recovery threshold; root should explicitly arbitrate the kill versus an exit. When retreating, the new recently-hurt near-goal fallback prevents two demonstrated exposed holds without abandoning true cover or rotation.
- **Mobility:** do not add purposeful roof flight in the first candidate. Existing acceleration, charge slowdown, concussion, ledge and ground-body handling are better understood. If roof access later becomes necessary, require an ascent/landing/energy model and a measurable firing advantage.
- **Energy:** keep the35→65 boost latch and existing physical emergency overrides. Pursuit makes boost an option, not a forced command. A short kill can justify a separately budgeted burst, but changing the ordinary reserve is not part of this movement restoration.

The neutral-fallback diagnostic and fractional-speed trajectory candidate are
documented separately in [NAVIGATION_RECOVERY_PLAN.md](NAVIGATION_RECOVERY_PLAN.md)
and [TACTICAL_RECOVERY_PLAN.md](TACTICAL_RECOVERY_PLAN.md). The root diagnostic
does not force movement or jump. The tactical candidate retains complete local
sweep and hazard checks; global connectivity remains a separate investigation.

## Validation and compute constraints

Keep the 32 ms internal policy deadline beneath the 50 ms official limit; the tactical selector requests at most 14 ms. The earlier selective recovery audit found target-selection work consuming more than 20 ms before movement. Aggressive-v1 instead gives target scoring a cooperative six-millisecond limit, bounds expensive geometry, and retains a validated fallback rather than evaluating long arcs for every visible mech. These are work budgets, not guarantees that an individual geometry call cannot overrun; full-policy timing remains necessary.

Required behavioral checks: proactive approach to a quiet selected mech; a pursuit target beyond immediate weapon range; closing-target spacing; no endless radial oscillation across the desired band; actual incoming shot avoidance; lightning entry with readiness/HP/energy versus mortar/multiple-threat rejection; cube-scaled blocked bridge; loss of target/route invalidation; urgent zone preemption; greedy nearby pickup during a distant pursuit; imminent kill outranking farming; and recovery continuing a feasible burst while preserving a real repair window when no useful damage exists.

Log positive-radial pursuit time, in-band uptime, distance traveled versus displacement, target churn, observed mech hits/kills, attempted-but-unusable shots, resource gains, boost phase/reserve, route failures and outside-zone time. Separate commands from applied physics in private traces: the latest run again showed approximately0.3 s online input delay. Official local scoring is the decisive comparison; private placement and single static trajectory tests are diagnostic only.

The first implementation restores proactive pursuit with established physical parameters; measurements now identify concrete remaining bottlenecks. The completed selective receipt BB-AC10AB33 scored 2.69 and must not be attributed to the new aggressive policy. Historical best remains 4.75.
