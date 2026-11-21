# Upgrade eligibility during a planned weapon replacement

Based on retained baseline `39b6d509af8e82b0ceb9e1c430dd964674d7488e`. Upgrade scores and all combat/navigation/resource policies are unchanged. The existing weapon pickup action is computed once before choosing an upgrade. General upgrades and weapon upgrades supported by held, retained types remain eligible; the type being replaced is excluded. An incoming unheld type is not eligible until observed, because the protocol does not promise pick/take application ordering.

The captured private v4 fixture at4.5s previously selected `lightning_efficiency` while requesting lightning→laser in the same action. Both applied at4.9s; the weapon was never reacquired or used afterward. The corrected action selects `jets`, preserving the original `take:8040, drop:1`.

Validation:

- 135 unit/integration tests pass, including11 focused cases for the captured action, retained gun and second-slot upgrades, incoming weapon acknowledgement, failed swaps, unsupported-only offers, absent offers, empty slots, unchanged rank adjustments/ties, and configuration-defined requirements.
- Conditional selector replay across36 private traces,68 offers and258 offer frames changes only2 offers/7frames, both planned lightning→laser swaps. None of the eight current diagnostic traces changes an offer. This is fixed-observation policy analysis, not a counterfactual match or score.
- Restricted Linux validation: linux/amd64, one CPU,512MB, no network, read-only filesystem, uid65534, real map259prisms. Captured full `Bot.act` returns the intended upgrade/swap in11.40ms.
- Checker and child bot run inside that container: `python3 /kit/check/check.py --map-dir /arena -- python3 -u /bot/bot.py`.300/300 on time; no bad, wrong-tick, or late answers; readiness3100ms; p50 12.0/p90 27.2/p99 32.5/max34.3ms. `git diff --check` passes.

Risks: the planned take can fail, making the alternative upgrade less valuable than one for the old weapon. The next observation restores old-type eligibility when no replacement is requested. An unsupported-only offer emits no pick and can reach the server default if no supported choice becomes available before expiry. Weapon upgrades persist and might matter after a later reacquisition, so this is an intentional current-loadout policy, not proof of globally optimal value. These cases are covered synthetically; no private game or official score was obtained for this candidate.

Runtime `bot.py` SHA256: `05a4335a3d398bd49a05c216cd19f19f1723f2556de76987ab0015d376d46012`. Combat, tactical, arena and Dockerfile are unchanged from the baseline. The separate private-adapter pick deduplication is not included.
