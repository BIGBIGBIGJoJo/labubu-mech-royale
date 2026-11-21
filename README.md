# labubu — Mech Royale

An adaptive, map-aware bot for the Builders Buildathon 2026 Mech Royale track.
The controller combines bounded ground navigation, obstacle-aware firing,
moving-target interception, recovery, anticipatory zone movement, and selective loot.

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
See [STRATEGY_V2.md](STRATEGY_V2.md) for the 6.3 target, evidence, and next design.

- `bot.py`: strategy, recovery, upgrades, resource completion, and zone prediction.
- `arena_map.py`: spatial index, terrain, solid geometry, bounded navigation.
- `combat.py`: shared aim arbitration and weapon control.
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
