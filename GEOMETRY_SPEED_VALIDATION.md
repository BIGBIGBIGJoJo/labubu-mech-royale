# Combined exact geometry acceleration

Combines navigation-cache commit `6bd5920166f9e09e790b232a568361db767770f1`
and compiled-terrain commit `0fad6304773c811f7eb598e5f334a13a5d9220c7`.
Bot strategy, combat, tactical scheduling and search limits remain the original
39b baseline. No reachability screening, resource or evasion change is included.

The Docker integration includes both loaders and data assets. The navigation
asset was fully regenerated with two workers in 183.83 seconds because the
combined arena source has a new validation hash. Its complete geometry payload
is byte-identical to the separately validated cache:
`1b54831b433872990385c8f5a91acdd755203bdd6439b46426b1d1678e0ccb45`.
Only its metadata key changes. The 353832-byte combined asset SHA256 is
`06e12324b3b4c9b315acd141ba3b8061a6a19bee2b1e1dea88539a881a0f4183`.

Image `labubu-score7:geometry-speed`, manifest:
`sha256:28e1b2b20bb7bfda599101a10683c2037ee7e10aae7d31a3b5beab87c97bcc6b`.

- **141 tests pass inside Linux**, including both sets of geometry tests with
  the compiled library required. Real-map cache loading/parity is covered.
- Official checker and bot inside 1-CPU/512-MB Linux, network disabled,
  read-only root, 64-MB temporary storage, uid65534: **300/300 timely**, no
  malformed, stale or wrong-tick replies. Startup3394ms; p50 10.5, p90 17.2,
  p99 24.0, max28.3ms. Preflight verifies map and seven loaded Python hashes.
- Three full C1 fixed-observation replays explicitly require **both** the
  navigation cache and native kernel active. Each contains1045 decisions.
  Median16.54/16.56/16.64ms, p9931.95/32.08/31.83ms,
  max36.81/33.31/42.64ms; zero responses over50ms.
- Compared with combined run zero, movement differs on45/41 frames, goals on
  1/18, and firing on zero. Baseline's separate three-run experiment differed
  on235/216 movement frames. This reduces observed timing sensitivity; it
  does not make the policy deterministic or prove a placement gain.

The individual cache scored4.75; terrain acceleration scored4.71. Original
baseline scored4.75 then4.58 on an unchanged repeat. This combination has not
been submitted. No performance measurement is a substitute for official score.
Existing unreachable destinations remain a separate behavioral problem.

Raw records under the shared workspace's `work/game-interface-audit`:
`geometry-speed-cache-build.log`, `geometry-speed-linux-tests.log`,
`geometry-speed-linux-check.log`, `geometry-speed-repeatability-linux.jsonl`.
The two inherited component reports describe their individual experiments;
this report is authoritative for the combined image.
