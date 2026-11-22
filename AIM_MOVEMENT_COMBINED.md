# Reviewed aim and movement-kernel combination

This branch starts from exact aim commit
`53d8d79502763325184252761ccc9ff7bbf5081e` and cherry-picks exact movement-kernel
commit `174e3a103b93891eb77627bbc60b9e8e3d8446fe`. The cherry-pick completed
without conflicts as local commit `8b4971c49030d723476fbb3f9fabb1ffc402a764`.
Both individual candidates originally branched from
`b0e296c356cd636ed5576b0152429dea22ddcffb`.

At preparation, the authenticated competition result reported for aim 53d8 is
**4.92**, submission **BB-4D7806CA**, selected as the current best. The b0 base
scored 4.77, and combat-cover 9dd tied 4.77. The kernel candidate subsequently
scored **4.60**, submission **BB-97861BB8**, below the selected aim version.
Its one completed normal private diagnostic placed second with five kills and
37 cubes, with no timing errors. That private result is not an official score
or a paired estimate of strength. Combining the components remains a separate
experiment; their benefits are not assumed to add together.

The combined code preserves both reviewed implementations:

- The gun/laser horizontal barrel solver, its captured fixtures and weapon
  tests are byte-equivalent to aim 53d8 in Git. Lightning, mortar and the
  existing shared-aim/readiness/firing policy retain their reviewed behavior.
- The native movement wrapper, C++ predicate, Docker build, bot import and
  movement tests are byte-equivalent to kernel 174 in Git. Existing geometry
  predicates, fallback, navigation intent, tactical scoring and runtime
  deadlines are preserved.
- No local-steering policy, recovery-seed selector, combat-cover controller,
  duel policy, or new parameter tuning is added by this combination.

The manifest in the workspace audit directory records exact blob identities
for every inherited change and normalized-LF hashes for runtime sources,
compiler sources, Dockerfile and both binary caches. It separately identifies
the source of each component. The original `MOVING_AIM.md` and
`MOVEMENT_KERNEL.md` retain their individual bases and validation history;
those test/checker/replay results do not validate the combined runtime.

Independent source review verified the exact 11-file union above. The combined
Linux/amd64 image is
`sha256:8486196cc1b6fb177f4e60c539f476641173104463aba0ec015e84620bc6ed55`.
Its full restricted Linux suite passed **230/230 tests**. The official checker,
run inside Linux with the real map, passed **300/300 observations**, p99 20.8 ms,
maximum 26.5 ms, with zero malformed, wrong-tick or late answers. Runs use one
CPU, 512 MiB, read-only root, no network and the existing unchanged deadlines.

Preflight verified every runtime source and both binary caches against the
manifest, the 259-prism/774680-sample arena, loaded terrain/movement kernels,
loaded navigation/ground caches and the external `pow` symbol. The combined
native library SHA256 is
`c092ae557b3cb3572b9d99cf64550f4442bde60f3ff3831e084b3b65727341c3`,
identical to the individually reviewed kernel build. Runtime sources were
checked again after each replay.

Two complete, unmodified chronological `Bot.act` replays passed:

| Recorded stream | Decisions | p50 / p99 / maximum ms | Zero MOVE | Tactical fallbacks | Errors / >50 ms |
| --- | ---: | --- | ---: | ---: | --- |
| Integrated 9c | 1,594 | 19.275 / 31.289 / 32.070 | 289 | 10 | 0 / 0 |
| Incoming-cover bcd | 1,038 | 27.692 / 31.265 / 31.945 | 105 | 3 | 0 / 0 |

The first replay has one decision above the internal 32 ms planning target,
and none above the competition's 50 ms limit. These observations retain their
recorded future positions, damage, ammunition and charge. They measure runtime
and conditional decisions, not new hits, escape, survival or match strength.

Against the aim-only integrated replay, all 1,594 aim/fire/reload/take/drop
commands are identical. Zero MOVE counts fall from 298 to 289 and fallbacks
from 16 to 10. There are 90 movement-vector changes, 10 boost changes and five
normalized goal-coordinate changes. The four previously failing ENGAGE frames
97.3, 97.4, 97.9 and 98.0 now issue nonzero movement with valid posthoc geometry.
The new neutral at 34.7 is a completed, geometrically valid decision in POSITION
mode with no threats and its goal equal to the current position. The 17.7
fallback is identical to the aim-only replay, although the kernel-only replay
used another recovery goal and moved there.

Against kernel-only, integrated aim changes on 462 frames and firing changes
only at 142.6 and 142.7, exactly the existing aim-only behavior: both gun and
fresh laser starts are withheld. Existing motion prediction consequently uses
laser charge zero rather than its 0.001 start marker at those two frames. No
observed future charge is changed by the replay. Kernel-only and combined both
have 289 zero MOVE commands; fallbacks are nine versus ten.

On the incoming stream, compared with kernel-only, there are 471 aim changes,
13 fire-vector changes and one reload change, with unchanged target IDs and
modes. Three fresh laser starts are withheld (40.8, 55.5, 75.7); six frames hold
an observed full laser instead of releasing (51.2, 56.8, 56.9, 59.8, 59.9, 60.0).
These existing aim/release-policy interactions preserve observed charging
slowdown in those conditional commands and require disclosure; they are not
automatically accuracy improvements. Zero MOVE/fallback counts are 105/3
versus kernel-only 107/4. During 99.2–100.3, 10 of 12 commands are nonzero
versus nine in kernel-only. No actual escape is inferred.

Direct comparison to the frozen aim-only incoming replay confirms all 1,038
aim/fire/reload commands are identical, with identical target/mode/recover
states. All six hold frames and 80.6 also retain identical movement/boost
commands to that prior aim-only audit. Consequently the existing
`moving-aim-six-holds.json` review applies without another replay: these are
inherited aiming effects, not new combined-command regressions. The known
tradeoffs remain: charging slowdown, shared-aim gun suppression at 80.6,
the moving-pose limitation at 112.4, and transient torso slew at 127.4. No new
body-alignment improvement or regression is inferred from unchanged commands.
Against aim-only, incoming zero MOVE/fallback counts improve from 128/44 to
105/3; movement changes on 202 frames and boost on 33. The one jump-command
difference is 100.1: the unchanged stuck detector requests a jump with nonzero
unboosted recovery movement. This command also occurs in kernel-only. The
posthoc tactical rollout checks ground movement, not the resulting jump
trajectory, and therefore does not certify the jump's simulated outcome.

Posthoc geometry retains the known limitations: integrated neutral fallbacks
17.8 and 81.1 and incoming neutral fallbacks 97.0 and 97.1 have invalid full
rollouts, also present in the respective kernel-only records. Seven integrated
lease-active decisions are marked unknown because their larger navigation
body is not reconstructed. Every other evaluated action passed the unchanged
geometry predicate. A valid rollout does not certify enemy-fire protection.

The scratch audit records `aim-movement-runtime-manifest.json`,
`aim-movement-linux-tests.log`, `aim-movement-linux-checker.log`, the two
`aim-movement-8486196-*-prefix.json` artifacts and
`aim-movement-8486196-normalized-comparison.json`. Goal comparisons normalize
serialized coordinate values, avoiding the old tuple-versus-list reporting
issue. The command comparison retains exact input/output hashes. The aim
solver and faster movement checks can affect which work completes before the
deadline, so individual improvements are not assumed to add together.

Source and validation review accepted this exact combination for freezing and
publication as a separate experiment. No combined private game or official
score is available at freeze. Aim-only 4.92 remains the selected best; the
kernel-only 4.60 result is adverse evidence, and combination strength remains
unproven. This freeze adds only this validation document to the reviewed
component cherry-pick; no runtime tuning follows the recorded checks.
