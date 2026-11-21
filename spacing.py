"""Conditional lightning approach model; this file does not connect to games.

Policy assumptions, not server facts: future straight-line movement/LOS; all
modeled shots hit; enemy weapons use base configuration and unknown magazines
are full/ready; no credit for unknown armor/upgrades or future regeneration.
Enemy movement toward us is reported but is not credited in the entry budget.
An ideal lightning hit suppresses a laser; observed beam timing only bounds the
next base-config release. These estimates do not establish a winning matchup.
"""
from __future__ import annotations

import math


class LightningApproach:
    MAX_FORECAST_S = 20.0  # Bounded policy horizon, not a game constant.
    ENTRY_BURSTS = 1.0
    CONTINUE_BURSTS = 0.0

    def __init__(self, config):
        self.config = config
        self.last_laser = {}
        self.short_until = {}
        self.committed = None
        self.last_report = None

    def observe(self, obs):
        for beam in obs.get('beams', []):
            if beam.get('kind') == 'laser':
                who = beam.get('by')
                fired = obs['t'] - max(0., beam.get('age', 0.))
                self.last_laser[who] = max(fired, self.last_laser.get(who, -math.inf))
        lightning = next((w for w in obs['self'].get('weapons', [])
                          if w and w['kind'] == 'lightning'), None)
        short_s = (lightning or {}).get('stats', {}).get(
            'short_s', self.config['weapons']['lightning']['short_s'])
        # Hit events have no within-observation timestamp. Use the earliest
        # possible hit in this decision interval, under-crediting remaining short.
        interval = self.config['match']['decide_every'] / self.config['match']['tick_hz']
        for event in obs.get('events', []):
            if (event.get('type') == 'hit' and event.get('weapon') == 'lightning'
                    and event.get('effect') == 'short'):
                target = event['target']
                until = obs['t'] - interval + short_s
                self.short_until[target] = max(until, self.short_until.get(target, -math.inf))

    def reset(self):
        self.committed = None
        self.last_report = None

    def applies(self, me, target):
        own = {w['kind'] for w in me.get('weapons', []) if w}
        enemy = set(target.get('weapons', []))
        return (own == {'gun', 'lightning'} and target.get('kind') == 'mech'
                and 'laser' in enemy and enemy <= {'gun', 'laser'})

    def _multiplier(self, actor):
        c = self.config['cubes']
        return 1 + c['damage_per_cube'] * min(c['stat_cap'], actor.get('cubes', 0))

    @staticmethod
    def _gun_events(stats, *, cooldown=0., ammo=None, reload=0., horizon=20., flight=0.):
        """Magazine schedule. Empty magazine reloads before the next shot."""
        capacity = int(stats['mag'])
        left = capacity if ammo is None else int(ammo)
        when = max(0., cooldown, reload)
        if reload > 0:
            left = capacity
        elif left <= 0:
            when = max(when, stats['reload'])
            left = capacity
        result = []
        for _ in range(128):
            if when + flight > horizon:
                break
            result.append(when + flight)
            left -= 1
            if not left:
                when += stats['reload']
                left = capacity
            else:
                when += stats['cooldown']
        return result

    def assess(self, obs, target, *, visible_count=1, los=True):
        me = obs['self']
        if not self.applies(me, target):
            self.reset()
            return None
        hp = target.get('hp')
        if (isinstance(hp, bool) or not isinstance(hp, (int, float))
                or not math.isfinite(hp) or hp <= 0):
            # Enemy HP is optional under the visibility settings. Do not infer
            # hidden health or enter a fight with an invalid finish comparison.
            self.committed = None
            self.last_report = dict(allowed=False, reason='unknown_hp', continuing=False)
            return self.last_report
        stats = {**self.config['mech'], **me.get('stats', {})}
        own = {w['kind']: w for w in me['weapons'] if w}
        gun = {**self.config['weapons']['gun'], **own['gun'].get('stats', {})}
        lightning = {**self.config['weapons']['lightning'], **own['lightning'].get('stats', {})}
        enemy_gun = self.config['weapons']['gun']
        laser = self.config['weapons']['laser']
        dx, dy = target['pos'][0] - me['pos'][0], target['pos'][1] - me['pos'][1]
        distance = math.hypot(dx, dy)
        velocity = target.get('vel', [0, 0, 0])
        radial = (velocity[0] * dx + velocity[1] * dy) / max(distance, 1.e-9)
        cube_size = 1 + self.config['cubes']['size_per_cube'] * target.get('cubes', 0)
        target_center = target['pos'][2] + self.config['mech']['height'] * cube_size * .5
        muzzle_height = stats['muzzle_height']
        if 'muzzle_height' not in me.get('stats', {}):
            muzzle_height *= 1 + self.config['cubes']['size_per_cube'] * me.get('cubes', 0)
        dz = target_center - me['pos'][2] - muzzle_height
        reach = math.sqrt(max(0., lightning['range'] ** 2 - dz ** 2))
        gap = max(0., distance - reach)
        relative_speed = stats['walk_speed'] - radial
        relative_contact = gap / relative_speed if relative_speed > 0 else math.inf
        budget_speed = stats['walk_speed'] - max(0., radial)
        contact = gap / budget_speed if budget_speed > 0 else math.inf
        yaw_error = abs((math.atan2(dy, dx) - me['aim'][0] + math.pi) % math.tau - math.pi)
        turn_delay = max(0., yaw_error - math.radians(lightning['cone_deg'])) / stats['turn_rate']
        contact = max(contact, own['lightning'].get('cooldown', 0.), turn_delay)
        if abs(dz) >= lightning['range']:
            contact = relative_contact = math.inf
        cycle = laser['cooldown'] + laser['charge']
        energy_reserve = stats['boost_drain'] * cycle
        lightning_shots = max(0, int((me['energy'] - energy_reserve) // lightning['energy']))
        own_scale = self._multiplier(me)
        enemy_scale = self._multiplier(target) * (1 - stats.get('armor', 0.))
        if yaw_error > math.radians(stats['front_arc_deg']) * .5:
            enemy_scale *= stats['rear_mult']
        enemy_kinds = set(target['weapons'])
        gun_damage = enemy_gun['damage'] * enemy_scale if 'gun' in enemy_kinds else 0.
        laser_damage = laser['damage'] * enemy_scale
        burst = gun_damage + laser_damage
        outgoing = [(t, gun['damage'] * own_scale, 'gun') for t in self._gun_events(
            gun, cooldown=own['gun'].get('cooldown', 0.), ammo=own['gun'].get('ammo'),
            reload=own['gun'].get('reload', 0.), horizon=self.MAX_FORECAST_S,
            flight=math.hypot(distance, dz) / gun['speed'])]
        for i in range(min(lightning_shots, 128)):
            when = contact + i * lightning['cooldown']
            if when <= self.MAX_FORECAST_S:
                outgoing.append((when, lightning['damage'] * own_scale, 'lightning'))
        outgoing.sort()
        damage, finish, used_lightning = 0., math.inf, []
        for when, dealt, kind in outgoing:
            damage += dealt
            if kind == 'lightning':
                used_lightning.append(when)
            if damage >= hp:
                finish = when
                break
        # Charging has unknown age, so a full release can be immediate. A
        # noncharging laser needs at least min_charge. The min-charge period
        # with full damage deliberately overestimates its base-config capacity.
        first_laser = 0. if target.get('charging') else laser['min_charge']
        seen = self.last_laser.get(target['id'])
        if seen is not None:
            first_laser = max(first_laser, seen + laser['cooldown'] + laser['min_charge'] - obs['t'])
        known_short = max(0., self.short_until.get(target['id'], -math.inf) - obs['t'])
        first_laser = max(first_laser, known_short + laser['min_charge'] if known_short else 0.)
        horizon = min(finish, self.MAX_FORECAST_S)
        incoming = gun_damage * len(self._gun_events(enemy_gun, horizon=horizon))
        without_short_releases = max(0, math.floor((horizon - first_laser + 1.e-9)
                                                   / (laser['cooldown'] + laser['min_charge'])) + 1)
        without_short = incoming + laser_damage * without_short_releases
        shots_laser = 0
        when = first_laser
        for _ in range(128):
            if when > horizon:
                break
            # Treat simultaneous first contact/release as incoming; do not rely
            # on unverified actor update ordering to win that exchange.
            short_ends = [hit + lightning['short_s'] for hit in used_lightning
                          if hit < when <= hit + lightning['short_s']]
            if short_ends:
                when = max(short_ends) + laser['min_charge']
                continue
            incoming += laser_damage
            shots_laser += 1
            when += laser['cooldown'] + laser['min_charge']
        continuing = self.committed == target['id']
        reserve = burst * (self.CONTINUE_BURSTS if continuing else self.ENTRY_BURSTS)
        margin = me['hp'] - incoming - reserve
        allowed = (visible_count <= 1 and los and math.isfinite(contact)
                   and math.isfinite(finish) and lightning_shots > 0 and margin > 0)
        reason = ('multiple_threats' if visible_count > 1 else 'no_los' if not los
                  else 'unreachable' if not math.isfinite(contact)
                  else 'energy_reserve' if not lightning_shots else 'forecast_exhausted'
                  if not math.isfinite(finish) else 'survival_margin' if margin <= 0
                  else 'continue' if continuing else 'enter')
        self.committed = target['id'] if allowed else None
        finite = lambda value: value if math.isfinite(value) else None
        self.last_report = dict(allowed=allowed, reason=reason, continuing=continuing,
            distance=distance, contact_s=finite(contact), relative_contact_s=finite(relative_contact),
            finish_s=finite(finish), incoming=incoming, reserve=reserve, margin=margin,
            energy_reserve=energy_reserve, lightning_shots=len(used_lightning),
            laser_releases=shots_laser, phase_known=seen is not None,
            known_short_remaining_s=known_short,
            incoming_without_future_short=without_short,
            margin_without_future_short=me['hp'] - without_short - reserve,
            laser_releases_without_future_short=without_short_releases)
        return self.last_report
