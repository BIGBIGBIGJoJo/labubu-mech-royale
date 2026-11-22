# Reactive recovery after an unseen weapon hit

Base: selected aiming candidate `53d8d79502763325184252761ccc9ff7bbf5081e` (official 4.92). The movement kernel and aim-plus-kernel combination are excluded. This candidate has no private-game or official-score result.

The recorded kernel-private match contains a stationary recovery hold from 160.6 seconds. Healing raises HP before unseen actor 14 deals three observed weapon hits at 164.3, 164.5 and 164.7, totaling 715.4 damage. The occupied location is therefore no longer a quiet healing opportunity. Merely refreshing the ordinary recovery search still selects the same position; its candidate set has no lateral or away alternative that meets the existing future-zone rule.

This change adds three bounded local candidates at `walk_speed * tactical.horizon`: directly away from the observed damage bearing and the two perpendicular directions. It does not infer an enemy position or claim the new location provides protection. The helper owns a goal only after completing the route and zone checks. It never forces movement; ordinary navigation, tactical collision/projectile checks, boosting and aim/fire rules remain authoritative.

## Admission and lifecycle

Admission requires terrain-grounded recovery, no resource/lease/urgent rotation, no observed threat actors, and a held recovery goal inside the existing 1.5 m arrival radius. Previous movement intent must be neutral, observed XY speed must be at most 1 m/s, and no laser may be charging. Evidence must be a positive, finite, non-zone weapon-damage event with a finite bearing and a known attacker ID. The existing active-contact window, `min(3, regen_delay)`, must contain exactly that one actual attacker. An ID-less hit retains uncertainty for the same window; a later bearing-less weapon hit invalidates paired bearing evidence. Zone events cannot refresh the old weapon-bearing timestamp.

Each candidate must fit the current full body and conservative visible incidental cube growth, including at the start. More than 256 visible cubes rejects the scan, matching the existing resource planner bound. Endpoint terrain scope, sampled directed terrain support/end height and full-body `move_clear` must all pass. The existing 22-second future-zone body-plus-2 m filter and ordinary position cost remain; the existing walking arrival model plus four-second zone reserve must also complete inside the currently announced phase. Stationary and toward-bearing endpoints are rejected. All work uses the existing safe-goal deadline, global 32 ms minus the existing 13 ms navigation/tactical reserve; no deadline is extended.

One successful relocation consumes one actual hit. An unfinished attempt can retry while the hit stays fresh, but a successful goal is retained rather than regenerated each observation. Retention rechecks current evidence, body, terrain route and zone constraints. New multiple/unknown/bearing-less attackers, a new bearing toward the goal, body/scope changes, expired evidence/TTL or an incomplete/invalid proof cancels ownership. A canceled owned goal is expired before ordinary selection, so it cannot survive as a held recovery goal. A successful goal has the existing 1.2 s recovery TTL, bounded by evidence freshness. Reaching it does not rearm the same hit. New actual hits can rearm only after the stopped-at-goal gates apply again.

When no candidate completes, the original ordinary refresh decision is preserved, including expired or out-of-zone goals. No reactive relocation is admitted during quiet recovery without fresh qualifying damage. This is deliberately limited to one successful relocation per hit; it is not continuous unseen-attacker evasion. Diagnostics can overwrite a cancellation reason during subsequent same-frame selection, so lifecycle review also checks stored ownership and the actual selected goal.

## Exact runtime validation

Image: `sha256:6f1b88a0984386b9b0d3ae2ffe8050d8c3cc7bb3a9d03857f7c88ae7eb713d2f` (`labubu-score7:reactive-recovery`, Linux/amd64).

Normalized-LF source hashes:

- `bot.py`: `b72dda0e9969d1b70913be2a12daf3cb10dde061c5ee9694b63c47e59e230b21`
- `reactive_recovery.py`: `e474701a8aff8d3b3e1d0e0cf0595a73f65ccfbea168ec81b33019ad947c2a19`
- Unchanged `combat.py`: `cd5f42327fe56a8fe9c6b282e8b5c470338519c255cdda40a0aa8a1fdd66fb45`

Runtime/source equality, native terrain library, Python `arena_map.move_clear`, both loaded exact geometry caches, and map 259 prisms/774680 samples were asserted. Actual map bytes were checked: world JSON `e0302dd4777b527b00a6a4b2e02759915402a23c58839d921e9fcc6d58092445`, terrain `3aa74308e096e36ed29230f135b0f3ff3ae09dfa164c2b687455b4f975b01d38`. The unchanged native terrain library hash is `61973f3bcbbcacfabb5f543e3fe12c47b7d34d31d6c7d48e9932b051a4211dc0`; there is no native movement library.

All validation containers used one CPU, 512 MB memory/swap, no network, read-only root, 64 MB temporary filesystem and UID 65534. No Windows-host checker was used.

- 234 Linux tests passed. Seventeen focused tests cover the recorded terrain route, quiet controls, event pairing and unknown attackers, consumed-hit/rearm rules, cancellation plus actual fallback selection, unchanged ordinary refresh after failure, cube/start-body bounds, and inertia/charge/priority negatives. Fixed-clock fixture tests establish geometry/policy, not runtime speed.
- Official checker: 300/300 replies on time, no late/wrong-tick/bad-line replies; p50 10.0 ms, p99 24.6 ms, max 27.5 ms; startup 3100 ms.
- Real-budget captured-state restores at 164.3/164.5/164.7 admitted lateral movement in 8.39/7.39/7.70 ms total `Bot.act`. Fresh posthoc full-ground/tactical checks passed. Quiet controls at 163.7/164.2 retained neutral movement. Restores reproduce observed controller hold context, not full chronology.

## Complete chronologies and limits

Each complete replay starts a fresh controller and calls unchanged `Bot.act` once per untouched recorded observation. State inspection and derived comparison occur outside the timed call. These fixed future observations do not simulate the changed commands or establish arrival, reduced damage, kills or a score gain.

| Trace/runtime | Observations | p50 / p99 / max ms | >32 / >50 ms | Exceptions | Admissions |
| --- | ---: | --- | ---: | ---: | ---: |
| Integrated 9c / candidate | 1594 | 23.18 / 31.65 / 32.17 | 3 / 0 | 0 | 0 |
| Incoming bcd / candidate | 1038 | 30.68 / 31.80 / 39.93 | 9 / 0 | 0 | 0 |
| Kernel 174 private / candidate | 1723 | 14.38 / 31.11 / 36.44 | 3 / 0 | 0 | 1 |
| Same kernel trace / exact selected 53d | 1723 | 14.16 / 30.98 / 32.23 | 1 / 0 | 0 | 0 |

Across all 4355 candidate observations, aim, fire and reload commands exactly match the corresponding selected-53d records. These are commands, not independently verified shots. No source aiming or firing rule changes are included.

The kernel-trace chronology admits one goal at 164.3: `[56.1466246193, -157.9541809045, 1.3540209243]`. It retains that exact goal through 164.8, producing six consecutive lateral movement commands `[0.9901875545, 0.1397447922]`, with ordinary boost and no jump. Whole-act times across those frames are 6.10–11.91 ms. New same-attacker bearings at 164.5 and 164.7 do not cause alternating cancellation or stops. Quiet 160.6–164.2 remains unchanged. At 164.9 the endpoint's existing 22-second body margin falls from 2.169 m to 1.758 m, below the required 2 m. The route is canceled and ordinary recovery selects its original northward destination; there is no re-admission. Six goal changes correspond to the six active frames. Compared with exact 53d on this trace, total movement/boost changes are 27/8, with zero mode/target/resource/recovery/fallback differences. Some movement differences outside activation reflect deadline-dependent planning.

The first two traces never meet this narrowly scoped trigger. Their combat commands remain identical, but timing-dependent movement and goal decisions differ: integrated 68 movement/16 goal changes, incoming 156 movement/112 goal changes. Integrated also has seven resource-selection and five mode differences; unchanged priority order is a source property, not an assertion of identical replay outputs. Incoming tactical fallbacks are 48 versus 44 in the older selected-53d recording: 15 newly true and 11 recovered frames, a net increase of four. Integrated fallbacks remain 16 in total. This is disclosed rather than attributed to a beneficial behavior change. Maximum time remains below the official 50 ms response limit, but some calls exceed the controller's internal 32 ms target. No claim of general deadline or movement improvement is made.

Scratch provenance and full frame data are retained under `work/game-interface-audit`: `reactive-recovery-runtime-manifest.json`, `reactive-recovery-focused-linux.json`, `reactive-recovery-6f1-{integrated,incoming,kernel}.json`, `reactive-recovery-53d-kernel-baseline.json`, and `reactive-recovery-chronology-comparison.json`.
