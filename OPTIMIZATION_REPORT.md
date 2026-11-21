# Why the score has not yet exceeded 4.75

The first aggressive entry, `219fde2` / BB-A29B40E8, scored **4.63** across the
official 48-match practice set. The best retained entry, `39b6d50`, scored
**4.75**. The target remains **6.0**. Private matches have different opponents
and rules of interaction, so their placements are not estimates of this score.

The official panel exposes an aggregate result here, not the individual match
traces needed to attribute every lost point. The following are demonstrated
controller failures in recorded diagnostics. Their effect on official score
must be measured by submitting the corrected candidate.

| Finding | Evidence | Optimization decision |
|---|---|---|
| Narrow ground exits are absent from the coarse route graph | A recorded pocket has only two reachable 5 m grid cells, although exact body sweeps establish a curved walking exit. The original controller stayed stationary for 15 seconds. | Add bounded incremental local routing only after confirmed failure/stall; retain all collision and tactical checks. |
| A zone goal can be projected into solid geometry repeatedly | The recorded 85.5–96.5 s goals include an exact radial future-circle projection that fails body clearance. Goal retirement can be bypassed by projecting the next goal back into the failed area. | Implemented validated projection/alternatives and repeated-goal regression tests. |
| Local motion alone does not resolve disconnected routing | Half-throttle candidates move initially, then stop at the same short route endpoint. Simple frontier and arrival-tolerance changes also fail. | Require sustained mechanical continuation, including search time and reconnection to a larger coarse component. |
| Firing is now proactive and maintains verified finishes | The corrected private trace contains two confirmed kills, stable finishing targets and no demonstrated budget-only missed usable target. | Preserve firing while testing movement. Do not change aim prediction to compensate for private network delay. |

The previously submitted `219fde2` candidate passed 422 tests and 580 host
schema/timing stress decisions. Its earlier Docker check used a Windows path
rewrite and did not establish map-enabled container timing; the corrected
Linux checks for the current candidate are recorded in VALIDATION.md. Its corrected
private diagnostic had no policy errors or decisions above 50 ms. These checks
do not prove that every official action met its deadline, but they provide no
current evidence that a broad reduction in tactical work would improve score.

The comparison with the former best also checked NPC farming, lightning entry,
reloads and resource memory. Seventeen recorded matches did not support
loosening NPC health/cube gates. The observed extra lightning restrictions did
not demonstrate a lost kill; the clearest weak opponent was subsequently
eliminated. Resource-memory and optional-reload differences were brief. These
are not sufficient reasons for a broad rollback or more aggressive thresholds.

The next candidate isolates movement recovery and any independently reproduced
goal-validity correction. It must pass full regressions, exact container checks,
timing stress and a fresh frozen private diagnostic before official scoring.
The best accepted entry remains selected until a higher official result is
verified. A successful local escape is not a promise of a higher score.
