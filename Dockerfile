FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS compiler
RUN apt-get update && apt-get install -y --no-install-recommends g++-14=14.2.0-19 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY terrain_kernel.cpp ./
RUN g++-14 -std=c++17 -O2 -fPIC -shared -fno-fast-math -ffp-contract=off -static-libstdc++ -static-libgcc terrain_kernel.cpp -o libterrain.so

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
WORKDIR /bot
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY bot.py arena_map.py navigation_cache.py navigation-cache.bin ground_reachability.py ground-reachability.bin combat.py tactical.py terrain_kernel.py mechfight.py zone_resource.py ./
COPY --from=compiler /build/libterrain.so ./
USER 65534:65534
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
