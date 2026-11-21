# Movement-only follow-up: restore useful gun separation

Status: the narrow helper change is implemented in this candidate. The original pursuit-v1 remains unchanged. This plan was written before implementation and follows the completed pursuit private run and the official pursuit-v1 result of 4.21; neither result predicts this candidate's score.

## Supported problem

The final private duel provides a specific case: own gun only, zero cubes, against a one-cube gun-and-laser mech, at 36.83–47.01 m for 10.7 s. The nearest-target selection was correct. The bot kept moving and had at least 71.5 energy, but received 1216.8 observed damage while dealing 450 to that opponent.

For a clear target, the movement helper currently returns `max(physical_floor, min(anchor, current_distance))`. Consequently, the gun's 70 m anchor vanished from all 107 decisions in this duel: preferred distance was exactly current distance. The distance-restoration term in the existing radial controller was therefore zero. Median observed target radial velocity was +5.98 m/s (moving away from us); median own radial velocity was +5.84 m/s (following toward it). The policy often followed the opponent's withdrawal and maintained approximately 41 m rather than allowing separation to grow. This is an intentional consequence of the clamp, not a pathfinding failure.

Restoring an anchor has a concrete effect without changing targets. At a representative 41 m gap with an opponent moving away at 6 m/s, the existing radial formula changes from `6 / 11.7 = +0.51` to `(6 + 0.6 * (41 − 70)) / 11.7 = −0.97`. Its existing spacing-boost preference then applies. The gun can continue firing while movement creates separation; firing remains subject to the unchanged Combat checks.

## Narrow candidate

For the first isolated comparison, restore the existing 70 m gun anchor for a clear **mech** target when exactly one weapon is held and it is a gun, in either slot. Keep the physical body/pitch floor and live range cap. This covers the observed gun-versus-gun-and-laser case without requiring an enemy-weapon classification branch and also gives a consistent gun spacing rule against other mechs. Any occupied second slot, including another gun or an empty/cooling secondary, retains the previous spacing behavior.

Do not change the 35 m NPC anchor, occluded-target approach, funded lightning band, other loadout anchors, target selection, incoming hazard costs, collision checks, boost reserve, reload permission, or quiet-only recovery. In particular:

- Far targets still receive the same fast approach toward the same gun anchor.
- A closer clear mech causes separation while the exact nearest target remains selected and firing remains enabled.
- Unknown or blocked LOS still uses the existing physical-floor approach so spacing does not prevent acquiring a shot.
- Urgent zone routing continues to override ordinary engagement movement.
- Terrain, incoming projectiles, beams and other actors' exposure remain tactical constraints; there is no forced straight-line retreat or forced boost.

The 70 m distance is the existing engineering parameter, not a measured optimal distance. Restricting the first change to gun-only versus mechs avoids simultaneously retuning every loadout. A gun-and-lightning loadout should keep its shorter funded joint range because a 70 m floor would remove lightning usefulness.

## Current velocity, boost and geometry evidence

`python work/probe_pursuit_separation.py` evaluates all 107 recorded states against mech 10. Each probe retains the current observed own velocity, energy, actual map and threats. It reconstructs the same strafe side from the recorded goal, changes only the desired distance to 70 m, runs ordinary map navigation and the unchanged tactical chooser, and compares 0.6 s held-action trajectories. The previous recorded movement seeds the chooser's continuity term. This is a shadow decision at each real observation, not a replay with counterfactual feedback.

| Measurement | Recorded action | Restored gun anchor |
|---|---:|---:|
| Commands directed outward from the target | 18/107 | 96/107 |
| Boost commands | 29/107 | 46/107 |
| Returned-action 0.6 s trajectories passing geometry | 107/107 | 107/107 |
| Neutral geometry fallback | 0/107 | 2/107 |
| Median conditional 0.6 s change in gap, 101 common future windows | +0.41 m | +7.41 m |

Across the 101 paired windows, median extra separation was 7.16 m; mean was 6.19 m. Six final states lack a recorded target position 0.6 s later and are omitted from that comparison. The minimum proposed trajectory-end energy was 61.3. Planner median time was 12.20 ms and maximum 12.85 ms in this host probe, within its existing local request budget; this is not a full-policy/container timing result.

There was enough current energy and velocity authority to create short-horizon separation in many of these states. At the lowest observed duel energy, 71.5, an ideal uninterrupted 17-energy/s boost could spend about 2.15 s before reaching 35, ignoring regeneration and decision quantization. This is a capacity bound, not a recommendation to force that burst. The opponent's maximum measured radial closing speed was 19.46 m/s, almost our 19.5 m/s boost speed, so separation is not guaranteed against sustained direct pursuit. Its measured radial closing speed exceeded walk speed in only 2/107 states; most states show it moving away.

Straight-away boosted trajectories failed geometry in 12 states from 19.9–21.0 s near the building corner. This rules out a simple unconditional backward boost. Normal navigation/tactical selection produced a safe returned trajectory in every probe, including neutral braking at 20.1 and 20.3 s after all six permitted geometry candidates were rejected. Those two fallback states are a required continuation test before integration, not evidence of a solved long-term route.

## Existing dodge evidence and tradeoff

The earlier isolated gun benchmark used the documented 20 Hz vector acceleration, 10 Hz decisions, 252 m/s shots and an unscaled 2.5 m body, without scenery, spread or a live opponent. At 70 m it avoided 16/34 modeled aimed shots with 15 energy and 22/34 with 100 energy; at 120 m it avoided 34/34 in both energy conditions. This supports the mechanism that extra distance can provide more response time, but does not establish 70 m as safe, does not measure this final duel at approximately 41 m, and does not predict match outcomes. The separate recorded-target velocity study also found larger motion-prediction errors at longer gun distances, so increased spacing can reduce our own hit probability.

The proposal deliberately retains 70 m instead of returning to the older 120 m default: the user requested fast pursuit and high firepower, and this iteration should test removal of the close-distance ratchet before changing the anchor itself. It preserves active combat and a nearest-target chase when the target exceeds the anchor; it does not flee to heal.

## Validation before implementation/submission

1. Unit boundaries: close clear gun-only mech restores the anchor; far target is unchanged; physical floor wins when larger; live gun range still caps the anchor; NPC, occluded and other-loadout behavior stays unchanged.
2. Fixed-observation Bot checks: exact nearest target, fire/aim/reload permissions and recovery choice remain unchanged while only engagement movement differs. Cover a closer gun-and-laser mech and a fleeing farther mech.
3. Repeated-controller mechanics around the 20.1/20.3 s corner with actual acceleration and every swept body checked; verify that any transient neutral choice does not turn into sustained deadlock. Do not claim long-term escape from the present one-action probes.
4. Existing gun spacing/zone/projectile tests, full-policy real-map deadline checks, restricted container check, then an isolated private/official comparison. Keep the previous candidate available.

## Implementation and focused validation

The runtime difference is two executable lines in `pursuit_distance`: a clear, explicitly mech target with exactly one held gun returns the already-computed anchor/floor maximum. No Bot, Combat, map or trajectory-planner implementation changed. The original closer-target test was updated for this scoped exception; all other loadouts retain the previous result.

Ten new tests passed, including actual Bot checks for unchanged nearest selection, firing/aim/reload fields, quiet-only healing permissions, continued fast approach when far, and safe body/pitch/range bounds. The existing 24 pursuit movement tests and 39 pursuit orchestration tests also passed. An independent fire/physics review found no material defect.

Two additional five-second controller continuations started from the problematic 20.1 and 20.3 s states. Each applied only the next 0.1 s of the chosen trajectory, checked every applied sweep, then replanned from the resulting position, velocity and energy. Recorded other-actor/hazard inputs remained exogenous; this is not a combat simulator or an online-delay reproduction.

| Start | Applied decisions | Rejected applied sweeps | Longest neutral period | Path / net displacement | End distance to mech 10 | Minimum energy |
|---|---:|---:|---:|---:|---:|---:|
| 20.1 s | 50 | 0 | 0.1 s | 56.65 / 2.38 m | 69.49 m | 62.0 |
| 20.3 s | 50 | 0 | 0.2 s | 56.31 / 12.73 m | 65.55 m | 60.3 |

The first continuation selected mech 8 temporarily when it became nearer, so its small net displacement includes a moving return path; it is not a claim of a large escape from the initial corner. Neither continuation remained trapped in the initial neutral fallback. Maximum full-policy host call times were 30.53 and 30.65 ms. Full-suite, container and live comparison checks remain separate. Reproduction artifacts are `work/probe_spacing_continuation.py` and `work/pursuit-spacing-continuation.json`.

Frozen tactical SHA256: `cdbf955645840bc3c36d49861410172225d7962d35dcc9b53548526a47278491`.

## Limits

The 0.6 s comparison assumes the selected action remains held, while the real controller replans every 0.1 s. It uses the recorded opponent position at the horizon; another policy would change that opponent's future behavior and observed projectiles. It does not reproduce the private run's approximately 0.3–0.4 s command-to-observation delay, Gaussian gun spread, future aiming decisions or damage. The result is evidence that available movement can create separation under stated conditions, not a counterfactual win, hit-rate estimate or guarantee against two weapons.
