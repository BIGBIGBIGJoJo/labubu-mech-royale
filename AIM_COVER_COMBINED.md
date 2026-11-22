# Selected aiming plus bounded reload cover

This candidate combines selected aiming `53d8d79502763325184252761ccc9ff7bbf5081e` (official 4.92) with frozen cover `9ddafe2b2f6a2ea08d036c22c8c9353a1eb6413e` (official 4.77). These separate scores do not establish the combination's performance. No movement kernel, reactive recovery, resource changes or policy tuning is included. The two explicit user-constraint amendments below mean this is not an exact unmodified union of the frozen components.

The cover commit merged into the selected aim source without conflicts. The shared `combat.py` gains exactly the cover's existing 13 report-hook lines. All aiming geometry methods remain identical to selected 53d; `Combat.__init__` and `Combat.plan` are identical to cover 9dd. Thus the report now copies the corrected horizontal-barrel gun solution computed by the one ordinary plan call. The cover helper's pure return-point gun probe also calls that same corrected solver. It does not call stateful `plan` again or alter aim/fire/reload permissions.

Two inherited cover edges are deliberately amended to honor the user's instruction to keep moving while exposed and permit brief protected reload stops:

- Arrival back at the firing point ends the cover cycle even if the gun is still reloading. Ordinary combat movement resumes on that same decision; an exposed firing point is not a place to wait for reload completion.
- A cover-induced arrival stop requires `actual_protected is True`; the old return-phase exemption is removed. Removing that boolean alone would be insufficient because a zero-distance return hint could still produce neutral movement, hence the explicit cycle exit above.

All other cover behavior is retained: gun-only admission, fixed return point, current observed target continuity, recovery/zone/resource priorities, bounded complete route/zone/incoming proofs, dynamic cancellation and actual protection before HOLD. Sampled direct protection is not whole-body invulnerability. The known moving-shooter and transient-slew limitations from `MOVING_AIM.md` remain.

Focused host checks cover the 10 horizontal-barrel tests, three report tests, 21 cover-helper tests, 10 cover-integration tests and four new combined tests (48 unique tests). The added combined tests confirm captured 96.4/96.5 reload admission with the corrected solver, reuse of exactly one ordinary solve, a pure return probe that leaves combat state/report untouched, and rejection of gun-only cover for the recorded dual-weapon laser case. The early-return regression shows nonzero ordinary combat stride while reload still has 0.45 seconds remaining; the protected HOLD regression explicitly retains neutral movement. Fixed-clock captured tests certify geometry and state transitions, not actual latency or a completed physical cover cycle.

## Reviewed runtime and Linux validation

Image: `sha256:f1e54237541e111e0f6c67ef1bc802016a64c2bc4a33f11120e558cac45f6da4` (`labubu-score7:aim-cover`, Linux/amd64).

Normalized-LF runtime hashes:

- `bot.py`: `e4f558e32bbbc44ec7e707e7f0f57cbf1ca8d25480522f48e755bf6913924659`
- `combat.py`: `5c54a6d767fba7e99b90c47c66c912a9841dbc59a78fb5b684c392d434160f8c`
- `reload_cover.py`: `28d3afbbaf27032c567cba6a0f866854ac2b134b0983c462312148b1100bf9bd`

Source/image equality, real map 259 prisms/774680 samples, native terrain library, Python movement checks, and both loaded exact geometry caches were verified. Actual world/terrain hashes are `e0302dd4777b527b00a6a4b2e02759915402a23c58839d921e9fcc6d58092445` and `3aa74308e096e36ed29230f135b0f3ff3ae09dfa164c2b687455b4f975b01d38`. The unchanged terrain library is `61973f3bcbbcacfabb5f543e3fe12c47b7d34d31d6c7d48e9932b051a4211dc0`; no movement-kernel library is included. All containers used one CPU, 512 MB memory/swap, no network, read-only root, 64 MB temporary filesystem and UID 65534.

- All 255 Linux tests passed.
- Official checker: 300/300 timely answers, no late/wrong-tick/bad-line answers. p50 17.3 ms, p99 33.7 ms, max 41.1 ms; startup 3810 ms. The checker ran inside Linux with the actual map.
- Cold, fresh-controller recorded states at 96.4/96.5 did **not** complete pair admission within the existing helper budget. Helper times were 9.21/8.04 ms and whole-act times 31.09/30.61 ms. Both retained ordinary nonzero movement. These negatives are preserved; the tests' frozen-clock positive geometry does not establish cold real-budget admission.

For the separate phase probes, a fixed-clock helper proof supplied a pair as **setup only**, then the clock patch ended before untouched real-budget `Bot.act`. With the opponent frozen and the mech placed conditionally at S, HOLD independently rechecked `actual_protected=True` and returned neutral movement: helper 4.21 ms, whole call 24.97 ms. At P in RETURN with 0.45 s reload remaining, the pair ended and ordinary nonzero combat movement resumed: helper 3.39 ms, whole call 28.97 ms. These are conditional state-transition checks, not observed arrivals or a completed physical cycle.

## Complete recorded chronologies

Each replay starts a fresh controller and processes every original observation once through untouched `Bot.act`. There is no seeded pair, clock patch or policy instrumentation during these complete timed calls. Independent geometry and comparisons occur afterward. Recorded future positions do not respond to changed commands, so these runs cannot establish avoided damage, completed shelter travel, kills or score gains.

| Trace | Observations | p50 / p99 / max ms | >32 / >50 ms | Exceptions / gate violations | Admissions |
| --- | ---: | --- | ---: | --- | ---: |
| Integrated 9c | 1594 | 22.54 / 31.41 / 33.25 | 2 / 0 | 0 / 0 | 1 |
| Incoming bcd | 1038 | 30.66 / 31.89 / 32.83 | 6 / 0 | 0 / 0 | 0 |

The complete integrated history admits a pair at 96.5, with helper time 5.41 ms, P `[-68.68, 78.68, -0.6]`, and S `[-69.1355797320, 84.6626789240, -0.4631527139]`. The final unboosted movement `[-0.0759299553, 0.9971131540]` points exactly toward S. The independent route and sampled incoming checks pass. At 96.6 the helper cancels with `shelter_or_isolation_unknown`. This is one actual-budget OUT command, with no observed HOLD/RETURN or completed route in that recorded future. It preserves the earlier cover mechanism after aiming integration; it does not erase the cold-start negatives.

Across all 2632 observations, aim, fire and reload commands exactly match selected-53d records; target and recovery outputs also match. These are commands, not independently identified shots. Against the compatible integrated cover-only 9dd record, 462 aim vectors and two fire-command frames differ (142.6/142.7), with no reload differences; those are the already-reviewed selected-aim effects.

Against selected 53d, integrated has 72 movement, seven boost, 18 goal, three mode and five resource-selection differences, while fallback flags are identical (16 total). Incoming has 104 movement, eight boost and 48 goal differences, no mode/resource/target differences, and 18 differing fallback flags (44 baseline versus 50 candidate). The controller's wall-clock deadlines make outputs timing-sensitive even when cover never activates. These differences are disclosed without attributing them all to useful policy changes. Some whole calls exceed the internal 32 ms target, although none exceed the official 50 ms response budget.

No combined private-game or official-score result exists at validation freeze. Runtime/component provenance and full observations are retained in scratch `work/game-interface-audit/aim-cover-source-union.json`, `aim-cover-runtime-manifest.json`, `aim-cover-focused-linux.json`, `aim-cover-conditional-linux.json`, `aim-cover-f1e542-{integrated,incoming}.json` and `aim-cover-chronology-comparison.json`. The inherited incoming driver's generic limit string incorrectly calls its recorded policy 9c; its actual trace is incoming bcd, as identified here and by its verified trace hash. Executed artifacts remain unchanged.
