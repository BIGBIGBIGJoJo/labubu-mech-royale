# Strategy v4: preserve earned advantages

Historical plan, superseded by [the current three-agent plan](AGENT_STRATEGY_PLAN.md)
and its user-confirmed **6.0** target and engagement rules.

At this experiment's start, the verified best was 4.75 and the target was 6.3. It focused on
specific losses observed in diagnostics and documented weapon geometry.

1. **Remember contested resources.** An enemy disappearing from the observation
   is not proof that a drop became safe. In the v3 private trace, an enemy last
   reported 2.28 m from a drop disappeared, the wounded bot approached, and the
   same enemy reappeared and inflicted heavy damage. Retain recent actor
   positions as resource hazards for a short bounded period. Do not use these
   extended memories as valid firing targets. Expire confirmed kills immediately.
2. **Require an advantage before committing to lightning range.** A useful
   secondary weapon does not justify chasing a stronger enemy with little
   escape energy. Preserve the documented laser-interruption advantage, but
   require sufficient health and energy; keep ranged spacing otherwise.
3. **Predict the launch position.** Twenty-three stable observed laser beam
   origins support movement before firing. The next-step velocity estimate
   reduced median horizontal launch-position error from 0.300 m to 0.014 m in
   those samples. Apply this small, measured correction; do not extrapolate
   speculative enemy intentions.
4. **Include the mortar barrel offset.** The protocol places every shot
   radius + 0.5 m forward along the aim. Iterate the ballistic solution around
   that offset, validate the actual arc, and retain self-blast protection.

Keep the current scored entry selected unless official evaluation improves it.
Require focused regressions, all existing tests, restricted-container conformance,
and a diagnostic run before submitting. Match scores remain the only evidence
that an iteration improves the competition result.
