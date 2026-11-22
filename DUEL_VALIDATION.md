# Duel candidate validation

Validated 2026-11-22. Execution base: `9c440e4f9609bf5028886751cf646fd1969fd461`.

Final runnable Docker image ID (from `docker image inspect`):
`sha256:2f3b0929a1a59703636f1b217402ae2ef633d04873b56f88d45cfb150e519806`.

Final runtime source hashes, with LF-normalized source bytes:

| File | SHA-256 |
| --- | --- |
| duel.py | 22025c59eddc9ed2f4b992cab8a902b7441e046263b996d70aee5f28a315667d |
| bot.py | ea5919a0e8d374378b040b1be2560c6bf794687c2fc2a97db5cbb74729a369f0 |
| combat.py | c5b3bf90f71efc15f94e3df6465047fa14cc5a4b4e6fa0ca66d3fa7906fecdcc |

No runtime edits followed these runs. Earlier source-file replay artifacts and the initial 206-test result precede the timestamp-anchored encounter-expiry correction and are not presented as exact final-image results.

## Restricted Linux tests and checker

The final image ran with no network, one CPU, 512 MiB memory/swap limit, 128 PID limit, read-only root, a 64 MiB temporary filesystem and UID/GID 65534. The official map and test/checker inputs were read-only mounts. The checker itself ran inside Linux with `/arena`, avoiding the previously identified Windows path-rewrite fallback.

- All **207 tests passed** in 34.655 seconds, including captured observation regressions and native geometry tests.
- Official checker: **300/300** timely valid actions; **0** wrong ticks, bad lines, late actions or debug-limit violations.
- Checker response times: median **10.2 ms**, p99 **26.5 ms**, maximum **28.3 ms**. Ready response: **3332 ms**.

These are local restricted-container measurements, not an official score or a guarantee about a different host.

## Independent full chronological replays

Both replays used the exact final image and checked LF-normalized image/source agreement, native terrain availability, loaded navigation/ground caches and the real map. They retained the actual `Bot.act` deadline and existing planning budgets. Recorded observations do not react to changed actions.

| Trace | Actions | p99 | Maximum | Errors / actions over 50 ms |
| --- | ---: | ---: | ---: | ---: |
| C1 correctness-ab878 | 1045 | 31.685 ms | 33.096 ms | 0 / 0 |
| Integrated 9c440e4 | 1594 | 31.823 ms | 34.846 ms | 0 / 0 |

C1 exercised 342 retreat decisions: 156 multiple-opponent, one initial health-cost exit, and 185 health-recovery frames. The 156-frame jam window completed 102 of 105 required routes; post-hoc ground witnesses were 144 reachable, 12 outside ground scope/unknown and zero unreachable. All sampled goals in that window were inside the zone; 152 actions had nonzero movement.

Integrated exercised 443 retreat decisions. Its final favorable 142.6–159.3 fight retained all **168 frames** without retreat: 20 probe frames and 148 duel frames, including the documented reload/burst gaps. Early no-progress retreat activated at 5.4, followed by commitment through 11.4. Neither full-prefix replay activated quiet-healing protection or the near-finish extension; those have controlled positive/negative tests rather than live coverage claims.

## Known limitations retained for the experiment

- C1 recovery goals at checkpoints 95, 97, 99, 100, 101 and 102 retain the inherited outgoing/incoming cover mismatch: each selected destination has three of five sampled incoming rays clear. This candidate does not change recovery goal ranking and does not promise a successful escape.
- Six integrated post-hoc unreachable endpoints were **engage standoff endpoints**, outside the ground-safe-goal guard, not newly unreachable retreat goals. Tactical motion validation remains in place; a goal witness is not proof of actual arrival.
- All captured replays keep the original movement and enemy behavior. Earlier target exits, different laser release commands, valid routes and smaller local compute times cannot establish extra kills, healing, survival or a higher competition score.
- The 20-second cap, 25% entry-health cost budget, bounded pending-hit allowance, 1.5-second one-use finish extension and small near-full laser release tolerance are explicit experimental policy choices.

Detailed local artifacts are `duel-linux-tests-final.txt`, `duel-linux-checker-final.txt`, `duel-c1-2f3b092-full-prefix.json`, and `duel-integrated-2f3b092-full-prefix.json` in the audit workspace. The compact 223-frame source/trace-provenanced regression fixture is committed under `tests/data/`.
