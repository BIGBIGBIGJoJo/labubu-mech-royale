# Fast nearest-enemy pursuit: movement plan

This plan precedes implementation on exact retained-best baseline `39b6d50`. The user has now specified equal priority for mechs and NPCs, selection of the nearest living listed enemy, and “nearby” based on usable held-weapon reach. Movement consumes that selected target and the orchestrator's shared nearby predicate; it does not select another target or redefine nearby from its preferred engagement distance.

The intended behavior is rapid routed approach into a useful close firing band, then tracking and strafing while combat uses the available weapons. Urgent zone movement, verified body collision constraints, incoming projectiles and aimed beams remain authoritative. Reload/recovery arbitration belongs to the orchestrator; a low-HP flag must not silently restore the old distant standoff while an enemy satisfies the user's nearby definition.

## Why baseline movement needs a specific change

The baseline approaches ordinary mech targets to 120 m with a gun or 150 m with a laser. Those are defensive spacing preferences. They can make the bot back away from the nearest enemy even when the new objective calls for a closer engagement. NPC spacing is 35 m; a conditional lightning branch uses 33/38 m.

There is also a measured boost-selection obstacle. Ordinary tactical boost costs 6.5 score units, while route progress is worth 1.3 per metre over the 0.6 s horizon. At base speeds, even instantaneous acceleration could gain at most `(19.5−11.7)*0.6*1.3 = 6.084` units. Thus boost cannot win on straight approach progress alone. The exact baseline rollout gives:

| Initial forward speed | Walk progress over 0.6 s | Boost progress | Weighted progress difference |
|---|---:|---:|---:|
| 0 m/s | 6.1425 m | 8.92125 m | 3.6124 |
| 11.7 m/s | 7.0200 m | 11.35875 m | 5.6404 |
| 19.5 m/s | 7.36125 m | 11.7000 m | 5.6404 |

In controlled calls to the unchanged baseline TacticalPlanner, all three cases chose straight walking. Changing only the existing boost preference to 1.8 made all three choose straight boost, with the same geometry and hazard checks. This is controller-mechanics evidence, not a match result or a guaranteed pursuit-speed gain.

## Interface and ownership

The movement implementation exports one pure helper from `tactical.py`:

```python
pursuit_distance(config, me, target, stats, *, line_clear=True) -> float
```

It returns a preferred **horizontal** distance. `stats` is the existing correctly cube-scaled self-stat dictionary. The helper reads at most the two held weapons and target body dimensions, performs no map queries, and does not mutate observations. It is a preference calculation; Combat remains the authority for current range, pitch, barrel geometry, target intersection, obstruction and firing readiness. The caller passes the selected threat's existing map line-of-fire result as `line_clear`.

For an occluded listed target, return the geometric minimum below rather than the ordinary 70/80 m preference: the bot must not retreat from a hidden target merely because it is inside a gun spacing band. For a clear target already closer than the ordinary anchor, cap the preference at the current horizontal distance, then apply the geometric minimum. This preserves close contact instead of deliberately restoring distant spacing. It does not guarantee that a straight standoff point will reveal every target behind a wall; existing map routing and collision checks still govern movement.

The orchestrator keeps the existing target-radial-velocity compensation and strafe equation, replacing its old 120/150/NPC/lightning distance overrides with this helper. When `distance > preferred + 8` and the resulting radial demand is positive, it passes the new pursuit option to movement. The 8 m boundary is a design tolerance that limits boost overshoot near the engagement band. A map route may initially move away from the enemy to go around a wall; progress follows that checked route, not a forced straight vector through the obstacle.

`TacticalPlanner.choose` gains backward-compatible optional parameters:

```python
choose(..., pursuit=False, shot_energy=0.0, ...)
```

`pursuit=True` lowers the boost preference cost from 6.5 to the existing 1.8 value. It does not set `urgent`, change damage weights, disable braking, increase candidate counts, or bypass geometry. `shot_energy` is the sum of live lightning costs for the triggers scheduled in the current action. No own energy cost is invented for mortar, gun or laser.

The orchestrator owns `bot.py`; this implementation owns the pure distance helper, tactical options and focused movement tests. No new runtime module or Docker copy entry is necessary. Global target coverage, nearby range and firing are handled by the other agents.

## Proposed close engagement distances

These are explicit engineering parameters for the new aggressive objective, not inferred user thresholds, proven optima or guaranteed safe distances. Nearby uses full usable weapon reach independently.

| Current useful loadout/target | Preferred distance before geometric floors |
|---|---:|
| NPC with ordinary ranged weapons | 35 m |
| Mech with gun and no laser/mortar | 70 m |
| Mech with laser, or mortar alongside the gun | 80 m |
| Lightning can fund its next trigger plus Combat's ordinary 8-energy reserve | Reduce the above preference to at most its live range minus 6 m |

The lightning margin is conservative center-distance preference, not a claim about the engine's exact target-surface reach. NPC preference stays at 35 m if that is already shorter. If energy cannot pay the next lightning trigger **and** Combat's ordinary 8-energy reserve, use the ranged preference. This matches the existing ordinary firing gate (11 energy for a base 3-energy shot), rather than treating an unfireable arc as available firepower. This helper is used in nonurgent pursuit; urgent movement has its separate policy. Upgraded lightning reach and shot cost come from live weapon stats. Current cooldown or a temporary empty gun magazine does not rewrite the orchestrator's nearby definition.

Raise the preferred distance when required by the self/target horizontal body radii plus a 2 m separation margin. For held direct pitched weapons, also include a conservative distance implied by current muzzle height, target body interior and the configured pitch limits. Very large self bodies against low NPCs can require extra spacing even when lightning is in range. For a held mortar, include the larger of the existing 15 m minimum and `splash_radius + scaled_self_radius + 3`; its actual arc and self-blast check can still reject a shot. A movement distance never certifies that both weapons can hit simultaneously.

This shortens the earlier defensive bands intentionally. An existing isolated base-body dodge benchmark avoided only 16–22 of 34 aimed gun shots at 70 m, versus 34/34 at 120 m. While charging a laser, the same model avoided 12–14/34 at 70 m and 34/34 at 150 m. It omitted scenery, spread, opponent reactions and input delay and is not a match prediction. The closer choices sacrifice reaction time to pursue the requested close, high-output engagements. They need actual-game evaluation; no survival improvement is claimed.

The recorded gun-forecast audit independently showed that shorter flight improves motion prediction: the first velocity upgrade reduced median horizontal error from 1.03 to 0.66 m in a highly selected 332-case sample, but conditional body contacts rose only 3–5% across sampling phases. This supports the physical relevance of flight time without proving that shorter spacing will improve score.

## Energy, acceleration and geometry

The existing 20 Hz vector acceleration, 0.6 s rollout, grounded boost speed, support/ledge geometry, laser movement multiplier, projectile sweeps and beam/zone costs are retained. Planned laser charging must continue to reach the movement observation so boost cannot pretend to provide an uncharged speed while the laser halves movement.

Boost is an evaluated option, never an unconditional command. Before allowing it, subtract scheduled lightning energy and the next held action's boost drain from current observed energy. Preserve a 35-energy ordinary reserve and the existing 12-energy urgent-zone reserve. These are existing policy reserves, not new claims about optimal aggression. Use the live drain and actual decision interval, and carry the shot deduction into rollout energy so ranking and eligibility agree. Falling, walls, braking and an incoming projectile can still make walking or another direction preferable.

Long pursuits can still exhibit the baseline's repeated floor-35 energy cycling. Earlier isolated accounting favored a 35→65 hysteresis latch for sustainable duty, and private traces showed repeated regeneration deadtime; those later-controller changes are not in this exact baseline. Do not silently port that larger mechanism into this first nearest-pursuit candidate. Measure boost duty and exhausted-energy behavior after the explicit pursuit-preference change, then decide separately whether a latch is needed. No energy model is promoted to a score claim.

No purposeful flight, wall tolerance relaxation, target-position extrapolation, new fine-route search or blind jump is added here. The existing map planner handles obstacles and the tactical sweep rejects unsafe paths. Current route limitations remain possible; a clear endpoint alone is not proof of an escape or eventual arrival. A newer nearer target or loss of the listed target is handled by the orchestrator, without movement retaining a secret pursuit target.

## Validation and time budget

Keep the current 32 ms internal policy deadline, 50 ms external limit, at most 14 ms tactical request and six checked movement candidates. This change adds only constant-time range/energy arithmetic and a boost preference option. It must not add a map ray for every actor; the orchestrator/fire shared nearby logic reuses their current geometry result.

Focused tests must demonstrate:

- A calm selected target outside the close band produces positive routed progress and makes boost useful at high energy; the non-pursuit default keeps baseline behavior.
- Scheduled lightning plus the next boost action cannot spend below the relevant reserve; unfunded lightning does not create a false close-weapon preference.
- Gun, laser, NPC and upgraded-lightning preferences are correct and independent of full-range nearby semantics; large body, low-target pitch and mortar safety floors remain finite and conservative.
- Charging uses the live movement multiplier, and pursuit does not override a wall, actual projectile/aimed beam, braking trajectory or urgent zone route.
- Expired deadlines retain a bounded fallback; no extra geometry candidate or scan is introduced.
- Real-map timing exercises the actual pursuit option and the complete integrated policy, including the newly requested maximum 27 actor records. Full-actor visibility work is measured separately; a helper's cheap cost is not evidence that the complete policy meets 50 ms.

Record target distance, preferred band, positive approach time, boost permission/energy reserve, observed progress, fired weapons and actual damage separately. Private network input delay means commanded motion is not immediate physical motion. The official score is the final comparison; a faster short trajectory or one private placement cannot establish that the new strategy reaches the target score.

## Implementation checkpoint

The movement helper and pursuit/energy options are implemented. All 24 focused movement tests and 13 existing tactical tests pass. The lightning availability gate matches Combat's ordinary shot cost plus 8 energy, including live-cost boundary tests. Movement source is frozen for integration.

On the real-map recorded opening, all52 frames requested and selected pursuit boost, every nearby assessment completed, and full-policy time was at most10.20 ms. A maximum27-actor host timing case exposed a separate unbounded visibility phase in the integrated Bot: typical threat-ray work alone took24–26 ms, all200 dense nearby scans exhausted their earlier deadline, and5/200 full calls exceeded50 ms. The orchestrator therefore bounds sight-line work while retaining all actor records and explicitly marking untested visibility unknown. Tactical handling conservatively treats unknown exposure as potentially visible and includes an unknown charging actor's possible aimed beam. Known blocked sight retains its existing discount; exact future-position world checks still resolve exposure when budget permits. Two focused tests cover these distinctions, bringing the movement suite to24. No candidate cap, hazard weight or movement threshold changes accompany this correction. Identical integrated timing must be repeated on the final hashes before validation is claimed.

That identical affected benchmark has now passed on the bounded-visibility revision: 52 recorded opening calls and 200 dense27-actor calls all stayed below50 ms. Opening maximum was9.84 ms; dense maximum was24.28 ms. Every call completed the nearby decision and selected pursuit boost, and every dense call retained all27 records in exact nearest order. Dense cases verified4–7 sight lines and marked the remaining20–23 unknown; a complete positive nearby decision does not mean every sight line was resolved. Maximum measured threat phase was7.65 ms and individual threat ray2.11 ms, illustrating that the6 ms between-ray guard is cooperative. These are host measurements with an initialized real map; restricted-container and live validation remain the root agent's separate responsibility. Tactical source SHA256 is `a40aa5d643eeb84b70909758562fb253f1498fd7ad5dc4881e330aaa76bbec50`.
