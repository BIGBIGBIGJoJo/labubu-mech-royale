# Bounded last-listed mech memory for drop contestation

Base: exact best-scoring `39b6d50`, with no first-magazine preference change.
This experiment changes only the supply-drop contestation check. It does not
change targeting, firing, movement, recovery thresholds, or other loot valuation.

## Recorded problem

In the offense private run, drop selection begins immediately after an opposing
mech disappears from the actor list:

| Snapshot | Prior last-listed mech | Own drop completion | Existing contest estimate |
|---|---|---:|---:|
| 78.8 s | mech 10 at 78.7 s | 9.66 s | 5.11 s from its prior listed position |
| 85.2 s | mech 10 at 85.1 s | 10.53 s | 5.27 s from its prior listed position |
| Independent v3 77.2 s | mech 2 at 77.1 s, 2.29 m from drop | 9.30 s | already inside capture radius |

These are concrete admission discontinuities, not proof that another choice
would save a life or improve the official score. The offense bot's previous hold
position still had clear shot rays from the later attacker 2. It was not verified
physical cover against that attacker. Private online observations/actions also
have approximately 0.4 s transport delay, unlike official lockstep scoring.

The successful selective-v4 excursion at 140.6 s follows an observed kill of
mech 11. That mech must immediately stop contesting the drop. A blanket ban on
low-health drop collection would suppress this legitimate case.

## Change

Keep at most 16 detached records of last-listed living hostile mechs, each with
its ID, position, and observation time. Admission is only from `obs.mechs` entries
whose kind is `mech`; exclude self, NPCs, dead actors, and IDs outside the documented
0–15 mech range. Purge observed kill targets immediately. Constructor state is
empty for each new match. Records expire at an age of exactly 2.0 s; this is an
explicit policy parameter.

Enemy HP is optional in the protocol. An omitted HP value is not evidence of
death and keeps the baseline conservative contestation behavior; only an explicit
nonpositive HP or observed kill establishes death for this rule.

The protocol may already retain actor listings for five seconds, so this is
**last-listed memory**, not a claim of freshly visible enemy information. No
velocity extrapolation or new collision model is introduced.

Only the supply-drop contestation loop merges missing records into its existing
current actor list. Current listed actors retain their present semantics and
positions; a cached record must never replace one or bypass current-list filters.
The existing straight-line travel estimate, base boost-speed model, and completion
margin remain unchanged. A retained record is treated as a conservative veto
for this short window; it cannot become a target or authorize a shot.

## Validation and acceptance

- Frozen snapshots: offense 78.8/85.2 and independent v3 77.2 must reject the
  previously accepted drop using only earlier observations, while control
  instances without memory continue to accept it.
- Confirmed kill 11 at selective-v4 140.6 must permit the existing safe excursion.
- Unit cases: exact expiry, current actor precedence, NPC/self/stale/dead exclusion,
  kill invalidation, observation immutability, new-match reset, and bounded storage.
- Preserve all baseline tests and inspect the complete diff to confirm no other
  runtime change. Freeze before Docker/private/official testing by the root agent.
- Report private commands, observed damage/kills, and official score separately.

Two seconds is a conservative experiment parameter, not an inferred enemy
position guarantee. A disappeared mech could have died without an observed kill,
so a useful drop can be delayed until this bounded record expires. No simulated
or counterfactual kill gain is claimed.
