# Guarded defensive laser finish attempt

Isolated base: `6d9dc40ba57b20df33d56aee04c49a25e5472552`. The frozen duel branch is unchanged. Production changes are confined to `bot.py` and `combat.py`.

## Observed problem and scope

In the frozen duel private diagnostic, enemy 4 had 98.57 HP at 182–184 seconds. Our gun was entering a long reload, while our laser had zero charge and zero cooldown. Existing emergency behavior prohibited starting a charge during retreat. With the observed five cubes and configured maximum legal enemy armor of 24%, the existing minimum-charge laser damage bound was 137.8944. This identifies an available modeled opportunity; it does not prove a hit or a survivable charge.

At 182.0 and 184.0 the bot was inside the current zone, but predictive 12-second zone urgency kept its movement mode `rotate`. At 182.5 it was outside the current zone. The new admission therefore allows preventive rotation while currently inside, and rejects the captured outside-zone frame. It preserves retreat/rotation goals, the health-recovery latch, and existing resource priorities.

The caller must explicitly opt in. All of these conditions are required:

- Currently recovering, with existing defensive-fire permission already true and quiet healing false.
- Currently inside the zone, with map geometry available.
- Exactly one active opponent ID from the existing duel classifier, matching the selected visible mech target.

Combat additionally requires observed zero laser charge and zero cooldown, known finite positive mech HP no greater than its conservative minimum-charge bound, a valid in-range/pitch solution, body alignment and a clear actual launch ray. The bound forces the existing configured maximum enemy armor; it does not credit an unverified armor estimate or a rear-hit bonus.

## Ray and charge model

The admission witness uses the first physics tick's slew toward the **final shared action aim**. It does not substitute the laser's desired aim when the gun owns that aim. The target center follows the existing solution's constant-velocity first-tick prediction; the cylinder uses its actual center height even if the aim point is an upper/lower-body fallback.

The witness checks the central muzzle-to-barrel segment, then the horizontally extended barrel-to-near-cylinder segment. Barrel Z stays at muzzle height. This model is supported by the current private recording: 18 observed laser-beam samples had median origin error 0.008124 m for horizontal-only extension versus 0.266224 m for full three-dimensional extension. These are samples, not necessarily independent shots. No ordinary aiming solver or ordinary weapon-ray policy was changed.

This is an admission snapshot, **not** a prediction that a beam fires on the next physics tick. A new press starts charging. A subsequent observed charge of 0.1 seconds retains the existing emergency release command; the server may continue to the configured 0.15-second minimum before emitting. Observed charge continues to slow the tactical movement model until a later observation clears it. Future target motion, our command acceleration, enemy attacks and geometry during the minimum-charge interval remain uncertain.

No new charging state machine or target lock was added. Existing ordinary gun/laser behavior, already-charging release behavior, near-full tolerance, defensive facing and no-fire permission remain in effect. The actual-ray helper is called only for this opt-in new-charge admission.

## Evidence and tests

The committed terminal fixture retains exact trace/source provenance and prior damage-memory timestamps. Controlled tests cover real-map 182.0/184.0 admission and 182.5 rejection; unknown/nonfinite/nonpositive or excessive target HP; NPC, multiple/mismatched opponents, cooldown, quiet healing, absent fire permission and unavailable geometry; invalid range/pitch; gun-owned shared aim; blocked actual rays despite a clear planned upper-body segment; a wall inside the barrel extension; and geometry behind an already intersected target.

Integration tests keep RUN/rotation and the health latch, preserve observed charging slowdown after release, and confirm that a newly requested charge bypasses the non-firing reload-facing override through the existing fire guard. Telemetry `duel.defensive_laser_start` means the action requested this guarded start. Repeated qualifying fixed observations must not be counted as independent emitted beams or kills.

## Final local validation

Runnable image ID: `sha256:c690979004895e5e06c6229a9e13dcda2ec15e274d2fd2cceab018bb71fd2702`.

LF-normalized source hashes:

| File | SHA-256 |
| --- | --- |
| bot.py | 25114da51c2613602ee508f5204f0fa6c96545171d061d9bcf9831fa870ce31f |
| combat.py | 6d217dcda28f491e23494d812f311887c554b4dceb5b982d4bc7914fe157bad3 |
| duel.py (unchanged) | 22025c59eddc9ed2f4b992cab8a902b7441e046263b996d70aee5f28a315667d |

Linux runs used one CPU, 512 MiB memory/swap, 128 PIDs, no network, read-only root, a 64 MiB temporary filesystem, UID/GID 65534 and read-only official map/checker inputs.

- **219 tests passed** in 36.180 seconds.
- Official checker executed inside Linux: **300/300** timely valid actions, no errors or debug-limit violations; median **10.1 ms**, p99 **28.2 ms**, maximum **30.4 ms**; ready in 3359 ms.
- Independent full frozen-duel private chronology: **1,841 actions**, no exceptions or actions over 50 ms; median **12.355 ms**, p99 **31.107 ms**, maximum **31.569 ms**. Image/source equality, native terrain, both caches and the actual map were asserted.
- The new exception admitted laser fire on **11 recorded frames**: 182.0, 182.1, 182.9, 183.0–183.5, 183.9 and 184.0, with **zero admission-gate violations**. All remained recovering, rotating, inside the current zone and moving. The 182.5 outside-zone frame remained excluded. All 1,841 duel phases/reasons matched the original frozen-duel recording.

These 11 fixed-observation admissions are not 11 independent charges, emitted beams or hits. Changed actions do not affect later observations in this replay. Neither the replay nor the local runtime results establish a changed match result or competition score. Detailed workspace artifacts are `defensive-finish-linux-tests.txt`, `defensive-finish-linux-checker.txt`, `defensive-finish-c690979-full-prefix.json` and the associated activation summary.
