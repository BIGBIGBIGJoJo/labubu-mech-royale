# Exact terrain endpoint reuse

This isolated performance change retains the previous evaluated terrain interval's
endpoint clearance within one line-of-fire query. Reuse it only when the next
interval starts at exactly the same floating-point parameter. A skipped positive
gap requires recomputation. Keep prism intersections, midpoint samples, quadratic
minimum checks and all clearance thresholds unchanged. No cross-query cache,
terrain approximation or visibility-budget increase is included.

The existing immutable terrain function returns the same value for the same
point. Therefore this removes duplicate interpolation without removing a sample.
The scratch comparison covered 4,467 rays with identical booleans and a targeted
skipped-gap control that fails if the equality guard is removed. Measured batch
time decreased 18–28%; this does not establish a full-policy or score benefit.

Before adoption, add focused guard/quadratic/duplicate/cross-query regressions,
run existing geometry and full-policy tests, and measure affected real-map timing.
Root will port the narrow change into the chosen resource/pursuit candidate only
after its scope and validation are recorded. Preserve submitted commits.

## Port validation

The isolated port passes 219 tests, including five focused endpoint-cache
regressions. The full-policy affected benchmark passed all 252 opening/dense
decisions below 50 ms; maximum was 22.66 ms. All 27 dense actors remained
eligible and correctly ordered. Under the unchanged six-millisecond visibility
budget, dense cases verified 6–10 sight lines versus 4–7 in the earlier baseline
sample. The two full-policy runs were not simultaneous paired measurements,
so their maxima are not a controlled percentage-speedup estimate. The earlier
alternating-order ray benchmark provides the narrower performance comparison.

The cache does not remove the deadline or make unchecked visibility clear.
Container, live and official validation remain required for the final combined
candidate. No score benefit has been measured for this isolated port.
