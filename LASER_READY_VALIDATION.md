# Release upgraded lasers at the observed charge plateau

An upgraded laser can report charge `0.56` against a live charge requirement
of `0.563`, or `0.42` against `0.422`. The former exact comparison never marks
these states full. It consequently misses both the normal aligned release and
the controller's bounded hold timeout, retaining the movement slowdown.

The isolated change adds a named 0.006-second near-full tolerance, gated by the
weapon's minimum charge. The same predicate controls full-charge hold timing
and release. Alignment, emergency release, lethal partial shots, and new-cycle
reset behavior remain in place. This is a bounded release policy motivated by
observed numbers, not a claim that the engine universally rounds observations
to a particular precision. It can release up to six milliseconds early.

This candidate starts from the current builders-4 selected entry `b0e296c`
(4.77). It changes only `combat.py` in production. The duel controller is a
separate experiment.

Evidence from 16 existing private traces (15,648 observations) found 17
sustained near-full plateaus: fifteen at `0.56/0.563`, two at `0.42/0.422`.
Eight lasted 1.9 seconds with earlier hold commands true, followed by zero charge
and cooldown at two seconds, consistent with configured automatic release.
Four of those observations also contain an own laser hit; four do not.
There is no claim that an earlier release would necessarily hit.

Validation:

- 210 tests pass in restricted Linux: one CPU, 512 MB, no network, read-only,
  unprivileged user, actual arena data, compiled geometry and both caches.
- Image/source equality checked after CRLF-to-LF normalization.
- Official checker: 300/300 responses, zero late/invalid responses; p50 10.3 ms,
  p99 28.2 ms, maximum 29.0 ms, ready in 3593 ms.
- Runtime image: `127b87274f4d93a04ec10ac24730fa75ab6ec93a77f001dfea33519f732de9d5`.

The scoped tests check aligned release, an unaligned bounded hold and new-cycle
reset, genuinely undercharged states, and the minimum-charge guard. Official
scoring is still required; private evidence does not establish a score gain.
