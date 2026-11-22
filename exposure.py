"""Bounded directional exposure queries, separate from weapon aiming.

These are geometry samples, not hit probabilities or an enemy-DPS simulator.
Blocked samples do not prove that every point on the full body is shielded.
Enemy upgrades, cooldowns and future aim are unavailable. Mech muzzle/body
geometry uses configured bases and observed cube growth. NPC muzzle height
uses config.npc.muzzle_height when present, otherwise the body's top as an
explicit model assumption. Range and aim do not turn a blocked/unknown query
into a safe result. Mortar arcs are unmodeled and remain uncertain.

Only immutable map rays are cached, with exact ordered endpoints and no
coordinate rounding. Construct a new model or clear_cache() if geometry changes.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class ExposureResult:
    clear: int
    blocked: int
    unknown: int
    rays: int = 0
    indirect_unknown: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def visible(self):
        """True: a clear sample; False: all blocked; None: unresolved."""
        if self.clear:
            return True
        if self.unknown or self.indirect_unknown:
            return None
        return False

    @property
    def fraction(self):
        """Equal-weight clear-sample fraction, only when fully resolved."""
        if self.unknown or self.indirect_unknown:
            return None
        return self.clear / max(1, self.clear + self.blocked)

    @property
    def lower_fraction(self):
        return self.clear / max(1, self.clear + self.blocked + self.unknown)

    @property
    def upper_fraction(self):
        if self.indirect_unknown:
            return 1.0
        return (self.clear + self.unknown) / max(1, self.clear + self.blocked + self.unknown)

    @property
    def conservative_fraction(self):
        """A binary risk gate: uncertainty is never interpreted as safety."""
        return 0.0 if self.visible is False else 1.0


class ExposureModel:
    def __init__(self, config, line_of_fire=None, *, cache_size=512):
        self.config = config
        self.line_of_fire = line_of_fire
        self.cache_size = max(0, int(cache_size))
        self._cache = OrderedDict()
        self._frame = object()
        self._remaining = None

    def clear_cache(self):
        self._cache.clear()

    def begin_frame(self, token, *, ray_budget=12):
        """Optional shared new-ray cap across all queries in one observation.

        Repeating the same token cannot replenish the allowance. Cache hits do
        not consume it. The caller controls the token and deadline independently.
        """
        if token != self._frame:
            self._frame = token
            self._remaining = max(0, int(ray_budget))

    def self_stats(self, me):
        """Effective body dimensions; live eye/muzzle values are already scaled."""
        stats = {**self.config.get('mech', {}), **me.get('stats', {})}
        scale = 1 + self.config.get('cubes', {}).get('size_per_cube', .05) * me.get('cubes', 0)
        for name, default in (('radius', 2.5), ('height', 9.0)):
            stats[name] = stats.get(name, default) * scale
        for name, default in (('eye_height', 8.0), ('muzzle_height', 7.0)):
            if name not in me.get('stats', {}):
                stats[name] = self.config.get('mech', {}).get(name, default) * scale
        return stats

    def _actor_geometry(self, actor):
        if actor.get('kind') == 'npc':
            base = self.config.get('npc', {})
            height = float(base.get('height', 3.5))
            return height, float(base.get('muzzle_height', height))
        base = self.config.get('mech', {})
        scale = 1 + self.config.get('cubes', {}).get('size_per_cube', .05) * actor.get('cubes', 0)
        return float(base.get('height', 9.0)) * scale, float(base.get('muzzle_height', 7.0)) * scale

    def _ray(self, source, target, deadline, remaining):
        key = (tuple(source), tuple(target))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key], False, None
        if self.line_of_fire is None:
            return None, False, 'geometry_unavailable'
        if remaining <= 0 or self._remaining == 0:
            return None, False, 'ray_budget'
        if deadline is not None and time.perf_counter() >= deadline:
            return None, False, 'deadline'
        if self._remaining is not None:
            self._remaining -= 1
        # A cooperative deadline cannot interrupt an individual geometry call.
        try:
            value = self.line_of_fire(source, target)
        except Exception as error:
            return None, True, 'geometry_error:' + type(error).__name__
        if not isinstance(value, bool):
            return None, True, 'geometry_unknown'
        if self.cache_size:
            self._cache[key] = value
            self._cache.move_to_end(key)
            if len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return value, True, None

    def _samples(self, source, position, height, *, deadline, max_rays, width_radius=None,
                 indirect_unknown=False, reasons=()):
        # As in the existing target controller, sample mid and upper body.
        # Stop on the first clear sample: it already establishes exposure and
        # saves the second ray. Bounds preserve the unresolved sample explicitly.
        # Recovery checks upper body first: low cover frequently hides the
        # center while leaving the head/shoulders exposed. Other users retain
        # the original center-first order.
        fractions = (.9, .5) if width_radius is not None else (.5, .9)
        targets = [(position[0], position[1], position[2] + height * fraction)
                   for fraction in fractions]
        if width_radius is not None:
            dx, dy = position[0] - source[0], position[1] - source[1]
            distance = math.hypot(dx, dy)
            ux, uy = (-dy / distance, dx / distance) if distance else (1., 0.)
            targets.extend((position[0] + side * width_radius * .8 * ux,
                            position[1] + side * width_radius * .8 * uy,
                            position[2] + height * .9) for side in (-1, 1))
        clear = blocked = rays = checked = 0
        reasons = list(reasons)
        for target in targets:
            value, fresh, reason = self._ray(source, target, deadline, max_rays - rays)
            rays += int(fresh)
            if reason is not None and reason not in reasons:
                reasons.append(reason)
            if value is True:
                clear += 1
                checked += 1
                break
            if value is False:
                blocked += 1
                checked += 1
            elif reason in ('deadline', 'ray_budget', 'geometry_unavailable'):
                break
        return ExposureResult(clear, blocked, len(targets) - checked, rays,
                              indirect_unknown, tuple(reasons))

    def incoming(self, me, actor, *, position=None, effective_stats=None,
                 deadline=None, max_rays=2, include_width=False, conservative_only=False):
        """Enemy muzzle -> our body at current or proposed feet position.

        effective_stats, if passed, must already contain the cube-scaled body
        dimensions (e.g. Bot.stats(me)); otherwise live observation stats are
        interpreted using self_stats(). Missing/unknown weapons and mortar
        prevent a blocked straight-ray result from declaring the actor safe.
        conservative_only skips direct samples when unmodeled weapons already
        force binary risk. It preserves uncertainty, not direct-visibility detail;
        callers needing clear/blocked samples must keep the default False.
        """
        stats = effective_stats if effective_stats is not None else self.self_stats(me)
        position = me['pos'] if position is None else position
        if actor.get('kind') == 'npc':
            kinds = ['npc']
        else:
            kinds = actor.get('weapons')
        unknown_weapons = kinds is None or any(kind not in ('gun', 'laser', 'lightning', 'mortar', 'npc') for kind in kinds)
        indirect = unknown_weapons or 'mortar' in (kinds or ())
        if kinds == []:
            return ExposureResult(0, 0, 0, reasons=('no_held_weapon',))
        if conservative_only and indirect:
            # Every possible direct-ray result still has conservative_fraction=1.
            # This query is fully priced as uncertain; no geometry deadline or
            # ray-budget failure occurred, so do not fabricate either reason.
            return ExposureResult(0, 0, 4 if include_width else 2,
                                  indirect_unknown=True, reasons=('unmodeled_weapon_path',))
        if kinds is not None and not any(kind in ('gun', 'laser', 'lightning', 'npc') for kind in kinds):
            return ExposureResult(0, 0, 2, indirect_unknown=True,
                                  reasons=('unmodeled_weapon_path',))
        _, muzzle = self._actor_geometry(actor)
        source = (actor['pos'][0], actor['pos'][1], actor['pos'][2] + muzzle)
        reasons = ('unmodeled_weapon_path',) if indirect else ()
        return self._samples(source, position, stats['height'], deadline=deadline,
                             max_rays=max(0, int(max_rays)),
                             width_radius=stats['radius'] if include_width else None,
                             indirect_unknown=indirect, reasons=reasons)

    def outgoing(self, me, actor, *, position=None, effective_stats=None,
                 deadline=None, max_rays=2):
        """Our muzzle -> enemy body; geometry only, not permission to fire.

        Actual range, aim, cooldowns, mortar arcs and weapon timing remain the
        combat controller's responsibility. This result is not incoming risk.
        """
        stats = effective_stats if effective_stats is not None else self.self_stats(me)
        position = me['pos'] if position is None else position
        height, _ = self._actor_geometry(actor)
        source = (position[0], position[1], position[2] + stats['muzzle_height'])
        return self._samples(source, actor['pos'], height, deadline=deadline,
                             max_rays=max(0, int(max_rays)))
