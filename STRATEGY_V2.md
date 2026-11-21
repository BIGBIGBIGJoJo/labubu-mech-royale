# Strategy v2: target 6.3

## Objective and evidence

Raise the verified practice score from **4.19 toward 6.3** while preserving a
robust free-for-all policy for the later tournament. A 6.3 practice score means
mean placement 9.7 across the official 48 matches. It is a target, not a predicted
or guaranteed result. The accepted baseline is commit
`7c38fba27c3feb6f52c2b74b45423f63beb33ff5`; experiments use `strategy-v2`.

The official objective is survival placement, not kills or damage. Practice
opponents cooperate, so prolonged trades with multiple enemies are especially
expensive. The bot should acquire power when the exposure is affordable, remove
attackers it can finish efficiently, and preserve an escape route and regeneration.

The audit found three concrete limits:

1. The movement controller assumes instantaneous directional movement and
   independent acceleration per axis. Recorded movement instead supports a
   vector acceleration limit. A deterministic projectile benchmark reduced
   modeled hits from 1,617 to 1,294 across 3,000 cases by selecting actions from
   swept physical trajectories. This is a mechanism check, not a match score.
2. Five earlier private diagnostics collected no cubes. No crate or NPC was
   fully destroyed by the bot. A blanket enemy-distance exclusion blocks even
   short retreating loot detours; recovery also prevents consideration of
   full-heal supply drops. Resource production and collection need a complete
   policy, not just a higher cube utility.
3. A command persists for two physics frames, but weapon readiness checks cover
   only one. Laser charging must account for its movement penalty, useful early
   lethal releases, shared torso aim, and the need to disengage.

## Decision order

1. Read authoritative live configuration and current upgraded stats. Update
   attackers, observed loot, target continuity, and recent combat.
2. Assess zone arrival, number of exposed enemies, health, energy, and available
   cover. Preserve safe regeneration once incoming fire stops.
3. Compare reachable objectives: immediate cubes, a useful second weapon,
   finishable crate/NPC, supply capture, defensive cover, or a favorable fight.
   Include travel/finish time and enemy interception; avoid spending health to
   contest a resource whose value will not be recovered.
4. Navigate toward the selected objective, with hysteresis to finish useful
   work. Fight while collecting when necessary. A safe healing objective may
   override passive recovery; an urgent zone rotation takes precedence.
5. Roll out candidate walk/boost/brake actions at 20 Hz. Score swept projectile
   intersections, physical collision, zone exposure, and progress. Check future
   enemy visibility for shortlisted actions using intrinsic enemy strength,
   rather than retaining a current occlusion discount.
6. Schedule both weapons against one torso direction. Use held-command readiness
   windows, release lasers early when sufficient to finish, preserve energy for
   escape, and stop dealing damage when quiet regeneration has become valuable.

## Findings incorporated during implementation

- **Cube geometry:** protocol section 8 says only eye/muzzle heights are already
  cube-scaled in `self.stats`. Radius/height still require the uncapped size
  multiplier. An eight-cube private trace showed the old controller trying to
  enter an 11.46 m bridge clearance with an actual 12.6 m body. Both navigation
  and weapon geometry now compute the real dimensions.
- **Arena boundary:** movement centers are confined by `match.arena_margin`,
  30 m in the supplied configuration. Terrain lookup retains the original map
  coordinates; movement and cover respect the narrower limits.
- **Reaction distance:** a small deterministic perfect-aim projectile fixture
  supported 120 m gun and 150 m laser spacing: 34/34 tested uncharged 120 m
  cases avoided the bullet, versus 16–22/34 at 70 m depending on energy. Laser
  charging required more room. This is a limited mechanism benchmark, not a
  guarantee against house bots, future shots, terrain, or multiple attackers.
- **Reload orientation:** while recovering with a long gun reload and no active
  laser charge, select a torso bearing that keeps the greatest observed threat
  weight within the front armor arc. This avoids staring at an unfireable target
  while a second attacker hits the rear.
- **Mortar scheduling:** briefly retain a valid mortar's aim while the torso
  slews, with a 0.3 s cap and immediate preemption for escape or an invalid arc.

An exact-baseline private diagnostic finished 2nd with five kills and 23 cubes;
the first v2 diagnostic finished 6th with three kills and eight cubes and exposed
the bridge bug above. Different random seeds and policies prevent interpreting
these two placements as a controlled improvement or regression.

## Economy policy

- Prefer already loose cubes and useful weapons over farming. Value cube
  thresholds and the immediate maximum-health increase. Reduce cube value after
  the damage/HP cap, since body growth continues.
- Replace the global 90 m exclusion with candidate-specific exposure and
  interception checks. A short move away from an enemy toward nearby loot can
  be useful; walking into its short-range weapon envelope is not.
- Persist on a partly destroyed crate when finishing remains safe. Use an
  aimable standoff and then collect the resulting cube. Do not begin farming
  while quiet recovery is needed.
- Treat a nearby isolated NPC as a finite two-cube opportunity when it can be
  killed and collected without entering an active mech fight. Actual NPC
  attackers retain defensive priority when no immediate mech threat exists.
- Evaluate drops using live landing/capture timings, arrival time, prospective
  contest, current capture progress, future circle, and missing HP. Recovery
  can select a safe drop. Never assume the private game's accelerated timings
  match the official scorer.

## Combat and positioning policy

- Use explicit pressure and target continuity to avoid wasting shots across
  multiple healthy enemies. Favor an actual nearby attacker or a reachable
  low-HP finish over a distant full-health target.
- Maintain separation from lightning and multiple attackers. Avoid unnecessary
  pursuit into new lines of fire. Prefer cover that blocks the strongest
  attackers and retains access to the future circle.
- Charge lasers only when the expected shot is worth the slowdown; release at
  a useful lethal threshold or when escaping requires full speed. Full charge
  remains the default for sustained damage, since minimum-charge tapping has
  lower ideal sustained DPS under the published defaults.
- Keep grounded navigation as the reliable default. Purposeful flight and
  speculative obstacle traversal are deferred until a measurable grounded
  improvement is established.

## Implementation and validation sequence

1. Implement `tactical.py` separately, with bounded runtime and conservative
   fallbacks. Add acceleration, braking, projectile height/sweep, collision,
   charging-speed, and exhausted-budget regression cases.
2. Update combat scheduling with deterministic timing/TTK fixtures. Keep the
   official wrapper unchanged and preserve actual torso alignment gates.
3. Implement resource exposure/arrival utility, safe recovery pickups/drops,
   finishable farming, and target continuity in the high-level controller.
4. Run behavioral and geometry tests; run real-map stress and the official
   recorded checker in the exact restricted Docker environment. Keep wall-clock
   headroom below 50 ms and check all actions against the official schema.
5. Use normal private-room games to diagnose stalls, cube production, retreats,
   and weapon scheduling. Private games are accelerated, delayed-input tests;
   their placements are not interchangeable with official 48-match scores.
6. Submit only a validated, committed candidate after checking the remaining
   quota and current scorer. Record the official result, retain the best entry,
   and use further attempts only for a concrete evidence-supported revision.

## Sources

- [Official Builders track](https://www.joinbuilders.org/buildathon/tracks/builders)
- [Official protocol](https://www.joinbuilders.org/buildathon/tracks/builders/files/protocol.md?inline=1)
- [Official starter kit](https://www.joinbuilders.org/buildathon/tracks/builders/files/mechfight-kit.tar.gz)
- Local official-kit configuration, supplied observations, and prior private
  diagnostic traces. No other entrant's implementation was used.

## Official feedback and route follow-up

Commit `39b6d509af8e82b0ceb9e1c430dd964674d7488e` scored **4.75**, up from
4.19. The 6.3 target remains unmet. The follow-up keeps the same overall strategy
and fixes route progress and firing geometry: consume a reachable partial-path
endpoint, abandon exhausted routes or exposed stationary frontiers, use the
documented lightning angle, and wait for the actual gun/laser ray to clear cover.
