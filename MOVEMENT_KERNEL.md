# Exact movement predicate experiment

Base: `b0e296c356cd636ed5576b0152429dea22ddcffb`, selected official score 4.77.
The goal is to let the existing tactical planner validate more candidate
trajectories within its unchanged deadline. Navigation intent, rollout physics,
costs, candidate ordering, aiming, and firing are unchanged.

The earlier restricted-runtime profile found grounded collision checks much
more costly than movement integration. A separate local-steering experiment
changed useful navigation directions and produced seven new stops in a paired
recorded-input comparison. That experiment is excluded here.

`native_map.ArenaMap` subclasses the unchanged Python map and replaces only
`move_clear` when the compiled predicate is available and compatible. The
kernel retains the existing directed terrain grade, horizontal capsule/edge
test, sampled support height, step/slope rules, holes, overhangs, contact
epsilon and arena boundary checks. It retains the original behavior of
ignoring the supplied endpoint Z; this predicate does not certify arrival at
that height. Public point/support queries remain Python implementations.

The C++ world borrows a strongly retained terrain buffer and copies immutable
loaded prism data. A finalizer frees the native world. Missing symbols,
unsupported inputs, replacement geometry/configuration or customized map
methods use Python. Nested in-place mutation of loaded world geometry is
outside the map's existing immutable-world contract. Static cache source keys
remain those of the unchanged Python geometry, and cache payloads are unchanged.

The build disables fast math, floating-point contraction and builtin `pow`
optimization. Distance is calculated by the original CPython `math.hypot` and
passed to C++ so terrain grade and sample counts retain its rounding behavior.
Contact-boundary parity and the compiled external `pow` call are validation
requirements, rather than conclusions from source inspection.

## Validation

Independent source and numerical-parity review passed. Tested runtime image:
`sha256:4526a76a1b993d289ad8abf7a331612ca5408b393c719574f1f6feec4a8caa1c`.
The runtime native library is
`c092ae557b3cb3572b9d99cf64550f4442bde60f3ff3831e084b3b65727341c3`.
Both original static caches load, the real map has 259 prisms and 774680 terrain
samples, all native exports are present, and the library calls external `pow`.
No production source changed after the image was built.

The restricted Linux suite passed 219 tests. A final 13-test focused run adds
one functional sampling-boundary regression: 220 unique test methods were
covered without repeating the unchanged full suite. Cases include holes,
corners, bridges, roofs/drops, directed slopes, body growth, contact nextafter
values, map margins, fallback and the inherited ignored-end-height behavior.
The official checker completed 300/300 replies with no errors or late replies:
p99 21.6 ms, maximum 24.7 ms.

Eight supplied proposals at recorded times 97.2 and 99.5 produced identical
complete corrected paths or rejection results (four each). All 87 observed
native calls returned a complete 0/1 result, rather than silently falling back.
Alternating measurements reduced the 97.2 walking-path check from 5.354 to
0.903 ms and the 99.5 walking check from 7.202 to 2.110 ms. Invalid proposals
remain invalid. These are conditional path checks, not physical movement.

Two complete unchanged observation chronologies ran with uninstrumented
`Bot.act`, one CPU, 512 MB, a read-only root and no network:

| Recording | Decisions | p50 / p99 / maximum ms | Errors / >50 ms |
| --- | ---: | --- | --- |
| Integrated 9c | 1594 | 19.437 / 31.628 / 37.924 | 0 / 0 |
| Incoming cover bcd | 1038 | 26.981 / 31.363 / 36.976 | 0 / 0 |

Against the existing exact-b0 integrated reference, tactical fallbacks decrease
from 16 to 9 and zero-movement commands from 297 to 289. All 1594 aim, fire,
reload, take and drop decisions match. The seven new stops caused by the held
local-steering experiment remain moving with valid rollouts here. Four b0
stationary frames at 97.3, 97.4, 97.9 and 98.0 become moving. At 27.0, the sole
moving-to-neutral change is a completed, valid braking choice with lower
unchanged cost (104.406 versus 124.430), not a failed search.

Faster primitives change the work completed by deadline-limited search:
176 movement, 11 boost and 103 goal-coordinate values differ in the integrated replay.
This is not a claim of action identity or an unchanged physical future.
The incoming recording's previously stationary 99.2–100.3 interval now has
nine nonzero commands out of twelve, but this is not proof that the changed
bot escapes in a new match. Its high-level source differs from the recording.

Neutral fallback rollouts can remain invalid while braking: integrated 17.8
and 81.1 match the reference; incoming 97.0 and 97.1 are also fallbacks. Seven
integrated lease cases lacked the grown body data for separate posthoc path
certification and were left unknown. The maximum whole-call times exceed the
internal 32 ms target while staying below the 50 ms interface limit. Available
telemetry cannot attribute each overrun to a specific primitive or scheduling
delay. These limitations are retained, not reported as proven protection.

Scratch manifests, complete replays and the independent review are recorded
in `MOVEMENT_KERNEL_VALIDATION.md` and `MOVEMENT_KERNEL_VALIDATION_REVIEW.md`.
No match or official score has yet been obtained for this experiment. Faster
checking alone does not establish better escape, crossfire avoidance or score.
