# Resource progress V2 validation

Base: `25c847bb154e5d8d9c8436588fb056615e247146` on isolated branch `goal/resource-progress-v2-seven`. Reviewed candidate; no V2 live game or official submission.

## Problem and change

The 2 s failed-progress test can blacklist a resource after an inertial out-and-back path, even while the bot is approaching at full walking speed. Captured rotation 22.4 s has a clear 21.587 m route to cube 5008, actual approach of 4.680 m over the last 0.4 s, and toward-goal velocity 11.704 m/s, yet V1 admits a blacklist. Its positive score is 49.128 including continuity. The same cube remains the unblacklisted best resource at sampled nonurgent times 23–30 s. This establishes suppressed eligibility, not earlier collection in an altered match.

The existing same-objective failure gate remains first. Only then, observed approach of more than 1.3 m over approximately 0.4 s grants a bounded 0.4 s veto. The same current resource position is used for all distance comparisons. The veto must still have recent measured approach on every call. Renewal after expiry requires another 1.3 m of net approach relative to the prior veto position, so a periodic loop cannot renew merely by returning to the same point. Changing or losing the resource objective clears the veto. Global stuck detection, jump, navigation, scoring, combat, and resource ranks are unchanged.

The 1.3 m threshold reuses the existing stuck/noise tolerance; the 0.4 s observation/grace window is an experimental hypothesis, not a configured game constant or an asserted optimum. An initial one-event veto design could reject the next 0.1 s step because 1.17 m is below the 1.3 m renewal requirement. The bounded continuous episode addresses that counterexample; the tests include consecutive sub-threshold steps and repeated loops.

Production diff: only `bot.py`, 25 insertions/5 deletions relative to V1. Other changes are seven tests, two captured fixtures, and this document.

## Tests and positive activation

- 13 targeted resource tests pass on host; 137 total tests pass inside the Linux image with 1 CPU, 512 MB, network disabled, read-only root/map, and 64 MB temporary storage. No map-test skips.
- Captured positive fixture includes actual rotation observations 22.4–22.8 and actual preceding history/objective/jump state. Exact body route is clear; cube remains selected without blacklisting across all five frames.
- Unmodified `Bot.act` with its normal 32 ms deadline, in three fresh restricted Linux instances: veto activates at 22.4 in 3/3; cube selected and not blacklisted in 15/15 frames. Full action latency range 21.864–25.524 ms. No scorer override or raised deadline in this check.
- Negative spacing 77.0: sustained drop objective, current toward-goal speed 1.002 m/s, but actual distance increased 0.461 m over 0.4 s. Direct route and forward rollout collide. Blacklist remains admitted in 3/3 bounded runs, at 27.771–30.793 ms; normal jump remains true. This does not claim every possible route is unreachable.
- Synthetic checks cover continuing approach and renewal, periodic out-and-back with no new net progress, no actual motion, no movement intent, objective preemption/change, and evaluating all historical positions against the current target position.

## Full-prefix conditional replay

Every recorded observation is passed to unmodified `Bot.act` from time zero. These are fixed observations, not a simulator: changed actions do not create changed positions, damage, loot, or future observations.

| Trace prefix | Frames | V1 p50 / p99 / max ms | V2 p50 / p99 / max ms |
|---|---:|---|---|
| rotation through 35.0 s | 351 | 20.59 / 32.37 / 37.53 | 20.64 / 31.47 / 32.38 |
| spacing through 78.0 s | 781 | 11.78 / 31.20 / 31.96 | 11.76 / 31.15 / 31.29 |
| navcache through 82.7 s | 828 | 22.22 / 33.71 / 35.35 | 22.05 / 34.00 / 36.18 |

Both runs have zero errors and zero actions over 50 ms across 1,960 frames. Run order was sequential V2 then V1; timing differences are not claimed as an improvement. There is no extra ray search or geometry work in the helper.

**Critical activation limit:** V2 adds zero veto activations in these full-policy prefixes, and their resulting blacklist sequences are equal. V1 already keeps the mortar objective past 20.3 in rotation, so at 22.4 its retained objective is the mortar, not the cube; both policies select the cube at 22.5. A separate full-prefix replay of exact recorded objective attribution reproduces V1 admitting / V2 rejecting the original cube blacklist at 22.4. Both admit spacing 77 and reject navcache 66.6. Do not present the captured-state correction as a full-prefix gain.

## Protocol/runtime check

Exact checker command, run from the shared workspace:

```powershell
docker run --rm --cpus 1 --memory 512m --network none --read-only --tmpfs /tmp:rw,size=64m --entrypoint python3 -v "${PWD}/work/mechfight-kit:/kit:ro" -v "${PWD}/work/labubu-resource-progress-v2/arena:/arena:ro" labubu-score7:resource-progress-v2 /kit/check/check.py --map-dir /arena -- python3 -u /bot/bot.py
```

Checker runs inside the image and supplies `/arena` to the child hello. PASS: 300/300 answered, zero late/missed/wrong-tick/bad lines; ready 3472 ms; p50/p90/p99/max 13.5/27.5/33.5/34.1 ms. Full-prefix preflight asserts real map availability, 259 prisms, and 774,680 terrain samples. `git diff --check` passes.

## Provenance and limits

- Bot SHA256: `6fd91f3dc8e7e83e1168dc90fe416108be7ddf62fb4d5ac927ef19b5787b25df`.
- Validated image `labubu-score7:resource-progress-v2`: `sha256:9d94fb6691f818b8f88b6da2702d4d4c64cda85ffa825891761cf786f62b141a`.
- Captured fixture source trace hashes are embedded in each JSON fixture.
- Audit artifacts in `work/game-interface-audit`: `FIRST_MINUTE_ACQUISITION_AUDIT.md`, `resource-v2-bounded-fixtures.json`, `resource-v1-v2-replay-summary.json`, `resource-v2-v2-replay-summary.json`, and per-frame outputs. Scripts: `replay_resource_progress_v2.py`, `probe_resource_v2_budget.py`.

The additional surviving counterexample occurs once in 15 current private traces. Private opponents fight each other; official practice opponents are allied against the entrant. This candidate establishes a narrow logical correction with bounded runtime, not a measured survival or official-score gain. Root reported V1 official aggregate 4.54; there is no basis to attribute that aggregate result to this episode.
