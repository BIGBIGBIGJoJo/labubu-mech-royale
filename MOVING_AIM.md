# Isolated gun/laser barrel geometry

Base: `b0e296c356cd636ed5576b0152429dea22ddcffb`, retained official score4.77. Only `combat.py` runtime changes. This candidate has no live-game or official-score result.

Gun and laser solutions now use the measured horizontal barrel extension: offset multiplied by direction X/Y, including cos(pitch), with Z held at muzzle height. A bounded pitch solve and four bounded gun-intercept updates recompute the desired point, launch origin, pitch, range and map segments consistently. Finite, forward-ray and angular-residual checks reject unresolved solutions. The existing center, upper and lower body sample order is retained. Geometry checks cover central muzzle→barrel and barrel→chosen point. A valid geometric solution with blocked geometry remains a solution with `clear=False`, preserving the existing controller's interpretation.

The whole `Combat.plan`, shared-aim ownership, charge/release/readiness/reload rules, lightning/mortar paths, root movement and target selection are unchanged. There is no new actual-ray firing gate, shooter-velocity translation, vertical prediction, laser-release holding policy or movement-policy patch. Nevertheless, corrected solution validity changes some decisions made by the existing rules; those indirect effects are measured below.

## Witnesses and scope limits

- Integrated trace112.4s gun: the corrected current-position pitch0.0425223 clears a modeled roof that the old0.0416526 ray clips. The same fixed corrected command remains blocked at the chosen-movement0.05/0.1s poses. This does not fix all moving-shooter aim.
- Incoming-cover trace80.6s full laser: the corrected solver selects lower-body pointZ12.405/pitch0.146467 under a bridge, replacing upper-body pointZ19.425/pitch0.230868 that hits the bridge in the horizontal-origin model. The lower path remains clear at current/0.05/0.1s poses under two explicitly conditional charge-release motion orders. Laser release remains unchanged, but its shared aim suppresses the simultaneous gun command.
- Baseline127.4s gun: the first slewed ray remains blocked while the body-angle test permits firing. This transient-slew limitation is deliberately not hidden by a new gate.

These are central-ray geometry and conditional motion-model checks. Own shot identities, exact engine movement/fire order and the consequences of new actions are not observed. Gun spread is not converted to a hit probability. The evidence establishes neither actual hits nor a score gain.

## Reviewed runtime and checks

Image: `sha256:b3e7654dcbfc85226817fc3879e54d01a40621d0275e717c61922ff240f18017` (`labubu-score7:moving-aim`, Linux/amd64).

`combat.py` normalized-LF SHA-256: `cd5f42327fe56a8fe9c6b282e8b5c470338519c255cdda40a0aa8a1fdd66fb45`. Other runtime files, native kernel and both geometry assets match b0. Before validation, source/image equality, real map259prisms/774680samples, native kernel and both loaded caches were asserted.

All runs used one CPU,512MB memory/swap, no network, read-only root,64MB temporary filesystem and uid65534. No Windows-host checker was used.

- 217 Linux tests passed without skips. Ten new tests cover recorded current/future poses, explicit simultaneous-gun suppression, retained slew limitation, finite/forward/residual rejection, prefix obstruction, range/pitch, and full lightning/mortar action parity across12 permission/loadout cases. One older low-cover test was corrected from a nonphysical endpoint-height stub to an actual wall-segment function so it accepts a clear barrel prefix.
- Official checker:300/300 timely replies, no late/wrong-tick/bad-line replies. p50=10.5ms,p90=18.6ms,p99=28.1ms,max=30.1ms; startup3326ms.

## Complete recorded chronologies

`Bot.act` was unmodified and uninstrumented during each timed full prefix. Subsequent pure-combat passes gave b0 and the candidate identical saved targets, observations, and existing root permissions. Current pure fire/reload output matched the timed candidate action on every frame: zero unknown targets or reconstruction mismatches. These are fixed recorded futures, not simulations of the changed commands.

| Trace | Observations | Whole-act p50 / p99 / max ms | >32ms / >50ms | Exceptions |
| --- | ---: | --- | --- | ---: |
| integrated9c |1594|23.667 /31.381 /31.805|0 /0|0|
| incoming-cover bcd |1038|30.694 /31.947 /33.358|9 /0|0|

The integrated pure comparison changed462 aim vectors and only two fire-command frames,142.6/142.7: both gun and fresh-laser commands changedTrue→False because the corrected origin had no clear sampled body point. No active laser hold/release or reload changes occurred. Mean extra whole-combat planning time was0.149ms; paired p99 extra1.411ms. Mean direct-solver time was1.142ms versus b0's0.863ms.

The incoming pure comparison changed516 aim vectors and13 command frames. Six gun commands were suppressed, three fresh laser starts were suppressed, and one earlier reload was requested at63.6s. Mortar fire commands were unchanged. Mean extra whole-combat planning time was0.715ms; paired p99 extra3.611ms. Mean direct-solver time was1.574ms versus b0's0.951ms. These separate timing probes did not consume the timed Bot.act budgets.

**Material mobility tradeoff:** six full-charge laser observations changed release (`fire=False`) to continued hold (`fire=True`) at51.2,56.8,56.9,59.8,59.9 and60.0s. Corrected `clear=False` feeds the existing alignment/release rule. All six still commanded movement, but continued charge preserves its movement slowdown. These are six command observations, not six identified shots or a measured additional0.6s physical duration. This indirect behavior requires review before accepting the candidate under a keep-moving combat preference.

A subsequent bounded six-frame audit found that every original b0 release ray clips the same nearby roof (prism53, top6.52m), at both current position and the conditional first0.05s firing pose under two charge-release motion orders. A diagnostic57-point body sweep found only top-edge+.45-height openings at56.8/56.9, outside the unchanged±.40 alignment margin. No current usable first-shot alternative was demonstrated. At59.8 a fresh solve at a conditional0.10s moved pose finds an upper point, but neither fixed issued command is clear there; at60.0 only the old ray becomes clear at0.10s in the release-effective motion variant. These later-pose caveats are not actual-shot evidence. The fixed continuation releases at51.4 when target becomesNone and at57.0 when the existing full-hold timeout expires. At60.1 the recording already has charge0, so it cannot establish the candidate's counterfactual release time. No release-policy change was made. Details are in scratch `MOVING_AIM_SIX_HOLDS.md` and `moving-aim-six-holds.json`.

The80.6s bridge fixture repairs the laser aim while retaining release; simultaneous gun suppression is an explicit tradeoff. No claim is made that geometry gains outweigh the added holds, CPU cost or lost firing opportunities.

Scratch evidence: `moving-aim-linux-tests.log`, `moving-aim-checker.log`, `moving-aim-runtime-manifest.json`, `moving-aim-b3e7654-integrated.json`, `moving-aim-b3e7654-incoming.json`, and `moving_aim_validation.py`. Source and runtime results received independent review before freeze. The six-hold investigation supports retaining the isolated geometry correction while preserving the existing bounded hold policy; it does not establish improved live performance.
