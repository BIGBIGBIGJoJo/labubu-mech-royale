# First-magazine priority experiment

Plan written before implementation; the narrow change is now implemented and locally tested. Start from the exact retained best entry, `39b6d509af8e82b0ceb9e1c430dd964674d7488e` (official score 4.75). The goal remains 6.0 with greedy, aggressive kill-oriented play. Later aggressive entries scored 4.63 and 4.60; neither replaces the best entry. This experiment changes only upgrade choice, so it does not combine their routing, targeting, or recovery changes with the upgrade test.

## Single change

Raise the first `gun_mag` choice from rank 73 to **90** when a gun is currently held. Detect a prior drum from either the observed `gun_mag` upgrade history or an actual gun magazine larger than the configured base magazine. Do not hard-code a 12-round base.

Keep the second drum at 73 and every other rank unchanged. Nanites remain 95 before the existing final-zone adjustment. The existing low-HP plating adjustment remains 78 + 17 = 95; its late-zone adjustment also remains unchanged. Existing ties continue to follow offer order. Do not alter firing, reload commands, movement, resource goals, or combat thresholds.

## Conditional weapon value

The official configuration supplies damage 45, cooldown 0.24 s, magazine 12 and reload 2.4 s. Each drum adds eight rounds and multiplies reload duration by 0.8, with a two-stack maximum. The protocol explicitly states that held gun fire maintains its configured rate. Recorded ammo/cooldown/reload transitions show reload beginning while the final shot's cooldown is still positive: those waits overlap.

For uninterrupted fire from a loaded weapon, the continuous-time first-shot-to-next-magazine-first-shot cycle is `(mag - 1) * cooldown + reload`. The 20 Hz physics boundary, aim and action timing can add delays; this model does not claim all shots hit.

| Drum stacks | Magazine | Reload | Cycle | Nominal damage per second | Marginal throughput gain |
|---|---:|---:|---:|---:|---:|
| 0 | 12 | 2.400 s | 5.040 s | 107.14 | — |
| 1 | 20 | 1.920 s | 6.480 s | 138.89 | 29.63% |
| 2 | 28 | 1.536 s | 8.016 s | 157.19 | 13.17% |

Cube damage scaling multiplies all three rates equally. These are potential firing throughput, not observed DPS. Short exchanges that need at most 12 rounds gain no loaded-magazine firing speed or damage from the first drum. If the same target requires 13–20 successful rounds, first-drum shot availability avoids one 2.16 s interruption; this is a conditional firing/TTK difference, before equal projectile flight time and any misses. The upgrade does not instantly grant eight loaded rounds: recorded applications preserve current ammo until a reload. An already-running reload also retains its observed remaining duration.

The first armor stack's 8% weapon-damage reduction gives about 8.70% more effective HP against those hits; it does not reduce zone damage. Plating gives 15% more max HP. Neither is directly interchangeable with nominal DPS: armor can prevent a death, speed can change hit rate and escape, and the gun may lack a safe firing solution. The experiment measures the tradeoff instead of treating the throughput ratio as a proof of superiority.

## Recorded offer and use audit

Eighteen private diagnostics contained 41 distinct upgrade offers, with identical gun and upgrade configuration. Drum appeared in eleven offers: ten first-stack opportunities and one second-stack opportunity. The first drum was selected four times and passed over for servos three times, armor once, plating once, and nanites once. The second drum was selected once. These are different random matches and policy revisions, not a controlled score comparison.

The three aggressive diagnostics each offered the first drum early:

| Diagnostic | Offer time | Choices | Actual choice |
|---|---:|---|---|
| Earlier pre-fix aggressive | 18.6 s | armor, drum, servos | servos |
| Corrected first aggressive | 3.5 s | jets, drum, armor | armor |
| Later route-correction aggressive | 4.0 s | nanites, drum, armor | nanites |

In the corrected first aggressive diagnostic, the gun dealt 4,429.76 of 6,299.32 recorded damage. Its reload state occupied about 36.0 seconds, including 18.4 seconds with a selected visible mech. Ten reload episodes began empty; five were partial reloads. At 60.4–61.9 s, selected mech 5 had 76.85 HP, later 30.05 HP, while the gun had zero ammo and 2.1–0.6 seconds of reload remaining. Fourteen captured states permit a gun trigger in a gun-only ready-weapon geometry probe that resets ammo, reload and cooldown. This is evidence that gun downtime can matter, not that choosing a drum would have preserved the same trajectory or guaranteed a kill.

In the later diagnostic, the gun dealt 4,003.24 of 4,279.95 damage. Recorded reload time was about 46.4 seconds, including 23.0 seconds with a selected mech. However, a prominent weak-target delay at 37.9–40.1 s followed an old empty-ammo reload command reaching the online game after a magazine had already refilled. This lag-sensitive partial reload must not be treated as an official lockstep failure or a clean magazine-upgrade benefit.

Nanites retain higher priority because their benefit was directly used. The later diagnostic recorded 1,972.31 HP of regeneration with one nanite stack: 72 HP/s after a 3.5 s quiet period, instead of base 45 HP/s after 5 s. One uninterrupted window restored 847.04 HP between 79.7 and 91.5 s. Holding the observed quiet interval fixed, the base rate/delay would permit approximately 459 HP in that same window. This is a health-recovery timing comparison, not a counterfactual survival claim.

An offer-only replay of the implemented rank against the unchanged baseline checks all 41 offers: five choices change, all to the first drum, and the nanites choice is unchanged. Changed offers had health ratios from 86.1% to 100%. The second-stack evidence is too sparse to justify changing its rank.

## Validation and acceptance

All **134 tests pass**: the 124 baseline tests plus ten focused first-magazine regressions. The runtime diff against `39b6d50` is exactly five added lines in `choose_upgrade`; no other runtime file changed. Container, private-match and official evaluation remain separate steps.

- Focused offer tests: first drum versus armor/servos; nanites preserved; low-HP plating preserved; second drum unchanged using both observed capacity and upgrade history; non-default configured magazine; stale gun offer without a held gun; actual `Bot.act` pick and observation immutability.
- Run the complete baseline regression suite, then the exact restricted container checker and an unchanged-source private diagnostic. Private results diagnose behavior; only the official 48-match result determines whether this experiment improves the retained entry.
- Compare the final runtime diff with `39b6d50`: only `choose_upgrade` should change. Keep the 4.75 entry selected unless the official result is higher.
- Record offered choices, actual picks, gun reload/shot use, kills and placement. Do not infer a controlled kill gain from a fixed-observation readiness probe or a single random private result.

Sources: official `protocol.md` sections 9–10 and `hello.config.upgrades`; numeric diagnostic observations are retained locally. No credentials or private-room identifiers are needed in this repository.
