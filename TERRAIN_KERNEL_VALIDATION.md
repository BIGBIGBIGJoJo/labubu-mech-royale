# Exact compiled terrain ray loop

Isolated from baseline `39b6d509af8e82b0ceb9e1c430dd964674d7488e`.
No navigation cache, target prediction, recovery, weapon, strategy, search-cap,
or deadline changes are included.

## Change and reason

`ArenaMap.line_of_fire` still performs the original Python prism, hole and
overhang checks first. Only its terrain-cell cut loop, bilinear interpolation,
five-centimetre clearance threshold and quadratic interior-minimum test move
to a compiled C++ function. Formula and operation ordering are preserved.
The compiler disables fast-math and fused multiply-add contraction.

The ctypes wrapper retains the sample array and its exported buffer, validates
sample identity, length and geometry configuration, and falls back to the
original Python terrain loop if the library is absent/incompatible or rejects
an unsupported input. Existing in-place sample edits remain visible; resizing
an exported array is prohibited by Python. No runtime writes or network calls
are introduced. Memory allocation per ray is bounded; exceptionally large
unsupported cut ranges use the original Python path.

The baseline's existing time-bounded searches vary between runs: three runs of
the same 1,045 C1 observations changed 235/216 movement commands relative to
run zero, despite every answer staying below 50 ms. The unchanged baseline
also scored 4.58 on an official repeat versus its original 4.75. These facts
motivate reducing computation cost; they do not prove this candidate scores
better.

## Build

The Dockerfile pins the existing Python image digest and compiler package
`g++-14=14.2.0-19`. A separate build stage compiles the small shared library;
the final image contains neither the compiler nor apt packages. C++ and GCC
support libraries are linked statically. The resulting library depends only
on libc and the dynamic loader in the base image.

Compiler and base-image pins do not freeze the entire apt dependency graph or
repository snapshot. The tested build completed successfully in under one
minute. A future build must still satisfy the competition's ten-minute limit.

Tested image: `labubu-score7:terrain`, manifest
`sha256:3e66c7663a137bfc06932eaed81df44ccb2b0a771588e87e249e6776db8a32d7`.
Compiled source SHA256:
`2dabb70713cfed1de9a386d32761ec915ac969f78ca858be5de3df52972dbca1`.

## Validation

- **130 tests pass inside restricted Linux**, with the native library required,
  including 1,200 synthetic rays, 800 official-map rays, threshold/grid/vertical
  and saddle-extremum cases, array mutation, stale configuration and fallback.
- An independent review found no blocking arithmetic, pointer-lifetime or
  supported-input fallback defect. Image probes verify absent-library,
  incompatible-version and missing-symbol fallback, plus 36 nextafter boundary
  cases. Image Python sources match the worktree.
- A benchmark uses all 1,818 recorded C1 mech center/upper rays. Three rounds
  alternate native/Python call order: **5,454 comparisons, zero mismatches**.
  Aggregate full-map speedup is **4.861x**. Native p50/p90/p99 are
  0.415/0.907/1.178 ms, versus Python 2.533/3.725/4.785 ms. Terrain-clear rays
  improve 5.447x; prism-blocked rays remain approximately unchanged (1.010x).
- Official checker and bot both run inside the Linux container with one CPU,
  512 MB, no network, read-only root, 64 MB `/tmp`, and uid65534. The helper
  verifies the real map (259 prisms, 774680 samples) and loaded Python hashes.
  **300/300 timely replies**, zero malformed/wrong-tick/stale replies. Startup
  3049 ms; p50 10.5, p90 16.3, p99 30.3, maximum 31.9 ms.
- Three full C1 fixed-observation runs (1,045 decisions each) give median
  17.43/17.37/17.19 ms, p99 32.17/31.80/31.86 ms, maximum
  34.40/32.25/46.32 ms, and zero replies over 50 ms. Relative to native run zero,
  movement differs on 72/125 frames and goals on 1/24 frames; firing is identical.
  This is less variation than the measured baseline, but is not deterministic.

The first full test invocation omitted the checker-fixture mount and failed
four test imports/setups; native geometry tests passed. After mounting the
required fixture directory, all 130 tests passed. No production correction
was needed for that validation setup error.

## Limits and artifacts

Timing results are measurements on this host under container restrictions.
They do not bound all future runtime delays. Exact geometric parity does not
mean identical behavior under deadlines: doing more search work changes
movement choices. Fixed-observation replays do not simulate resulting positions,
damage or opponents' reactions. No live placement or score improvement is
claimed before official evaluation. The worst C1 ground-grid destination is
still unreachable; this candidate does not redesign destination selection.

Raw evidence in `work/game-interface-audit` outside the submission repository:
`terrain-native-tests.log`, `terrain-linux-check.log`,
`terrain-repeatability-linux.jsonl`, `native-c1-rays-benchmark.json`, and the
independent native review artifacts. `outputs/run-validation.ps1` runs the
official checker inside the already-built image.
