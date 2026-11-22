# Bounded duel or retreat experiment

Base: `9c440e4f9609bf5028886751cf646fd1969fd461`. This preserves the base's native terrain, navigation cache, ground reachability, route checks and global 32 ms planning deadline. It does not incorporate the collection lease or recovery-goal exposure candidate.

## Behavior and interfaces

`DuelController.decide(obs, threats, target, stats, urgent=False)` returns a diagnostic report with `retreat`, `phase`, `reason` and counted opponents. `Bot.act` uses it for movement mode and optional-resource precedence. A healthy single reachable target receives a ranged probe without prior damage or a weakened-prey requirement. Optional loot cannot replace the target while that probe's progress clock is running. Lightning keeps its existing close-contact spacing only when already in its live range; carrying it no longer causes a distant approach to 33 m.

The active set comprises the chosen reachable opponent, other currently exposed mechs within their configured weapon reach, actual mech damage sources retained for 3 seconds, and previously exposed actors absent from the observation for 1 second. IDs are deduplicated; NPCs, zone damage and null IDs do not fabricate extra mechs; killed actors are removed. An observed occluded bystander is not automatically counted. This is a classification model: outgoing LOS and base enemy weapon range do not prove safety from incoming fire or reveal enemy upgrades.

Retreat preempts loot and uses the existing `recover` route/movement contracts. Below 55% HP enters a separate health latch, released at 93%. Full-health multiple-opponent contact still retreats. Zone rotation retains priority. The existing imminent/recent-contact defensive-fire rules remain; no-new-laser-charge and mortar emergency rules remain. The current-position quiet-healing check additionally requires all bounded incoming body samples to be blocked, with unknown unseen attackers, mortar arcs, projectiles and exhausted ray budget treated as uncertain. These samples neither certify cover nor change recovery-goal ranking.

## Explicit experimental limits

- Initial probe: 2 seconds, extended for current own readiness/turn/flight up to 3.5 seconds.
- Progress: only positive own `hit` events on this encounter's target count. Other damage or falling target HP does not. A gun reload has a fixed readiness/flight grace. At the first no-progress boundary, one pending-weapon allowance uses the latest first arrival among currently usable own weapon cycles plus one action interval, capped at 1 second. Its deadline cannot renew on cooldowns, charges or another reload; only another actual target hit re-arms it.
- Cost: incoming `damaged.amount` after the entry observation accumulates against 25% of **entry** maximum HP. Cubes, healing and maximum-HP changes do not refund the ledger.
- A cost exit may receive one fixed finish attempt of at most 1.5 seconds only with recent own hits, known positive enemy HP, current HP above 55%, no urgent zone rotation, and an ideal live-weapon finish inside that interval. It cannot override multiple attackers or the 20-second absolute encounter cap. Expiring a health-cost extension retains the heal-to-93% latch.
- The 8-second remaining-HP/recent-own-damage estimate is diagnostic only. Recorded cheap successful progress produces 13–38 second estimates around burst/reload boundaries, so it is unsuitable as a hard veto.
- The same encounter ledger survives brief LOS breaks. Six seconds without relevant contact expires it. A committed retreat can also re-arm after at least 6 seconds when at least 93% healthy and exactly one eligible opponent remains. A one-frame cover break cannot renew the probe or finish allowance.

The own-weapon schedule uses observed ammo, reload, cooldown, energy, live upgraded stats, body pitch envelope, torso rates and travel time. It assumes ideal unarmored hits and simplified current geometry. It is a readiness/optimistic finish model, not a guaranteed kill time or an estimate of hidden enemy DPS.

## Necessary retreat/weapon integration corrections

An observed laser charge remains in the tactical motion input after releasing its trigger, until a later observation clears it. In particular, release below minimum charge does not instantly restore full movement. The existing rollout holds the observed slowdown over its short horizon, which is conservative.

During non-firing recovery reloads with no valid visible defensive inputs, a bearing from an actual non-null damage event remains the fallback for 3 seconds. Zone damage does not refresh its timestamp. Visible-threat defensive optimization and firing/charging behavior are unchanged by that fallback.

Laser full-charge recognition uses a named 0.006-second tolerance with a minimum-charge guard, consistently for release and the bounded aim hold timer. Recorded observations plateau at `.56` with upgraded threshold `.563`, and `.42` with `.422`. The tolerance is an explicit small release policy, not a claim that the engine guarantees a particular rounding rule.

## Validation scope

`tests/data/duel-captured-regressions.json` retains exact trace/source provenance for 223 captured frames. Conditional tests retain all 168 frames of the 142.6–159.3 cheap final duel, select a health-cost retreat at 123.2 in the costly prediction trace, retain the pending gun hit at 16.8 in evasion, and exit on a fixed deadline when later hits are removed. A separate weapon assertion changes the recorded 16.6 laser hold command to release. No recorded-position replay simulates the outcome of a different action or proves an improved match score.

Full chronological route/deadline replay and the restricted Linux checker are recorded separately in the audit report before freezing this experiment.
