# Ground pickup leases on the integrated controller

Base: `9c440e4f9609bf5028886751cf646fd1969fd461`. This candidate adds the existing `297966fa398fb90f07be2cbc80be0a06de74b46d` collect-and-exit lease to the integrated controller. A currently visible, ordinarily exposure-filtered cube or weapon can briefly override rotation only when both full ground legs, anticipated observed cube growth, announced zone timing and a fixed exit pass verification. The candidate retains the existing resource ranking, combat, ground-goal revalidation, native geometry, exact navigation cache and reachability metadata.

Three correctness changes accompany the old lease: the pickup walking waypoint uses terrain height, every full leg also checks the bounded sampled support-height progression, and a cancelled continuation expires a held rotation goal before fallback selection. Telemetry reports whether the stored lease remains active, including stuck cancellation.

## Validation environment and identity

All final runs used Linux/amd64 Docker, no network, one CPU,512MB memory/swap, read-only root filesystem,64MB temporary filesystem, uid65534 and the actual arena. The preflight asserted259prisms/774680terrain samples, the native terrain implementation, both loaded geometry indexes and image/source equality. Python hashes normalize CRLF to LF; binary asset hashes remain exact. No checker was launched on the Windows host.

Validated image: `sha256:c7e86e837f8082d8f2d158e6c6aa9e9d5127502583071cbb1eacdcdc2957a69f`, tagged `labubu-score7:integrated-economy` during validation.

| Runtime file | SHA256 after LF normalization |
| --- | --- |
| bot.py | b894d3d7426b4fa1a4b62ee9f4a052876b257e82b4bb9557b14dcc84b0fccbae |
| zone_resource.py | 326a411c6060f1eef8933ff36af01b5398e8c625a11f6950abc56d1e3d4e869e |

All other runtime Python files, `terrain_kernel.cpp`, `navigation-cache.bin` and `ground-reachability.bin` remain identical to9c. Native compilation is unchanged. Runtime source did not change between the final build, tests, checker and replays.

## Tests and protocol check

All207 tests passed in37.970s:174 existing tests,23 original lease tests and10 new ground/transition regressions. The new cases cover the recorded119.7 witness, elevated item walking height, an actual bridge roof start, continuation onto a roof, intermediate roof support between two terrain endpoints, item height changing during collection, fixed-exit phase-reserve expiry, a recorded airborne state, expired geometry budget and cancellation of an exit with an unexpired goal TTL.

The geometric/state unit tests use generous diagnostic helper budgets to isolate correctness from host scheduling. One original geometry-only test initially failed when its6ms cap expired under the full suite; its budget was separated from the runtime performance checks. Pipeline tests and both full chronological replays retain the actual6ms helper cap and32ms action scheduling. A synthetic fixture initially inherited the real arena's30m margin in a40m test world; its fixture configuration was corrected. These changes did not change production deadlines or behavior.

The official checker ran inside the restricted Linux image using `/kit/check/check.py --map-dir /arena -- python3 -u /bot/bot.py`:300/300 on time, zero late/old/wrong-tick/bad lines, p509.5ms,p9017.2ms,p9924.9ms,max27.0ms. Ready in3083ms. This verifies protocol and response timing on the recorded official stream, not competitive performance.

## Full chronological recorded-observation replays

The replay calls actual `Bot.act` from the image in observation order. Hooks only record existing resource, lease and navigation calls. Deadlines remain: action32ms, resource `min(global−21ms,now+4ms)`, lease `global−18ms` with its6ms component cap. Later observations still come from the original controller's movement, so alternate actions are not simulated collection outcomes.

| Trace | Observations | p50 ms | p99 ms | Max ms | Errors / above50ms | Lease result |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Integrated9c private |1594|22.509|31.449|32.110|0 /0|Admitted119.7, seven collect actions through120.3, cancelled120.4|
| C1 correctness private |1045|21.457|31.563|33.202|0 /0|Five admissions59.8,63.5,65.8,69.6,72.8;40 active collect actions|

The original C165.8 positive activates under the full real-budget prefix and continues through67.5. The integration-specific119.7 positive retains the same exit after terrain normalization. Its action took12.435ms: resource scoring2.614ms, lease call3.513ms starting2.865ms into the action with a14.002ms caller deadline. Neither trace enters an observed exit phase under the alternate policy; collection-to-exit transitions are exercised by explicit fixture tests, not claimed as live outcomes.

At119.7, the complete legs measure30.213m and56.173m. The model takes8.38345s plus4s reserve, fitting the12.8s announced phase by0.41655s. The fixed exit remains admissible through120.3 despite newly generated exits being blocked. At120.4 the recorded turn away increases modeled remaining trip+reserve to12.12339s, beyond12.1s of known phase; the lease correctly cancels. This is a temporal limit on fixed observations, not proof the alternate movement would have failed or collected the cube.

## Scope and limitations

This is a direct ground-route model, not authoritative game simulation. Both endpoint terrain scope and intermediate sampled supports are checked because `move_clear` also supports roofs and ignores requested end Z. An independent real-geometry fixture demonstrates terrain start/end with an intermediate retained14m bridge roof; the added guard rejects it. Actual119.7 has49 terrain support samples and is preserved. Airborne/elevated starts and unsupported route heights fail closed; no general3D route claim is made.

Collection repeats the ordinary value/exposure gate for the leased item. Exit repeats recovery, charge, grounded-state, geometry, growth and zone checks; it does not newly rescore enemy exposure during the exit. The6m rotation-release hysteresis and4s exit reserve are existing policy parameters. The model overestimates observed incidental cube growth but cannot account for unseen future items, enemy motion, future attacks or actual game physics beyond the existing geometry checks.

No new private game or official submission was run for this candidate. No score or actual additional pickup improvement is established.

## Local audit artifacts

The surrounding workspace contains `work/game-interface-audit/integrated-economy-tests.log`, `integrated-economy-checker.log`, `integrated-economy-source-manifest.json`, the independent review, and `integrated-economy-replay.json` in each of the integrated9c and C1 trace directories. The broader read-only cube5064 investigation is `CUBE_5064_LEASE_AUDIT.md` alongside the integrated trace.
