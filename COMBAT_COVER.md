# Gun-reload cover experiment

This candidate starts from `b0e296c356cd636ed5576b0152429dea22ddcffb`, the retained economy/routing bot with official score 4.77. It adds a short shelter-and-return movement cycle during an observed gun reload. It has no new official score or demonstrated live health benefit at this validation point.

Admission requires exactly one equipped gun, a currently observed live mech target, grounded terrain travel, and an existing clear gun solution at the current position. Recovery, zone rotation, resource objectives, collection leases, the existing stuck response, and a recent known attacker absent from observation all take priority. A ready secondary weapon is never sacrificed for this experiment because every secondary excludes admission.

`Combat.plan` runs once. Its new reset-per-call report copies the gun solution already computed for the actual observation; it does not change the weapon solver or fire commands. A cycle may keep the same currently observed target through its own outgoing LOS loss. Another ordinary target wins. Structural changes are checked before retaining a target. The temporary movement goal does not overwrite the ordinary held goal or its expiry.

The planner pairs the current potential firing point P with a nearby shelter S. It searches at most 128 collected wall anchors within 20 m, interpolating toward them by at most 6 m. Its cursor keeps an unfinished candidate after a budget-UNKNOWN result. The local limit is 8 ms and the caller retains the existing global 32 ms deadline with 13 ms reserved afterward. Exact static route proofs are cached only within one immutable map instance, using exact endpoints and actual body dimensions. Incoming samples are cached only within the same call at identical points and unchanged actors.

Both directed ground connectors require body clearance, the existing support-height progression, correct endpoint feet height, and `move_clear`. A clear segment alone does not certify a roof descent. The visible-cube pickup corridor is excluded to avoid entering a passage immediately before body growth; continuation checks current-to-S, S-to-P, and current-to-P. Body growth, loadout changes, airborne motion, excessive displacement, a failed fresh proof, and observed lack of progress cancel the cycle. Cancellation prevents immediate re-entry during the same partial reload.

Protection means five direct incoming samples are blocked for each currently observed direct-weapon mech: three center heights and two upper side points. Enemy muzzle dimensions use configured base values scaled by observed cubes; our body uses live stats and cubes. NPCs, unknown loadouts, mortar, and lightning exclude this first version. Other observed opponents must also be screened at P. This is a sampled geometry model, not complete body protection, protection from unseen actors, or prediction of enemy upgrades or future movement. Existing tactical collision and projectile handling remains authoritative.

The OUT phase becomes HOLD only after observed proximity and actual-position protection. HOLD does not imply regeneration: a normal gun reload is shorter than the quiet regeneration delay. The return starts before reload completion using an estimate that includes walk travel, worst-direction braking displacement and time, acceleration/deceleration, decision delay, and aim slew. Actual position, not elapsed ETA, determines arrival. Tactical deviations and target motion prevent this estimate from being an arrival guarantee. The small policy bounds are experimental: 0.35 m arrival, 0.3 m progress, and a 1 s no-progress limit. The inherited generic 1 m/1.5 m navigation stop is bypassed only for these fully proved short connectors; tactical movement still has final authority. Protected arrival can stop, while an exposed near-S position retains its movement hint.

Zone checks use the announced moving circle. Extending beyond the announced shrink end is allowed only when the live shrink start/end and next radius match the configured phase schedule; the known next circle then remains valid through the following configured hold. No unannounced next center is assumed.

## Final runtime validation

Production image: `sha256:0a1f368e4390ab3373fb3346644a5d35248afbc3a7442255abe669086f29da9e` (`labubu-score7:combat-cover-braking`, Linux/amd64).

Normalized-LF runtime hashes:

| File | SHA-256 |
| --- | --- |
| bot.py | e0b12361208a73eb7db2a67a4184471ed0963fb95f2d4c6db1813de5e08049c6 |
| combat.py | da8d48056912496b8ce9e3edb68d481dcf3d669baf6bf5cb727cae86ab82384f |
| reload_cover.py | 9efbfb1829b52ddb8f309713824b8e6b1554ce7add5b4d3be43b2a7dfaf35c80 |

The geometry modules, native kernel, and navigation/reachability assets remain those of b0. Validation used one CPU, 512 MB memory/swap, no network, a read-only root filesystem, a 64 MB temporary filesystem, and uid 65534. Preflight asserted the real map (259 prisms and 774,680 terrain samples), loaded native geometry and both caches, and equality between every copied runtime Python/binary file and the reviewed source. Python equality normalizes CRLF to LF.

- All 239 Linux tests passed, with no skips. Focused cover tests include the recorded 96.4 geometry, root priorities, target continuity, no changed fire action, body/loadout transitions, unsupported threats, incomplete proof/cursor behavior, phase/arrival guards, zone schedule matching, cube growth on a deviated return, stuck-plus-jump precedence, and braking estimates.
- The official checker ran inside Linux against `/arena`: 300/300 timely answers, zero late/wrong-tick/bad-line answers. Timing was p50 10.9 ms, p90 19.1 ms, p99 27.1 ms, maximum 33.3 ms; startup was 3479 ms. These are measured on this machine under the stated restrictions.
- An unchanged full chronological replay of the 1594-observation `integrated-9c440e4-20261121-190956` private trace completed with no exceptions or observed cover-gate violations. Timing was p50 23.644 ms, p99 31.566 ms, maximum 34.398 ms; five calls exceeded the internal 32 ms planning target and none exceeded 50 ms.
- That final replay admitted one cycle at 96.5 s. The helper used 6.152 ms, proved a 6 m bidirectional terrain route, and selected unboosted movement directly toward S. P had 3/5 incoming samples clear; S had 0/5. The next fixed observation canceled the cycle after its fresh shelter proof failed. This shows budgeted admission and movement, not collection, arrival, completed live sheltering, damage prevention, or score gain.

The captured geometry/state unit tests freeze the clock to isolate correctness; they are not latency evidence. The full replay uses untouched `Bot.act` and real clocks, but its future observations remain the recorded future rather than the consequences of the new actions.

An earlier reviewed image `4172172...` had the same admission/next-observation cancellation before the narrow braking-distance correction. Its separate controlled continuation, with the opponent explicitly frozen and the self position/reload explicitly changed, exercised protected HOLD and RETURN. Those synthetic transitions are supplementary state-machine evidence, not an observed live outcome for the final image.

Audit artifacts are maintained outside the submitted source: `combat-cover-braking-linux-tests.log`, `combat-cover-braking-checker.log`, `combat-cover-braking-runtime-manifest.json`, and `combat-cover-0a1f368-integrated-prefix.json`. No private game or official submission is included in the evidence above.
