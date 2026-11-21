# Gun vertical prediction candidate

Isolated from baseline `39b6d509af8e82b0ceb9e1c430dd964674d7488e` on `goal/prediction-seven`. No rotation, navigation, muzzle-origin or strategy branch changes are included. This report records pre-submission validation.

## Model and integration

`TargetMotion(config, arena)` keeps bounded state for at most 64 currently observed mechs. Each update consumes only the current observation and the immediately preceding configured observation tick. Missing actors, skipped ticks, backwards ticks and large position discontinuities invalidate previous acceleration evidence; repeated ticks do not create new evidence.

For an observed mech, XY remains exactly `position + velocity * horizon`. Gravity is applied to Z only when two consecutive observed vertical velocities imply acceleration within 3 m/s² of negative configured gravity, with current vertical speed above 0.5 m/s in magnitude. This includes rising jumps after their launch impulse, but does not treat observed jet acceleration as freefall. The model uses the hello's gravity and tick rate, not hardcoded 22 or 20. A body-width continuity check rejects a large ID/position discontinuity beyond the displacement implied by observed velocities.

Predicted feet are clamped to `arena.support_height(predicted_x, predicted_y, current_feet_z)`. The current feet height allows a roof below the actor to support landing while preventing a bridge above the actor from becoming its floor. This is an endpoint support estimate, not a full collision or control simulator. No future observation enters a forecast.

`Bot.update` updates the model before combat. `Combat` accepts an optional target predictor, used only for gun solutions against mechs. Existing callers without the predictor retain their prior behavior. The forecast horizon includes launch delay plus projectile flight exactly once. Three bounded distance refinements in each existing barrel-origin iteration reconcile changed target height with flight time, with at most eight forecasts per gun solution. Predicted body center Z is shared by aiming, pitch clipping, alignment and alternate upper/lower body checks.

Laser, lightning, mortar and NPC/crate aiming retain their existing prediction paths. Existing barrel translation and world-ray construction are preserved so this experiment does not combine vertical prediction with the separate weapon-origin experiment.

## Retrospective calibration traces

The implementation is evaluated chronologically on the same four traces that motivated the hypothesis. Later observations are held out from each forecast; the traces themselves are **not an independent validation set**. These are position errors, not gun hit rates or match scores.

Mean absolute vertical error at 0.4 s, metres, over **all** current/future actor pairs:

| Trace | Pairs | Constant velocity | Support only | Candidate |
|---|---:|---:|---:|---:|
| Baseline 39b | 1138 | 0.824 | 0.636 | 0.435 |
| Correctness ab878 | 885 | 0.626 | 0.498 | 0.345 |
| Aim 2dba505 | 641 | 0.744 | 0.603 | 0.397 |
| Navigation fc474fd | 786 | 1.327 | 1.028 | 0.658 |

The original audit excluded pairs without consecutive history or with measured horizontal/vertical acceleration above 65 m/s². On that identical subset, this implementation reproduces the original evidence:

| Trace | Pairs | Constant velocity | Candidate |
|---|---:|---:|---:|
| Baseline 39b | 1067 | 0.788 | 0.381 |
| Correctness ab878 | 839 | 0.563 | 0.267 |
| Aim 2dba505 | 595 | 0.678 | 0.305 |
| Navigation fc474fd | 701 | 1.262 | 0.514 |

All-pair mean vertical error improves in every trace at each measured horizon, 0.1, 0.2, 0.4, 0.6 and 0.8 s. Horizontal forecasts are asserted exactly identical to constant velocity. Full counts, means, medians, p90/p99, maxima and timing distributions are in `../game-interface-audit/prediction-model-audit.json`.

An exact recorded regression uses baseline actor 8 at ticks 856 and 858, with future tick 866 withheld. Current feet Z 0.17 and velocity Z -1.6 forecast -2.23 at 0.4 s; observed future feet Z is -2.45. Error is 0.22 m versus constant velocity's 1.98 m. The official map supplies support height for this regression.

Reproduce:

```powershell
python experiments\prediction_evidence.py --traces ..\game-interface-audit --output ..\game-interface-audit\prediction-model-audit.json
```

## New trace holdout, fixed model

The newly completed `rotation-230f9b5-20261121-170627` trace was first evaluated after implementation and the preceding validation were finished. It did not contribute to model selection. All production source hashes remained unchanged; no thresholds, physics, support logic or integration were retuned after inspecting it.

Vertical error in metres over **all** current/future actor pairs:

| Horizon | Pairs | CV mean | Candidate mean | CV p90 | Candidate p90 |
|---|---:|---:|---:|---:|---:|
| 0.1 s | 580 | 0.0549 | 0.0289 | 0.160 | 0.060 |
| 0.2 s | 575 | 0.1493 | 0.0678 | 0.550 | 0.110 |
| 0.4 s | 565 | 0.4329 | 0.1814 | 1.980 | 0.270 |
| 0.6 s | 556 | 0.8052 | 0.3326 | 3.580 | 0.520 |
| 0.8 s | 548 | 1.2449 | 0.5258 | 5.770 | 1.153 |

Both mean and p90 improve at every measured horizon. The original acceleration-filtered subset also improves; at 0.4 s its 547 pairs give mean 0.4258→0.1667 m and p90 1.980→0.250 m. Horizontal predictions remain exactly unchanged.

Individual failures remain visible. At 0.4 s, 207 forecasts improve, 82 worsen and 276 are unchanged. All 82 worsened cases involve the support clamp; the largest added error is 0.150 m at 40.9 s for actor 9. Its horizontal velocity turns substantially over the forecast interval, so support at constant-velocity XY differs from support at its actual position. The confirmed-freefall subset improves from mean 2.298 to 0.220 m over 59 pairs; the other 506 pairs improve from 0.215 to 0.177 m. The largest single added error across tested horizons is 0.865 m at the 0.6 s horizon (actor 8, 67.5 s), despite the aggregate improvement. These exceptions were reported without modifying the model.

The holdout has 922 observations and 585 visible mech samples; 59 samples confirm freefall. Model update p99 is 0.0257 ms and forecast p99 0.0243 ms on this host. Raw artifacts:

- `../game-interface-audit/prediction-rotation-holdout.json`: complete horizon, model, subset and timing summaries, with unchanged source hashes.
- `../game-interface-audit/prediction-rotation-holdout-subsets.json`: 0.4 s subgroup summaries and worst individual increases.
- `../game-interface-audit/prediction-rotation-holdout-deltas.json`: improve/worsen/unchanged counts and largest increases at every horizon.

This is a genuine new-trace forecast holdout. It still does not establish a gun hit-rate or score improvement.

## Geometry, integration and runtime validation

**144 unit tests passed**, including 20 new regressions. The gun-focused tests were also rerun after extending the center-height assertion to a four-cube target.

New cases cover recorded freefall, ground and rooftop landing, actors above versus beneath the same bridge, support at predicted XY, rising jumps, jet acceleration, absent history, observation gaps, ID/time reset, duplicated observations, stale snapshots, bounded history, alternate tick rate/gravity, input immutability, delayed launch, consistent flight/body-center geometry, pitch-limited upper-body shots, cover alternates, bounded predictor calls and non-gun isolation.

Synthetic geometry uses the real `ArenaMap`: a ground plane, a solid building roof and a raised bridge. A falling actor above the bridge lands at its 14 m deck, while an actor already below it lands at ground Z 0. Gun tests preserve baseline muzzle/ray behavior and include the actual cube-scaled target center in the forecast.

Host model overhead across four traces: update p99 0.029–0.047 ms; one forecast p99 0.030–0.078 ms. Worst individual measured update was 0.167 ms and forecast 0.308 ms. A gun solution uses at most eight forecast calls; there are no unbounded iterations or additional world-ray queries in the predictor.

Image `labubu-score7:prediction`:

```text
sha256:9f6038d37c48feb027657bbd154f47ef6afe0664212f0d46bace8cdac2ab7d24
```

The current official checker ran **inside Linux** using `/kit/check/check.py --map-dir /arena -- python3 -u /bot/bot.py`. Restrictions: one CPU, 512 MB memory/swap limit, no network, read-only filesystem, writable 64 MB `/tmp`, uid 65534, read-only arena and kit mounts. The same container first asserted the actual loaded map's 259 prisms and 774680 samples, plus loaded predictor gravity 22 and simulation interval 0.05 s.

**PASS: 300/300 timely responses**, zero late answers, stale queued answers, wrong ticks or malformed lines. Startup 2938 ms. p50 11.2 ms, p90 27.7 ms, p99 32.3 ms, maximum 34.3 ms. Raw log: `../game-interface-audit/prediction-linux-check.log`. The checker's generic timing parenthetical does not describe these invocation restrictions; both checker and bot ran inside the restricted container.

Production source SHA-256:

```text
target_motion.py 52c845e14e0a13136a1832755a5f4a745df2699340ada7c8424e55068955b40a
combat.py        ae195a7c00374dcd7dff7ab69aac6f1ddf9f324563877d52c5cf17ca4acd91a7
bot.py           e83fedf49f92354ab7c9436efc6292612bdd00532ddd58b4a8d5701dd9f285a2
```

## Limits

The model cannot predict a future jet, jump, landing-control change or horizontal turn from unavailable inputs. An endpoint support clamp cannot determine the full route the opponent will traverse. Some individual forecasts worsen even when aggregate error improves. Better predicted height does not prove better firing alignment, damage or score; those need a subsequent controlled match evaluation.
