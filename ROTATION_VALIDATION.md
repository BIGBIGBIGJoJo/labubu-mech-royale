# Verified walking after repeated geometry fallback

This isolated candidate starts from baseline `39b6d509af8e82b0ceb9e1c430dd964674d7488e` on `goal/rotation-seven`. It has not been submitted or played in a new live match. Its evidence is unit tests, the official protocol checker, and conditional policy replay of the C1 private trace. Replay observations remain fixed: fewer neutral decisions do not establish a counterfactual match result or score.

## Demonstrated cause

The frozen C1 trace is `../game-interface-audit/correctness-ab878-20261121-163846/trace.jsonl.gz`. Its separate `DIAGNOSIS.md` covers the complete rotation, resources and final recovery episodes.

At 45 s the body is stationary at `(-357.41, 38.77, -5.1)`, with raw navigation approximately `(0.8483, 0.5295)` toward an unfinished route's last point `(-352.38, 41.91, -5.1185)`. This point is 5.93 m away. The desired strategic goal is farther east and uphill.

Exact trajectory checks establish:

- Ordinary walking along this navigation is legal for the complete 0.6 s horizon. Its endpoint is about `(-352.2, 42.02, -5.12)` and geometry takes roughly 6–8 ms on this host.
- The first ranked boosted trajectory fails late, consuming roughly 6.4–7.6 ms. A second boosted proposal consumes the remaining 2.8–4.5 ms without a completed legal path.
- Thus the legal walk is never reached before the existing tactical deadline. Removing a fixed candidate-count limit cannot solve this specific time-budget failure.
- The historical `origin/strategy-v3` partial-waypoint patch does not address this observation: the nearest waypoint is index 1 of 4, so baseline navigation already follows a later waypoint. An isolated replay of that historical `arena_map.py` gives 60 fallbacks versus baseline 61, which is not a material repair.

The unfinished A* search is distinct from the tactical failure. Repeated bounded search calls at this position continue expanding while their closest-to-goal frontier remains unchanged. A short collision-clear walk does not prove the entire strategic route is reachable. No map/search change is retained in this candidate.

## Change

After a grounded decision checks geometry but has no valid path, remember the current body position. Until actual displacement reaches the existing 1.3 m progress threshold, consider validating the current navigation's ordinary walk first. Promote it only when its existing approximate risk/progress score is better than braking. Use the same complete geometry validator, live energy, momentum, charging state, projectile/beam/zone/exposure costs, candidate limits and wall-clock deadline.

The promoted candidate is rebuilt from the current observation and current navigation every time. The episode resets on observed progress, zero navigation, becoming airborne, backwards time, a validated deliberate stop, or a deadline path taking ownership. It never authorizes a previously checked trajectory at a changed position, and never bypasses a failed sweep.

`Bot` additionally records navigation demand separately from final movement. Its bounded two-second diagnostic can recognize recent repeated neutral fallback, which the original final-command-based stuck detector missed. The diagnostic does not jump, blacklist loot, change goals or alter movement. The overall-deadline movement branch now writes a fresh report so earlier tactical telemetry cannot be mistaken for the current decision.

## Conditional replay

Every run primes all 542 observations through 54.1 s and measures the same 156 observations from 38.6–54.1 s. Map dimensions use the live observed three cubes (radius 2.875 m, height 10.35 m). All calls finish without policy exceptions.

| Variant | Neutral fallback decisions | Neutral commands | p99 / maximum act time |
|---|---:|---:|---:|
| Baseline, first run | 61 | 65 | 32.78 / 43.11 ms |
| Baseline, repeat | 57 | 65 | 32.06 / 32.58 ms |
| Historical partial-waypoint patch only | 60 | 67 | 31.79 / 32.01 ms |
| Walk recovery, first run | 12 | 16 | 33.05 / 33.17 ms |
| Final walk recovery | 5 | 10 | 31.49 / 32.24 ms |

These are deadline-sensitive host measurements, not deterministic score estimates. Report the observed range (baseline 57–61 versus candidate 5–12), rather than attributing every between-run difference to code. The first recovery run preceded the final explicit validated-stop/deadline resets.

The final comparison changes 56 baseline-neutral frames to movement. Independent replay of every one of those commands through the complete 0.6 s real-map geometry validator passes: zero geometry failures. This checks the local model only, not a future match trajectory.

Artifacts in `../game-interface-audit/`:

- `rotation-baseline-conditional.json` and `rotation-baseline-repeat-conditional.json`
- `rotation-historical-partial-conditional.json`
- `rotation-walk-recovery-conditional.json` and `rotation-final-conditional.json`
- matching `*-summary.json` files containing source hashes
- `rotation-evidence.json`, generated by `experiments/rotation_evidence.py`

Reproduce a conditional run with:

```powershell
python ..\game-interface-audit\conditional_replay.py --repo . --trace ..\game-interface-audit\correctness-ab878-20261121-163846\trace.jsonl.gz --label rotation-final --start 38.6 --end 54.1
```

## Final validation

`python -m unittest discover -s tests -q`: **134 passed**. New regressions reproduce expensive late boosted rejection under a deterministic clock; verify that legal walking survives the same budget; retain momentum, energy and charging collision checks; reject promoting a known projectile-risk walk over braking; reset on progress/arrival/intentional stopping/deadline; and use changed navigation immediately. Actual `Bot.act` tests distinguish requested navigation lost to fallback from deliberately selected braking and verify that diagnostics do not force escape actions.

Image: `labubu-score7:rotation`, ID `sha256:1f642252f8d5b2aea57b6b6b1beff6c65e64f4827065a56871b51e18941d60f3`.

The current official checker was run **inside Linux**, using `/kit/check/check.py --map-dir /arena -- python3 -u /bot/bot.py`. The container had one CPU, 512 MB RAM/swap limit, no network, read-only filesystem, a 64 MB writable `/tmp`, uid 65534, and read-only kit/arena mounts. Before the checker, the same container asserted that the actual loaded map had 259 prisms and 774680 terrain samples. This avoids the Windows-host `/arena` to `C:\arena` path issue.

Final checker result: **PASS, 300/300 timely**, zero late responses, wrong ticks, stale queued answers or bad lines. Startup 2928 ms; p50 11.2 ms, p90 26.6 ms, p99 32.5 ms, maximum 34.6 ms. Raw log: `../game-interface-audit/rotation-linux-check.log`. The checker's generic printed parenthetical says it is not a match container; here the checker and its child bot were both inside the explicitly restricted container described above.

Final production source SHA-256:

```text
bot.py       880efec7b27caa52a482737b5a290412e5ef90059b264c20d128bb8eee29d251
tactical.py  b52505f6085b10d7c53737c7b597fa91dbbe8140094739995d091b92361a26bc
arena_map.py 268c47f9f4975fce9d5dee06793a1c4f2c35de32d6678d4b9127b4c29d808524
combat.py    b2d7199a1277ef3731139607b37fe6f409862d553e7ea9f97d8588793383da39
```

This report records pre-submission validation. A subsequent live comparison should measure actual departure from a stall, progress to the next viable route/goal, and resulting resource collection; it must also check that safer deliberate stops and combat avoidance remain effective.
