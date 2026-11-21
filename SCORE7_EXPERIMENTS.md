# Score-seven experiment ledger

## Verified baseline

The authenticated official panel was inspected during this task. Receipt
BB-12F2E201 confirms commit `39b6d509af8e82b0ceb9e1c430dd964674d7488e`
scored **4.75** and was automatically selected as the best final entry.
Later submissions shown in the panel remained below that score.

### Correction to older container measurements

Running the official checker from Windows with `--map-dir /arena` resolves that
path to a Windows location before passing it to the Linux bot. Because the map
loader permits a fallback, a protocol PASS can then omit real geometry work.
Run the checker inside Linux and verify map availability. This correction also
applies to the initial review's 13.8 ms Docker maximum.

The baseline was rechecked fully inside Linux: preflight loaded 259 prisms and
774,680 terrain samples; 300/300 replies were timely, p99 32.6 ms, maximum
33.2 ms, ready in 3,067 ms. The container had one CPU, 512 MB/no swap,
128 processes, no network, read-only root, 64 MB `/tmp`, uid 65534 and a read-only
arena. Checker and bot shared that resource limit.

## Candidate 1: geometry and firing correctness

Changes:
- Check further tactical candidates when high-ranked candidates collide;
  rejected paths no longer consume the shortlist of usable trajectories.
- Validate actual gun/laser rays to the target's near body surface while the
  torso turns. Check each gun launch possible within the held action.
- Reuse only identical adjacent terrain endpoints inside a single ray query.

Verification before publication:
- 138 regression tests passed; no whitespace errors.
- Docker image built from the candidate runtime sources.
- Official checker entirely inside restricted Linux: 300/300 replies on time,
  no missing, stale, wrong-tick or invalid replies; p50 11.1 ms, p99 32.1 ms,
  maximum 33.0 ms; ready in 2,944 ms.
- Additional synthetic dense diagnostic on the actual map: 120 cases over
  12 locations, 15 other mechs and 30 projectiles. No exceptions or policy
  decisions over 50 ms; p99 31.98 ms, maximum 34.44 ms. This is computation
  evidence, not a match or a full transport timing measurement.

Official result: pending. The target score of 7 is not yet achieved.
