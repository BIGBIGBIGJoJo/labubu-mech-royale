# Labubu: observe, defend, finish

## Objective and confirmed policy

Aim for an official practice score of **6.0**. The best measured entry is currently **4.75**; this plan has not yet established an improvement.

The first implementation scored **2.46** in coordinated practice. See
[the follow-up plan](SELECTIVE_V2_PLAN.md) for the measured rotation failure and
the next bounded investigations. Private first/second places did not establish
an official improvement.

The user confirmed all three constraints:

- Avoid initiating fights with enemy mechs. There is no fixed opening timer that later permits arbitrary attacks.
- Return fire in self-defense. Join an existing fight only when a weakened participant can be finished safely, choosing the lowest **absolute HP** among eligible opponents.
- Farm crates and NPC drones safely during the opening; avoid enemy mechs while doing so.

The official score is mean placement points, `16 - place`, over 48 practice games. Kills improve resources and survival but do not award these points directly. Practice opponents cooperate and never fight each other, so reactive defense must carry that evaluation. Free-for-all matches can additionally provide third-party finishing opportunities. The policy uses observed events, never a guessed game mode.

Sources: [track and rules](https://www.joinbuilders.org/buildathon/tracks/builders), [protocol](https://www.joinbuilders.org/buildathon/tracks/builders/files/protocol.md?inline=1).

## Movement strategy agent

Preserve survival, weapon spacing, and a feasible exit. Reuse the existing collision-aware map routes and short-horizon projectile avoidance, including cube-scaled body dimensions and truthful route failure status.

While observing, choose cover or safe resources without deliberately approaching a quiet mech. Farming must pass current and remembered enemy exposure checks. Self-defense uses retreat or lateral movement rather than an unlimited pursuit. A finish is attempted from the current usable firing position; the first version does not authorize a speculative chase. Before entry, require health and energy reserves, future-zone clearance, a physically traversable retreat corridor, and tolerable incoming pressure. A failed route, repair opportunity, or shrinking zone can veto entry.

The movement agent owns a bounded safety evaluator and focused geometry/safety tests. It supplies per-target permission and rejection reasons, not weapon commands. Initial spacing remains approximately 120 m for a gun and 150 m for a laser, adjusted for actual terrain and zone. These are policy parameters, not guarantees of safety.

## Fire strategy agent

Own `engagement.py`, which decides **whether** an enemy may be attacked and which eligible target has the lowest HP. Keep the validated `combat.py` controller responsible for actual shot timing, aim, leading, ballistic arcs, and weapon compatibility.

Authorize defense from a recent non-zone `damaged.by` event or an attributed enemy beam intersecting our body. Proximity, aim direction, sounds, an unexplained HP decrease, and anonymous projectiles alone never identify an attacker.

Authorize third-party entry from fresh evidence of one enemy mech attacking another. Attributed beam paths are the initial reliable source. Ownerless gun projectiles require separately validated corroboration before they can establish fight membership. Our own hits, attacks on NPCs/crates, and zone damage must not create a fight. Evidence expires; missing actors are hazards, not firing targets.

Apply permission at the weapon level as well: suppress shots that are predicted to intercept a different observed mech, lightning that would select or chain into one, and mortar splash near one. Starting a laser charge can be suppressed; releasing an existing charge remains unavoidable. Preserve its observed aim when permission is lost rather than redirecting the release toward a quiet enemy. These checks use observed motion and cannot guarantee where opponents will move after a shot is launched.

For each wounded participant, estimate a short finish using actual HP, conservative armor, upgraded weapon damage, cube scaling, ammo, reload, charge, cooldown, range, aim movement, and flight time. Require the estimate to fit a maximum two-second exposure budget with margin and explicit movement permission. This estimates a kill if shots connect; it is not a guarantee. Lowest absolute HP wins among eligible candidates, with finish time and ID as tie-breakers. Do not refresh authorization merely because our shots hit.

## Orchestration strategy agent

Combine independent movement safety and firing authorization. No previous broad target-ranking or close-enemy exception may bypass the new gate.

| State | Movement | Enemy-mech firing |
|---|---|---|
| OPENING / OBSERVE | Safe farming, cover, observation, escape planning | None without the defense/finish gate |
| DEFEND | Evade and maintain distance; no unlimited chase | Only recent attributed attackers |
| FINISH | Hold a safe firing position with an exit | Lowest-HP safe, finishable participant in an observed fight |
| RECOVER | Break exposure and regenerate; safe healing items | Attributed self-defense only |
| ROTATE | Reach the future safe zone | Attributed self-defense without a detour |

Opening is a logistics state, not a countdown. Rotation and necessary recovery control movement; defensive firing can coexist with either. Authorized safe farming is separate from mech permission. Avoid starting a laser charge during quiet recovery; an already-held charge cannot be canceled by the protocol and may fire when released.

The shared decision contains mode, current target, fire permission, reason, evidence class/age, estimated finish time, exposure budget, and exclusions. The orchestrator adds movement mode/range and logs why it accepted or rejected an entry. The movement safety predicate is evaluated per candidate, so one safe enemy cannot authorize an unsafe one.

## Implementation and verification

1. Preserve the selected 4.75 commit and checkpoint the existing correctness fixes.
2. Implement independent engagement and movement-safety modules; integrate them in `bot.py` and the Docker image.
3. Test quiet openings, authorized farming, real attackers, lowest absolute HP, false fight evidence, evidence expiry, quiet regeneration, wall/zone/escape rejection, and laser release limitations.
4. Run the full regression suite, recorded-observation stress tests, and the official 300-observation checker in the exact restricted Docker runtime. These establish correctness and timing, not game strength.
5. Run private-match diagnostics with source snapshots and inspect actual state/permission traces. Private games differ from coordinated practice; report their outcomes separately.
6. Publish only a validated commit, submit it within the official quota, and compare its measured 48-game score with 4.75 and the 6.0 objective. Keep every submitted commit public. Retain the organizer-selected best entry if an experiment scores lower.

A score below 6.0 is evidence for further measured iteration, not permission to violate the user's opening policy. There is no authoritative local tournament simulator, so official evaluation remains necessary.
