# Resource progress attribution

A newly selected cube could inherit an unrelated positioning stall and be blacklisted before the bot tried to reach it. The captured navcache state at 66.6 s selects cube 5040, 35.8 m away on a verified clear movement segment, then immediately excludes it for 12 seconds. It is eventually collected at 82.7 s. This event occurs once in 13 current private traces.

The fix records movement against the preceding action's resource identity. Blacklisting additionally requires failed attempted progress for a continuous same-resource history spanning over 1.3 s. Global stuck detection, jumping, navigation, combat, and resource valuation are unchanged. This avoids both immediate inherited penalties and the same error one frame later, while retaining genuine blocked-resource blacklisting.

Validation: 130 tests pass on the host and in Linux, including captured state/followups with real map geometry and blocked-resource/preemption controls. A full-prefix restricted Linux replay of 828 observations under the actual decision deadline changes cube 5040 from a baseline 12-second blacklist to continuous pursuit at 66.6–82.6 s; no candidate blacklist or errors occur. Recorded positions remain fixed, so no earlier collection, placement, or score gain is asserted.

The checker and child bot both run inside the image with a real `/arena`, one CPU, 512 MB, network disabled, read-only root/map and tmpfs `/tmp`: 300/300 timely responses, zero bad/wrong/late answers, readiness 2868 ms, p50/p90/p99/max 11.8/29.0/35.5/38.8 ms. Candidate full-prefix latency p50/p99/max is 21.21/33.45/34.37 ms, with none >50 ms. `git diff --check` passes. No live game or official submission was run for this candidate.
