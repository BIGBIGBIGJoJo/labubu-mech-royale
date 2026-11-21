# Historical experiment document

This file records earlier experimental branches. The current controlled
experiment is described in PROGRAM_DESIGN.md and the three current strategy-agent plans. Its runtime
does not include all mechanisms proposed or tested below.

# Selective strategy follow-up: preserve the escape route

The first selective entry scored **2.46** officially, despite finishing first
and second in two private free-for-alls. The selected best remains **4.75**;
the **6.0** target is unmet. The user's constraints remain unchanged: safe
farming, no first attacks on quiet mechs, attributed self-defense, and safe
finishes against the weakest eligible participant in an existing fight.

## Confirmed movement failure

In the second private match, urgent rotation began about 14 seconds before the
bot left the safe zone. It subsequently took 852 zone damage. The route around
a building was physically valid, and laser charge was zero throughout the final
rotation. Replaying captured observations reproduced repeated movement opposite
the route.

The local planner rewards only 0.6 seconds of route progress. Its estimated
enemy exposure could outweigh that reward and send the bot backward, while the
zone model missed most of the later cost of delaying escape. In a recorded case,
a clear northbound trajectory advanced about 5.3 m but carried estimated exposure
234; a retreat lost about 6.3 m but carried exposure 143 and won the comparison.
These exposure values are heuristic costs, not measured damage.

The movement agent will make an isolated urgent-rotation correction:

- Increase route-progress weight from 1.3 to `1.3 + max(3, zone_dps / walk_speed)`
  during urgent rotation.
- Use 0.35 as the urgent multiplier for inferred enemy exposure.
- Retain full projectile, aimed-beam, actual-zone, and exact collision checks.
- Preserve ordinary movement behavior outside urgent rotation.

Verify the change against the captured failure, blocked routes, projectile
escape, and full regressions. Replaying observations verifies decision changes;
it does not simulate the resulting match.

## Defensive firing investigation

The fire agent is reviewing two hypotheses for coordinated practice, where
opponents never fight each other:

1. The three-second attacker memory may end an ongoing defensive duel whenever
   successful dodging prevents another damage event. A longer bounded memory
   while healthy could retain permission against an established attacker.
   Recovery must keep its short quiet window, and unseen actors must never become
   targets. No elapsed-match timer or proximity-only first-shot permission is allowed.
2. Protecting every other mech from collateral also protects other separately
   attributed attackers. Active self-defense targets may deserve a shared
   authorization set while target selection still prefers the lowest eligible HP.

Changes require a concrete evidence review and focused permission tests before
implementation. There are no official per-match replays available, so neither
hypothesis is an established explanation of the score decrease.

The separate reload audit did establish a local availability problem: partial
reloads began with 10/12, 6/12, and 6/12 rounds while a mech remained visible.
They overlapped 2.7 observed seconds of subsequently authorized defense. A
one-observation counterfactual found 1.0 second with valid gun triggers if those
rounds had remained available; it does not establish additional hits or survival. Add a
`quiet_reload` input: keep automatic empty-magazine reloads, but defer optional
partial reloads while a current visible opponent can threaten the bot. Quiet
observation still cannot fire; retaining ammunition only preserves readiness.

## Boost experiment, kept separate

A proposed 35-to-65 energy recharge latch reduces repeated regeneration restarts
under sustained boost demand. A work-only energy model supports testing it, but
does not establish a game-speed or score improvement. Any implementation must
keep existing trajectory ranking, preserve the finish reserve, and permit a
verified immediate escape without waiting to recharge. Test this separately from
the rotation correction so its behavior and cost remain reviewable. Its separate
implementation and verification plan is [BOOST_PLAN.md](BOOST_PLAN.md).

## Acceptance and comparison

Keep the submitted commit `88488f29e2b56ea82b33930793a6506c91efc21a` public and
unchanged. Run meaningful behavior tests, stress checks, the exact Docker
conformance check, and a private diagnostic on each finished candidate. Publish
and officially score only validated commits. Preserve the selected 4.75 result
if a candidate scores lower, and report private and official outcomes separately.

Sources: [official rules](https://www.joinbuilders.org/buildathon/tracks/builders),
[protocol](https://www.joinbuilders.org/buildathon/tracks/builders/files/protocol.md?inline=1),
captured local observations from the two unchanged selective-policy diagnostics.
