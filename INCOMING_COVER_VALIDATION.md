# Incoming exposure during recovery

Base: selected builders-4 entry `b0e296c356cd636ed5576b0152429dea22ddcffb`,
score 4.77. This isolated candidate changes recovery destination exposure and
the bounded candidate scan. It preserves the base's collection lease, geometry,
navigation caches, tactical movement and combat policy. It does not contain the
duel controller, near-full laser correction, or experimental route-retention
helper.

The previous recovery score checks our muzzle toward the opponent. That can
be blocked by a low wall while the opponent can shoot our upper body. Recovery
now samples the opposite direction, from the opponent's modeled muzzle toward
our body at each proposed destination. Missing geometry, exhausted budgets and
unmodeled mortar trajectories remain exposed/unknown, not protected. Samples
are bounded to four per opponent and 64 new rays per observation; immutable
exact-endpoint ray results are cached. This is sampled exposure, not a proof
of full-body shielding or approach-route safety.

The scan rechecks the origin and held goal, then rotates through remaining
candidates under the existing deadline. Definitely unreachable candidates
advance the cursor; unresolved route/exposure work remains for the next pass.
Ground-route classification and pending-height revalidation remain unchanged.

## Validation

- 238 tests passed in Linux/amd64 with one CPU, 512 MB memory/swap, no network,
  read-only filesystem, uid 65534 and the actual 259-prism/774680-sample arena.
- Loaded Python/binary files matched the reviewed source; native geometry and
  both caches were asserted loaded.
- Official checker: 300/300, no late/invalid replies; ready 3601 ms,
  p50 11.2 ms, p99 31.5 ms, maximum 32.1 ms.
- Full C1 chronological replay: 1045 actions, no errors; p50 23.304 ms,
  p99 31.888 ms, maximum 32.969 ms. 31 recovery scans, maximum 21 new rays.
- Image: `7a8df00a62b13004a00e0727befeb39dbce4e11a2610fdf368ad13cf5be1bd00`.
- Reviewed bot LF SHA256:
  `eccedf156d1b7439e9dea8dc4c8eaf212c41a762d7e6725516dacf4fe59e34e3`.

At 95 seconds the selected destination remains exposed. At 97 seconds the
selected destination blocks the sampled incoming rays and has a separately
validated eleven-node route with valid start/internal/end connections. At
101 and 102 seconds the selected destination also blocks the samples, but
requires a 34-node detour despite being only 33.59 m away. Euclidean distance
does not price that detour correctly. A previously considered direct incumbent
is exposed at 102 seconds and must not be retained as protected cover.

These fixed-observation results verify decisions and geometry, not alternate
movement, healing, survival or score. The route-retention experiment was
excluded because its full C1 replay produced no verified retention. A scoring
benefit for this simpler candidate remains unestablished.

Independent review confirmed that `zone_resource.py`, geometry/reachability,
combat/tactical files and both binary caches match b0 exactly. Removing the
three exposure bookkeeping additions from `Bot.act` gives the base AST; lease
admission, continuation, charge, body growth and exit-reserve logic remain.

Audit artifacts in the sibling `game-interface-audit` directory:
`incoming-cover-linux-tests.log`, `incoming-cover-checker.log`,
`incoming-cover-replay.json`, and `incoming-cover-independent-review.json`.
