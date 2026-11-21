# Timestamp the optional damage-bearing fallback

Follow-up to frozen `ffc08c7b3845beb2afa9c550ef910ff74e85f1e0`.
The parent commit and image remain unchanged.

## Boundary and minimal guard

`update` advances `last_hurt` for every damaged event, including zone damage,
while retaining the previous bearing when the event carries null. The original
general aim-selection rule can consequently select an old bearing after a new
zone hit. The parent fix would preserve that stale selection in its new optional
reload fallback.

The schema's `DamagedEvent.bearing` is number or null; its description explicitly
uses null for zone damage. Rather than equating any weapon hit with a new bearing,
this follow-up records `damage_bearing_t` only when a non-null bearing is observed.
Only the optional reload fallback now requires that timestamp to be less than
three seconds old. **The earlier general aim-selection rule is unchanged.**

Production delta from the parent: one initialized timestamp, one timestamp update
alongside the existing non-null bearing assignment, and one freshness condition
when supplying the optional fallback. Visible-threat optimization and existing
fire, charge, reload and pitch behavior remain unchanged.

## Evidence

A scan of all 15 complete traces in the current workspace found no naturally
occurring stale-bearing revival. This is a protocol-valid boundary regression,
not an observed live-match failure. Four explicitly synthetic fixtures verify:

- A four-second-old bearing is not refreshed by zone damage.
- A bearing exactly three seconds old is stale despite fresh zone damage.
- A genuinely fresh two-second-old bearing remains usable after zone damage.
- A schema-valid nullable non-zone event cannot refresh an older bearing.

The frozen parent incorrectly preserves the old bearing in the three stale
cases; the timestamp guard passes all four. The non-zone-null case is defensive
schema coverage, not a claim that such an event occurred in the observed traces.

The original captured window's initial timestamp was verified in the raw trace:
at **54.2s**, a `damaged` event reports gun damage 91.8, bearing **-0.203**, attacker
6, rear=true. It is neither zone nor null. The fixture now stores that bearing
timestamp explicitly rather than relying on `initial_last_hurt` as an alias.

## Validation

- **133 tests pass** on host and restricted Linux, including all 21 recorded
  facing frames and the four freshness fixtures.
- Fresh real-map checker: **300/300 timely**, zero malformed/wrong/stale/late
  replies; ready 3054ms; p50 12.2ms, p99 33.0ms, maximum 34.7ms.
- Full 613-observation prefix: no errors or computations over 50ms; p50 20.51ms,
  p99 32.29ms, maximum 34.63ms.
- Relative to the frozen parent's replay, **zero aim, fire, reload, take/drop or
  upgrade-pick differences**. All 21 captured facing corrections remain present.
- Container limits remain one CPU, 512MB, no network, read-only root, uid65534,
  128 processes and 64MB temporary storage. Real map: 259 prisms.

Image `labubu-score7:hidden-defense-fresh`, manifest:
`sha256:e42fece9d1c88bd7a3e47982e284575db7830e98dae852bbc42cddfcfcff92c2`.
`bot.py` SHA256:
`3f09b3cb40d4ff6b995d4a3120747ad83abc8f0d476a940162ee3324138c7847`.
Python runtime manifest SHA256:
`8fcec6f20203ea374bf70da5389a4a54f61f07aa2d5658dc17fe1c08631eb1ba`.

Audit artifacts remain outside the repo: `damage-bearing-zone-audit.json`,
`hidden-defense-freshness-before.json`, `hidden-defense-fresh-linux-tests.txt`,
`hidden-defense-fresh-official-check.txt`, and `hidden-defense-fresh-replay.json`.
No private game was launched. No prevented-damage or score claim is made.
