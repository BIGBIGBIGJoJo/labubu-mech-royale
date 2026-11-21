# Reuse the caller's existing tactical time budget

Base: `0fad6304773c811f7eb598e5f334a13a5d9220c7`, the isolated exact native
terrain-ray candidate. This branch contains no navigation cache or other policy
candidate. There is no new match score for this scheduling change.

## Change

`Bot.act` already supplies a deadline 32ms after the decision begins. Previously,
the tactical chooser imposed an additional 14ms local cap even when the caller
had more time left. It could abandon a valid collision check while leaving
allocated decision time unused.

The chooser now honors a supplied caller deadline, retaining the existing 1.5ms
guard. Calls without a deadline retain the 14ms default. The global 32ms target,
6ms cheap-scoring phase, maximum six geometry attempts, all costs, movement
physics and collision checks are unchanged. No CPU, memory or competition
timeout limit was raised. Only the deadline expression and its explanation
change in production code.

The existing limits are cooperative: an individual operation can run beyond a
deadline before the next check. This change does not make 32ms a hard runtime
guarantee, and the external competition deadline remains 50ms.

## Conditional evidence before implementation

A read-only function variant changed only the deadline expression inside the
unchanged terrain image. Complete C1 observation prefixes produced:

| Version | Valid paths / decision | Fallbacks | Geometry timeouts | p99 / max ms |
| --- | ---: | ---: | ---: | --- |
| Original local cap | 2.106 | 146 | 519 | 32.13 / 38.72 |
| Supplied caller deadline | 2.648 | 118 | 335 | 31.99 / 40.42 |

Both processed all 1,045 observations with zero errors and zero computations
over 50ms. These are fixed-observation replays, not simulated outcomes.

At C1 86.2s, a paired probe reused identical captured inputs, last-direction
state and 25.51ms caller availability. In three alternating-order repetitions,
the original chooser completed 1–2 valid paths and the variant completed four.
The selected action was unchanged; more validation does not necessarily mean
a different or better action.

At C1 68.1s, only 14.97ms remained in the captured call. The original completed
1–2 valid paths, the variant 2–3; the gain was smaller. The earlier performance
audit also found that most chooser time at this point lay outside geometry.
Using the caller's time helps other remaining work too, but cannot eliminate
its computational cost.

## Production-image validation

Image: `labubu-score7:tactical-budget`, manifest
`sha256:f083fb541919a75a60ee089f87ad74bd64f27619f728f3185213ac83ea90205a`.
Every run used one CPU, 512MB, no network, read-only root, uid65534, a 128-process
limit, 64MB temporary filesystem, and the real map. Replay asserts all 259 map
prisms and the loaded native terrain kernel.

- **133 tests pass inside Linux with the native library required.** Three new
  deterministic scheduler cases verify six completed checks when the caller
  provides time, the unchanged standalone default, and respect for a shorter
  caller deadline. A simulated deadline-aware 5ms collision check avoids sleeps
  or machine-speed assumptions. Host tests also pass; the six native-only cases
  skip on Windows and are exercised in Linux.
- **Fresh official checker: 300/300 timely**, no malformed, wrong-tick, stale or
  late replies. Ready 3108ms; p50 10.6ms, p90 19.4ms, p99 30.0ms, max 32.3ms.
  Both checker and bot run inside Linux with `/arena`, avoiding host path rewriting.

| Fixed-observation run | Frames | Valid paths / decision | Fallbacks | Geometry timeouts | p50 / p99 / max ms |
| --- | ---: | ---: | ---: | ---: | --- |
| C1 production 1 | 1,045 | 2.730 | 109 | 306 | 25.09 / 31.87 / 32.41 |
| C1 production 2 | 1,045 | 2.678 | 121 | 325 | 25.13 / 32.00 / 36.47 |
| recovery production | 593 | 3.411 | 6 | 8 | 7.29 / 30.90 / 31.58 |
| recovery original-cap control | 593 | 3.260 | 6 | 51 | 7.35 / 30.72 / 31.64 |

All production and control rows have zero errors and zero computations over
50ms. C1 production runs have 5 and 12 computations over the internal 32ms
target; the original-cap C1 control had 13. Recovery has none. Overall C1 median
compute time increases because the chooser uses available time to validate
additional alternatives. Recovery's fallback count is unchanged despite fewer
geometry timeouts. Do not describe this as a universal fallback reduction.

The two production C1 runs differ on 121 movement/boost commands and on zero
fire commands. Deadline-sensitive searches can still vary between runs. The trace
does not react to changed commands, so additional validated paths and fewer
fallbacks establish scheduling coverage only, not improved damage, survival,
placement, or official score. No private game was launched for this candidate.

## Reproduction and provenance

Local audit artifacts outside the submission repository:

- `compare_tactical_budget.py`: full-prefix metrics and paired fixed-input probe.
- `tactical-budget-conditional-c1.jsonl`: pre-implementation original/variant comparison.
- `tactical-budget-production-c1.jsonl`: two production-image C1 prefixes.
- `tactical-budget-production-recovery.jsonl` and `tactical-budget-control-recovery.jsonl`.
- `tactical-budget-native-tests.txt` and `tactical-budget-official-check.txt`.

Traces: `correctness-ab878-20261121-163846/trace.jsonl.gz` and
`recovery-e7c6248-20261121-174602/trace.jsonl.gz` in the workspace audit directory.
No private trace is embedded in the repository.

Production `tactical.py` SHA256:
`af03b12660080d13c8d7b9ed9ad0e3956c2fe718af5916a1b7b219a106dff69f`.
Python runtime manifest SHA256 (sorted `sha256  filename\n` for top-level files):
`1a0fe239abe014d7ae58c3904017ab3123fe69f1ce6e769887c814cd33017643`.
