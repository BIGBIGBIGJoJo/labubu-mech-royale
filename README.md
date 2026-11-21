# labubu — Mech Royale

An adaptive, map-aware bot for the Builders Buildathon 2026 Mech Royale track.
The controller proactively hunts current visible enemies, prioritizes feasible
short kills, approaches useful weapon range and collects valuable resources.
It combines collision-aware navigation, moving-target interception, recovery,
anticipatory zone movement, and selective loot.

## Run

Python 3.13, standard library only. The entry point reads `mechfight/1` JSON lines
from stdin and flushes one action per newest observation to stdout.

```sh
python -u bot.py
python check/check.py -- python -u bot.py
docker build --platform linux/amd64 -t labubu-mech-royale .
python check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --memory-swap 512m --pids-limit 128 --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" labubu-mech-royale
```

On PowerShell, use `-v "${PWD}/arena:/arena:ro"` for the mount argument.
The checker replays recorded observations. Passing it confirms protocol
conformance; it does **not** establish a gameplay score.

## Design

See [DESIGN.md](DESIGN.md) for the competition requirements, strategy,
implementation plan, limits, and evaluation process.
See [AGGRESSIVE_PLAN.md](AGGRESSIVE_PLAN.md) for the current **6.0** target and
the user's greedy, aggressive kill-oriented objective. Detailed agent plans:
[movement](MOVEMENT_STRATEGY_PLAN.md), [fire](FIRE_STRATEGY_PLAN.md), and
[orchestration](ORCHESTRATION_STRATEGY_PLAN.md).
The previous selective objective is historical in [AGENT_STRATEGY_PLAN.md](AGENT_STRATEGY_PLAN.md).
Implemented boost/recharge behavior is documented in [BOOST_PLAN.md](BOOST_PLAN.md),
and the implemented recovery escape in [RECOVERY_FOLLOWUP_PLAN.md](RECOVERY_FOLLOWUP_PLAN.md).
The separate navigation-stall diagnostic is described in
[NAVIGATION_RECOVERY_PLAN.md](NAVIGATION_RECOVERY_PLAN.md), and the validated
fractional-speed tactical candidate in [TACTICAL_RECOVERY_PLAN.md](TACTICAL_RECOVERY_PLAN.md).
Local collision-clear movement does not establish global route connectivity;
see [VALIDATION.md](VALIDATION.md) for results tied to exact candidate versions.
[SELECTIVE_V4_PLAN.md](SELECTIVE_V4_PLAN.md) records the historical selective
controller; its evidence and fixed finishing-deadline gates are not active in aggressive-v1.
Earlier experiments remain documented in [STRATEGY_V2.md](STRATEGY_V2.md).

- `bot.py`: strategy, recovery, upgrades, resource completion, and zone prediction.
- `arena_map.py`: spatial index, terrain, solid geometry, bounded navigation.
- `combat.py`: shared aim arbitration and weapon control.
- `engagement.py`: proactive target selection, short-kill estimates, focus and reachability;
  the prior selective controller remains separately tested.
- `positioning.py`: retained selective-policy escape/zone/exposure assessment;
  the aggressive root does not use its finish-admission gate.
- `tactical.py`: bounded physical trajectories, swept projectile avoidance, and exposure.
- `mechfight.py`: official stdin/stdout wrapper.
- `check/`, `arena/`, `protocol.md`, `mechfight.schema.json`: official kit resources.
- `tests/`: behavioral and geometry regression tests.

The bot uses configuration values sent by the server and upgraded self/weapon
stats. It does not use network access, remote models, hidden seeds, or external
services during a match. Strategy thresholds are explicit engineering choices,
not claims of optimal play.

## Attribution and license

Released under the MIT License as required by the event. The original controller,
navigation, and combat code were developed with AI assistance for this entry.
The following preexisting material comes from the official
[Mech Royale starter kit](https://www.joinbuilders.org/buildathon/tracks/builders/files/mechfight-kit.tar.gz):
`mechfight.py`, `protocol.md`, `mechfight.schema.json`, `check/`, and `arena/`.
The kit wrapper is retained for transport and generated type definitions.
No third-party runtime Python packages are used. The container uses the official
Python slim image, pinned by digest in `Dockerfile`.

Rules: [track](https://www.joinbuilders.org/buildathon/tracks/builders),
[event](https://www.joinbuilders.org/buildathon),
[protocol](https://www.joinbuilders.org/buildathon/tracks/builders/files/protocol.md?inline=1).
