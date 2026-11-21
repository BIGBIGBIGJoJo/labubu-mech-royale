# Historical experiment document

This file records earlier experimental branches. The current controlled
experiment is described in PROGRAM_DESIGN.md and the three current strategy-agent plans. Its runtime
does not include all mechanisms proposed or tested below.

# Aggressive fire plan — user policy updated

The user now prioritizes greed, aggression and kills, with an official score target of 6.0. This supersedes the former no-initiation, external-fight-evidence and quiet-enemy protection rules. This plan was written before implementation. AggressiveEngagement is now enabled in aggressive-v1; current validation is recorded in VALIDATION.md. Prior selective receipt BB-AC10AB33 scored 2.69 and is not an aggressive result; historical best remains 4.75.

## Recommended first candidate

Replace admission/selection, not the verified ballistics or weapon scheduler. Use a proactive selector that can attack any current, visible hostile mech. First choose a physically feasible short kill; otherwise use the broad target-value ranking from best39b, with readiness and continuity. Restore useful approach/spacing in the movement agent. Keep economy active when no useful shot or favorable combat is available.

This is a stronger grounded starting point than designing a new long-horizon fight simulator: best39b scored4.75 with broad target admission and approach. The selective initial and zone/reload policies scored2.46 and2.29 respectively. These are different whole-policy evaluations, not a controlled estimate of any one change. Private placements do not establish practice score: latest selective-v4 won privately with3 terminal kills, yet never found external-fight evidence or entered FINISH.

## Selection and interface

The root enables `AggressiveEngagement(config, line_of_fire=None)` using the verified `Engagement` geometry helpers, with `select(obs, candidates, recovering=False, deadline=None)`. A selected target uses `AggressiveDecision`, adding `finish_weapon` to the base Decision fields; an observation-only result can use Decision. The old class/tests remain a separately exercised baseline. `mode="ATTACK"`, `target`, `allow_fire`, `reason`, `finish_eta`, `finish_weapon`, `authorized_ids` carry the selection. `authorized_ids` includes all current hostile mech IDs; no attribution evidence is required. Never use a remembered actor as a firing target.

1. Filter current living mech observations through current LOS and at least one weapon that can physically hit it after actual readiness/turn time. A target behind another mech is not the gun's direct hit target. Preserve first-interceptor checks, finite laser pierce, and nearest valid lightning primary. Authorizing damage to another hostile does not imply that damage reaches the selected target.
2. For plausible one/short-burst kills, reuse the existing conservative <=2s estimate. Among genuinely finishable candidates, choose the lowest finishing ETA; tie-break by HP, then previous target, distance and ID. An unavailable target must not win simply because it has low HP.
3. For all remaining viable targets, use best39b's broad score as the fallback: `2 + observed_risk + 1.6*(1-hp/max_hp) + .7*recent_attacker + .35*current_target - .006*distance`, retaining its explicit low-HP finishing bonus where no exact short estimate is available. Deduct a small explicit readiness penalty, e.g. `.4 * first_usable_seconds`, to avoid selecting a reloading/incompatible target over immediately usable damage. These weights are policy parameters, not physical facts.
4. Use a stable incumbent: keep it when the challenger offers only a small fallback-score improvement. A new clearly feasible short kill overrides continuity. During an active laser charge prefer the current still-feasible target unless a new short kill is clearly better; never let a continuity preference override a blocked line, absent/dead target or physical range.

The existing `_weapon_profile` is **not a general TTK calculator**: it caps finishing at2s, accepts only a one-beam laser kill, and excludes mortar finishing. `finish_eta=None` therefore means “no validated short kill,” not “cannot fight.” Do not filter out full-health mechs using that field. It already returns a separate usable-shot wait.

For efficiency, calculate cheap damage/ammo/cooldown/slew bounds for all <=15 current mechs, short-kill geometry only where the bound permits a <=2s finish, and ordinary direct path checks in score order. Mortar arcs are evaluated only for a small top set or when no ordinary weapon is usable; do not compute15 expensive arcs every decision. Preserve a hard fallback when the optional scoring budget expires.

## Weapon behavior and collateral

Keep Combat's proven gun intercept, frame-ready trigger holding, actual-ray geometry, correct cube scaling, lethal laser release, own-velocity launch offset, mortar low-arc solver and bounded mortar aim commitment. Do not expand the shared-aim scheduler in the first candidate. Gun plus lightning can both work when the actual torso cone permits; gun plus laser cannot be credited as independent aim solutions.

Root passes no quiet-hostile protection to Combat (`protected_ids=None`, or the equivalent empty set). All enemy hits and lightning chains are now useful; NPC/crate interception still changes which body actually takes damage. This removes a prior policy gate, not walls, self-splash safety, weapon readiness, current range or energy checks. Charged-laser release remains irreversible and must never be described as cancellation with zero emission.

Gun partial-reload protection remains: do not auto top-up while a useful nearby target may become hittable; empty magazines still reload. Keep the recent confirmed fix. Use current cooldown/ammo and predicted turn time to prepare a target during a short reload; do not repeatedly switch because the first shot is a fraction of a second away.

Do not impose the old35-energy elective-finish escape reserve on **all offensive firing**. Separate the conservative finishing estimate from actual usable-shot permission. Keep actual lightning's existing low-energy gate and movement's reserve/boost policy; a short kill's estimate must still account for enough energy for its required shots. Relaxing reserves belongs to a measured later economy/escape tradeoff, not silent reuse of the old finishing constraint.

## Recovery and economy coordination

Aggressive admission is unconditional on who fired first. Movement still decides whether an exposure is worth taking. At healthy HP, attack viable current mechs and approach the useful weapon band. During recovery, continue combat when a short verified kill is available or incoming pressure makes quiet regeneration implausible; otherwise preserve the repair window rather than firing low-probability distant shots. Root must make this recovery policy explicit instead of accidentally retaining the former attribution gate.

Use the current safe NPC/crate farming policy if there is no useful current mech engagement. An already aggroed nearby NPC can be removed before a distant hard-to-hit mech, consistent with best39b. Do not interrupt a near-complete mech kill to farm. Weapon/cube pickup scoring and whether to close/loot remain orchestration/movement responsibilities; selector admission must not force all15 enemies to be continuously chased.

## Bounded validation before submission

- Full-health quiet visible mech can be selected and fired on; no damaged/beam evidence needed.
- Two targets: lower feasible ETA wins; very low HP behind cover or another body cannot falsely win. Gun interception selects the nearer reachable hostile; laser pierce and lightning primary respect their actual mechanics.
- All current hostiles are collateral-authorized in both profile and final Combat; no obsolete quiet-enemy protection remains.
- Charged laser target continuity, disappearance and materially better short-kill cases; no indefinite charge holds.
- Gun cooldown/reload, energy-starved lightning, mortar-only reachability and out-of-range targets remain correctly gated.
- Recovering but immediately finishable target versus recovering/no useful damage; root owns the explicit recovery decision.
- No useful combat permits safe farming; active finishing takes precedence; empty-magazine reload remains unconditional.
- Dense15-target stress with mixed weapons stays below the existing decision deadline; inspect p99/max and any policy fallback.

Run private diagnostics for actual commands, observed hits, focus churn and time spent unable to fire; keep results separate from the official score. Compare the whole candidate through official scoring. The completed prior-policy receipt BB-AC10AB33 scored 2.69; it is not an aggressive-candidate result.

## Validated readiness-order correction before publishing aggressive-v1

The frozen aggressive-v1 diagnostic revealed a concrete ranking bias at50.5–50.8s. Its incumbent alternated between mech2 (332.6HP) and mech4 (1276.25HP). The fast seed cached the first viable gun slot's reload wait as though it were the minimum over all weapons, while challengers received their ready laser's minimum. At50.5 the incumbent2 was scored using2.35s instead of its0.05s laser wait; challenger4 received0.25s. At50.6 the reversed incumbent4 was penalized by2.25s, causing selection to flip back. This is weapon evaluation order, not evidence that the opponent became more valuable.

The implemented correction makes seed readiness comparable with ordinary target
readiness. Weapon candidates are evaluated in increasing readiness lower bound;
pruning occurs only when that bound cannot beat the best fully checked wait.
Readiness order alone does not account for aim delay. Completeness is tracked,
so an interrupted seed is not compared as an exact minimum: it is completed
within reserved fallback work, or retained as a validated fallback without
using its partial wait to justify switching. The six-millisecond cooperative
scoring budget and physical path checks are unchanged.

Regressions cover a reloading gun plus ready laser preserving the appropriate
incumbent, slot-order invariance, and a lower-readiness weapon that still loses
on aim delay. These tests and recorded-state decisions validate the correction;
they do not establish improved official score. Candidate-wide measurements are
recorded separately in VALIDATION.md.

## Implemented finishing-weapon budgeting correction

Before this correction, the readiness-fixed selector (source hash
`743b0f6c3de7bca65fee9bffecaf0852f761c5ef6d880bbe4cafc26bdf2c411f`)
still missed short laser estimates on the original aggressive trace. At 51.3 s,
mech 2 had 265.1 HP at 102.48 m; our gun reload was 1.55 s, the laser was ready,
and our mech had 318.76/1568 HP and 71.66 energy. Complete profiling validated
a 0.85 s laser finish, but nominal six-millisecond selection reported no ETA
because gun-first mixed profiling exhausted its short-analysis slice. At
82.4–82.9 s, the same target fell from 207.95 to 39.65 HP at 101.6–101.74 m;
laser estimates were 0.55–0.25 s while gun reload was 2.35–2.15 s. Clear
world/body paths were verified in those captured states. These are pre-fix
missing-estimate findings, not demonstrated missed kills.

The implemented selector profiles only weapons whose arithmetic finishing lower
bound is at most two seconds, in ascending bound order. Each is checked
independently; the minimum validated ETA and its `finish_weapon` are returned
without adding incompatible shared-aim DPS. Legacy Decision/CommittedDecision
constructors are unchanged. The whole-selector budget, ordinary fallback and
physical checks remain. Identical solution geometry is reused only within one
select call; keys include weapon parameters, the cache clears every decision,
and budget-interrupted results are never cached. The captured 51.3 s case now
reports laser/0.85 s under the nominal selector budget; this is a decision
replay, not a simulated alternate kill.

The root now permits a fresh recovery laser charge only when the laser itself
supports a verified ETA at most 1.25 s, HP is above 15%, the mech is grounded,
rotation is not urgent and firing is otherwise permitted. A gun-only short
estimate does not enable an unrelated nonlethal laser. Urgent and airborne
recovery retain the veto. Charging still halves movement speed. Four actual-Bot
regressions cover the positive case and these exclusions, alongside selector
weapon-order, provenance, slot-order and bounded-work tests.

## Deferred until evidence warrants it

Do not first implement a full multishot laser/mortar fight simulator, infer hidden armor, sum incompatible shared-aim DPS, or aggressively chase an extrapolated invisible target. A longer TTK estimate can later use sustainable gun magazine/reload cycles and laser charge+cooldown, but should rank a bounded current exposure rather than promise a kill. The first candidate should recover proactive opportunities while preserving verified mechanics and measured compute limits.
