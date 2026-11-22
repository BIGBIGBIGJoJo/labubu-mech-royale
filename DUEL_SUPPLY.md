# Duel supply candidate

This isolated repair starts from `6d9dc40ba57b20df33d56aee04c49a25e5472552`, whose reported builders4 score was 3.01. That aggregate result motivates investigation; it does not establish which behavior caused the score.

The change preserves defensive fire while withdrawing at the existing 93% recovery-exit threshold. Protected-healing quiet and emergency restrictions remain in force: fresh laser/mortar attacks stay blocked, while legal gun/lightning defense can continue. Existing charge, cost, finish and retreat parameters are unchanged.

Before creating a new encounter, a healthy, nonurgent controller may keep the existing resource selector's winning weapon-pickup approach. Danger gates run first. The selector runs once under its existing deadline; no alternative loot ranking, acquisition timeout or extra budget is added. An encounter present at decision entry cannot be replaced by acquisition, including a normal retry reset. A positive current hit on the selected opponent starts its ledger immediately. A single incoming attacker alone does not veto a vetted approach while HP remains at least 93%; attacker memory and multiple-opponent retreat still apply. Automatic taking is unchanged.

## Exact runtime

Validated 2026-11-22. Runnable image ID:

`sha256:2a4b8c684702b325513b0d7a3543b0d689c7ac8729a046208c48e706ec8bb5c7`

| Source | SHA-256 after CRLF-to-LF normalization |
|---|---|
| bot.py | `5166106b4427687d8c6dfe4838e11b79a47ffe9c5e2455499b643de5b9444b91` |
| duel.py | `35528c485810f99dfaca3a118ef1fb1e09e2d7a850e22d82f8cc892405ff7ab9` |
| combat.py, unchanged | `c5b3bf90f71efc15f94e3df6465047fa14cc5a4b4e6fa0ca66d3fa7906fecdcc` |

No runtime edits followed validation. Geometry, native terrain kernel and both cache assets are unchanged. Independent source review found no demonstrated blocker.

## Validation

Tests and checker ran inside Linux/amd64 with no network, one CPU, 512 MiB memory/swap, 128 PIDs, a read-only root, 64 MiB temporary filesystem and UID/GID 65534. Preflight verified image/source equality, the actual 259-prism/774680-sample arena, native terrain kernel and both geometry indexes. The official checker ran inside Linux with `/arena`.

- **221 tests passed** in 35.972 seconds. Tests cover acquisition priority, a single resource scan, stale recovery restoration, unchanged taking, danger gates, existing/retried encounters, and current-hit ledger initialization followed by incoming cost accumulation.
- **300/300 official checker observations passed**, with zero late/invalid/wrong-tick responses. Response p50 11.0 ms, p99 29.4 ms, maximum 31.0 ms; ready response 3433 ms.
- The captured 110.3-second unit fixture freezes the clock to isolate policy and real geometry. It is not a scheduling test. The chronological replay below supplies budget evidence.

Both full chronological replays use unchanged observations and the same source/native/map/cache assertions. Only existing navigation/telemetry capture is added; diagnostic geometry queries occur after chronological decisions.

| Recorded prefix | Decisions | p50 / p99 / maximum ms | Errors / over 50 ms |
|---|---:|---|---|
| Integrated 9c | 1594 | 21.689 / 31.560 / 32.402 | 0 / 0 |
| Actual duel 6d | 1841 | 12.257 / 31.116 / 31.634 | 0 / 0 |

On integrated observations, exactly 25 probe decisions become acquisition at 110.3–112.7 seconds for laser 8053. Movement at 110.3 points toward the weapon; maximum acquisition compute is 31.540 ms, with no zero movement while more than 4 m from that goal. Taking is unchanged. The recorded laser-equipped observation at 112.8 starts a normal probe. Retreat remains 443 decisions. Exactly 45 fire vectors change, all to gun fire while recovering at healthy HP: 28 immediately ready, 17 opportunities within the held command as cooldown/reload ends. These are **45 commands, not 45 independent shots or hits**. No fresh laser charge is admitted during healthy retreat.

On actual duel observations, acquisition does not activate; phase counts and all fire vectors remain unchanged. Retreat movement remains nonzero for 428 decisions. Both prefixes have zero acquisition/fire-gate violations and no take-command changes. Integrated fallback decisions are 12 versus the earlier replay's 13; actual-duel fallback decisions are 2 versus the recorded 3. These small timing-dependent differences do not establish a navigation improvement. Actual-duel quiet decisions are 153 versus recorded 144, with no fire change; quiet sampling is deadline dependent.

Artifacts are under the workspace's `work/game-interface-audit`: `duel-supply-2a4b8c6-tests.log`, `duel-supply-2a4b8c6-checker.log`, both `duel-supply-*-2a4b8c6-full-prefix.json` files, and `duel-supply-2a4b8c6-activation-summary.json`.

These fixed-future observations cannot prove actual collection, damage, escape or score improvement. In particular, the recorded equipped weapon is not caused by the replay's alternate movement. An empty or expired resource scan starts the normal probe and cannot repeatedly defer an existing encounter. The scoped recovery restoration test checks exception-safe state restoration; it does not turn an unexpected resource exception into a graceful action fallback.
