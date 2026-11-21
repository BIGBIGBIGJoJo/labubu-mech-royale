# Ground reachability height scope

This small follow-up is based on frozen `fb3a01c125700261f1619fa1b1acadcc2160005c`.
That version and its one private diagnostic remain unchanged. The earlier
`REACHABILITY_VALIDATION.md` describes fb3, before this scope correction.

`GoalContext` previously returned YES for horizontal distance below 1 m without
checking feet height. Also, `ArenaMap.move_clear` can keep roof support throughout
a segment and does not certify the requested endpoint Z. Consequently a connector
boolean alone cannot establish that a mech on a roof reached the underpass.

The helper now returns UNKNOWN before graph/direct-connector queries when the
start differs from terrain ground by more than the existing `step_up + .02`
tolerance. Its near-XY shortcut additionally requires feet-height agreement within
the existing `CONTACT_EPS` (0.015 m). UNKNOWN preserves ordinary candidate scoring;
the change does not reject an airborne goal or introduce 3D navigation.

The actual-map regression uses the bridge adjoining the previously recorded
low-clearance encounter. At `(-114.84,-29.77)`, terrain is about -4.8007 m and the
bridge top is 8.59 m. Both a base-size mech on top and one below are clear.
`move_clear(roof, underpass)` returns true because support remains on the roof;
the corrected helper returns UNKNOWN for the same-XY underpass and for a farther
underpass point. Additional fixtures cover airborne/below-terrain starts,
same-height close goals and different-floor close goals.

This remains a witness in the existing ground-navigation representation, not a
universal physical route guarantee. Geometry may contain other support-height
ambiguities; the helper does not model jets, landing trajectories or general 3D
connectivity.

## Validation

- All **22 focused tests passed in restricted Linux**, including independent
  directed floods and the actual bridge regression.
- Metadata regenerated in 2.04 s with two workers; its size remains 633,513 bytes.
  Neither `arena_map.py` nor the exact navigation asset changed.
- Official checker inside Linux: **PASS 300/300**, no late answers, wrong ticks,
  bad lines or dropped queued answers. Startup 3,125 ms; p99 32.5 ms; max 34.8 ms.
  The wrapper asserted the actual 259-prism/774,680-sample map and matched all
  seven image Python sources to the repository.
- Full-prefix C1 replay: 1,045 observations, max action 43.21 ms, zero over 50 ms.
  Overall completed-route frames: 460/596 (77.2%); mean navigation 1.36 ms.
- In the 38.6–54.1 s jam window, completed-route frames are 83/90 (92.2%), versus
  cache-only 11/115 (9.6%). Search expansions are 109 versus 31,348; mean navigation
  2.32 versus 10.59 ms. Tactical fallbacks remain 49 versus 93.

Posthoc classification of all 156 actual window goals gives **144 YES, 12 UNKNOWN,
0 NO**, all inside the existing future zone. The 12 UNKNOWN frames are precisely
t39.1–40.2, when recorded feet are 1.64–4.81 m above terrain. They retain the same
low-ground objective, rather than the old high-ground zone-clamp fallback. Fourteen
of the fifteen original witness timestamps are YES; t40 is correctly UNKNOWN
while airborne. At t45, the selected existing cover point remains
`[-328.464,-8.536,-4.738]` with a completed live 36-node A* search.

These are conditional replays, not closed-loop score estimates. Timing-sensitive
differences between separate runs remain, and not every live call has navigation
budget. The diagnostic does not justify a general claim that all final goals are
physically reachable.

Evidence in `../game-interface-audit/`:

- `reachable-height-c1-linux.json`
- `reachable-height-c1-linux-witnesses.json`
- `reachable-height-official-checker.txt`

When combining this guard with another exact navigation asset, run
`python build_ground_reachability.py` again: metadata binds both the helper source
and the exact navigation asset. The included metadata is for this standalone
navcache-derived branch.
