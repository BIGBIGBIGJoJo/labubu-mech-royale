"""Short gun-reload shelter cycles; sampled direct protection, not invulnerability.

Only terrain walking is certified. Enemy muzzle dimensions use observed cubes
and configured base stats; hidden upgrades, future movement, indirect fire and
unobserved actors are not inferred. Every incomplete dynamic proof falls back.
"""
from __future__ import annotations

import math
import time

from combat import angle_delta
from zone_resource import ZoneResourcePlanner, circle_at


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class ReloadCover:
    # Small experimental policy bounds, not engine guarantees.
    BUDGET_S = .008
    LOCAL_RADIUS = 20.
    SHELTER_DISTANCE = 6.
    ARRIVAL = .35
    NO_PROGRESS_S = 1.
    PROGRESS_M = .3

    def __init__(self, config, arena, combat):
        self.config, self.arena, self.combat = config, arena, combat
        self.ground = ZoneResourcePlanner(config, arena)
        self.pair = None
        self.last_report = {}
        self._geometry = {}
        self._cursor = 0
        self._search_key = None
        self._blocked_until = -1.

    def cancel(self, reason):
        if self.pair is not None:
            self._blocked_until = max(self._blocked_until, self.pair['reload_end'])
        self.pair = None
        self.last_report = {'active': False, 'admitted': False, 'reason': reason}

    def retain_target(self, obs, ordinary, eligible, stats=None):
        """Keep a currently observed target across our own outgoing LOS loss."""
        if self.pair is None:
            return ordinary
        me = obs['self']
        gun = self._gun(me)
        if (not me.get('grounded') or not me.get('in_zone') or gun is None or
                gun[0] != self.pair['slot'] or not self.ground._ground_scope(me['pos']) or
                obs['t'] > self.pair['reload_end']+self.combat.action_dt*2 or
                (stats is not None and (stats['radius'], stats['height']) !=
                 (self.pair['radius'], self.pair['height']))):
            self.cancel('structural_change')
            return ordinary
        target = next((a for a in obs.get('mechs', ())
                       if a['id'] == self.pair['target_id'] and a.get('kind') == 'mech'
                       and (a.get('hp') is None or a['hp'] > 0)), None)
        if (not eligible or target is None or
                (ordinary is not None and ordinary['id'] != target['id'])):
            self.cancel('priority_or_target_changed')
            return ordinary
        return target

    def _gun(self, me):
        equipped = [(i, w) for i, w in enumerate(me['weapons']) if w]
        return equipped[0] if len(equipped) == 1 and equipped[0][1]['kind'] == 'gun' else None

    def _same_report(self, report, obs, target, slot):
        return (report is not None and report['tick'] == obs['tick'] and
                report['t'] == obs['t'] and report['target_id'] == target['id'] and
                report['slot'] == slot and report['pos'] == tuple(obs['self']['pos']) and
                report['solution']['clear'])

    def _known_zone_until(self, obs):
        """Extend only a config-matched announced circle through its next hold."""
        zone = obs['zone']
        end = zone['shrink_end']
        elapsed = 0.
        phases = self.config.get('zone', {}).get('phases', ())
        for i, phase in enumerate(phases):
            begin = elapsed + phase['hold_s']
            elapsed = begin + phase['shrink_s']
            if (abs(begin-zone['shrink_start']) < .02 and abs(elapsed-end) < .02
                    and abs(phase['radius']-zone['next_radius']) < .02):
                if i + 1 < len(phases):
                    return end + phases[i+1]['hold_s']
                return end
        return end

    def _zone_safe(self, obs, points, radius, until):
        if until > self._known_zone_until(obs) + 1e-7:
            return False
        # Distance to a linearly moving center minus a linearly changing radius
        # is convex: interval endpoints bound every intervening instant and
        # every point on the straight P-S segment.
        times = {obs['t'], until}
        for t in (obs['zone']['shrink_start'], obs['zone']['shrink_end']):
            if obs['t'] < t < until:
                times.add(t)
        for t in times:
            center, r = circle_at(obs, max(0., t-obs['t']))
            if any(distance(p, center) + radius + 1. > r for p in points):
                return False
        return True

    def _cube_corridor(self, obs, a, b):
        # Reject possible incidental growth rather than rely on detecting the
        # enlarged body only after it has entered a narrow passage.
        cubes = obs.get('cubes', ())
        if len(cubes) > 256:
            return True
        dx, dy = b[0]-a[0], b[1]-a[1]
        length2 = dx*dx + dy*dy
        reach = self.config['cubes']['pickup_radius']
        for cube in cubes:
            p = cube['pos']
            f = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(1e-12, length2)))
            if math.hypot(p[0]-a[0]-f*dx, p[1]-a[1]-f*dy) <= reach:
                return True
        return False

    def _route(self, a, b, stats, deadline):
        if time.perf_counter() >= deadline:
            return None
        # This cache belongs to one immutable ArenaMap instance. Exact endpoints
        # and actual dimensions are mandatory; no rounded geometry reuse.
        key = (tuple(a), tuple(b), stats['radius'], stats['height'])
        if key in self._geometry:
            return self._geometry[key]
        valid = (self.ground._ground_scope(a) and self.ground._ground_scope(b)
                 and self.arena.point_clear(a, stats['radius'], stats['height'])
                 and self.arena.point_clear(b, stats['radius'], stats['height'])
                 and self.ground._ground_segment(a, b, stats['radius'], deadline))
        if time.perf_counter() >= deadline:
            return None
        if valid:
            valid = self.arena.move_clear(a, b, stats['radius'], stats['height'])
        if time.perf_counter() >= deadline:
            return None
        if len(self._geometry) >= 128:
            self._geometry.clear()
        self._geometry[key] = bool(valid)
        return bool(valid)

    def _actors(self, obs):
        actors = obs.get('mechs', ())
        if len(actors) > 16:
            return None
        # Mortar arcs and lightning chains require a different protection model.
        # Do not label a direct-ray wall as protection from either weapon.
        if any(a.get('kind') != 'mech' or not a.get('weapons') or
               not set(a['weapons']) <= {'gun', 'laser'} for a in actors):
            return None
        return actors

    def _protected(self, point, actors, stats, deadline):
        if time.perf_counter() >= deadline:
            return None
        key = (tuple(point), tuple(a['id'] for a in actors), stats['radius'], stats['height'])
        if key in self._incoming:
            return self._incoming[key]
        for actor in actors:
            muzzle = self.config['mech']['muzzle_height'] * (1 +
                self.config['cubes']['size_per_cube']*actor.get('cubes', 0))
            source = (*actor['pos'][:2], actor['pos'][2]+muzzle)
            dx, dy = point[0]-source[0], point[1]-source[1]
            norm = max(.001, math.hypot(dx, dy))
            # Upper-center first gives a cheap rejection for open terrain.
            for side, fraction in ((0, .9), (0, .15), (0, .5), (-.8, .9), (.8, .9)):
                if time.perf_counter() >= deadline:
                    return None
                end = (point[0]-side*stats['radius']*dy/norm,
                       point[1]+side*stats['radius']*dx/norm,
                       point[2]+fraction*stats['height'])
                clear = self.arena.line_of_fire(source, end)
                if time.perf_counter() >= deadline:
                    return None
                if clear:
                    self._incoming[key] = False
                    return False
        self._incoming[key] = True
        return True

    def _candidates(self, p, stats, deadline):
        shift = stats['radius'] - self.arena._cover_base_radius
        extent = self.LOCAL_RADIUS + abs(shift)
        found, seen = [], set()
        for ix in range(math.floor((p[0]-extent)/self.arena.BIN), math.floor((p[0]+extent)/self.arena.BIN)+1):
            if time.perf_counter() >= deadline:
                return
            for iy in range(math.floor((p[1]-extent)/self.arena.BIN), math.floor((p[1]+extent)/self.arena.BIN)+1):
                if time.perf_counter() >= deadline:
                    return
                for index in self.arena._cover_bins.get((ix, iy), ()):
                    if time.perf_counter() >= deadline:
                        return
                    if len(seen) >= 128:
                        break
                    if index in seen:
                        continue
                    seen.add(index)
                    x, y, _, nx, ny, _ = self.arena._cover[index]
                    x, y = x+nx*shift, y+ny*shift
                    d = math.hypot(x-p[0], y-p[1])
                    if 2. <= d <= self.LOCAL_RADIUS:
                        found.append((d, index, x, y))
                if len(seen) >= 128:
                    break
            if len(seen) >= 128:
                break
        found.sort()
        for d, index, x, y in found:
            if time.perf_counter() >= deadline:
                return
            f = min(1., self.SHELTER_DISTANCE/d)
            x, y = p[0]+f*(x-p[0]), p[1]+f*(y-p[1])
            yield (x, y, self.arena.ground_height(x, y))

    def _travel(self, a, b, velocity, stats):
        # Walk-speed timing estimate includes worst-direction braking distance,
        # braking time, acceleration/deceleration and an observation/action
        # delay. Tactical detours and target motion are not predicted; this
        # estimate never advances an arrival phase without observation.
        speed, accel = max(.1, stats['walk_speed']), max(.1, stats['ground_accel'])
        current_speed = math.hypot(*velocity[:2])
        braking_distance = current_speed*current_speed/(2*accel)
        return ((distance(a, b)+braking_distance)/speed + speed/accel +
                current_speed/accel + self.combat.action_dt)

    def _turn(self, me, solution, stats):
        return max(abs(angle_delta(solution['aim'][0], me['aim'][0]))/max(.1, stats['turn_rate']),
                   abs(solution['aim'][1]-me['aim'][1])/max(.1, stats['pitch_rate']))

    def _outgoing(self, p, obs, target, stats, gun, deadline):
        if time.perf_counter() >= deadline:
            return None
        _, height = self.combat._body(target)
        source = [*p[:2], p[2]+stats['muzzle_height']]
        center = [*target['pos'][:2], target['pos'][2]+height*.5]
        solution = self.combat._direct_solution('gun', self.combat._stats(gun), source, center,
            target.get('vel', (0, 0, 0)), stats['radius']+.5,
            (stats['min_pitch'], stats['max_pitch']), height)
        return solution if time.perf_counter() < deadline and solution and solution['clear'] else None

    def step(self, obs, target, stats, eligible, deadline):
        begin = time.perf_counter()
        deadline = min(deadline, begin+self.BUDGET_S)
        self.last_report = {'active': False, 'admitted': False, 'actual_protected': None,
                            'static_complete': False, 'incoming_complete': False}
        self._incoming = {}  # Exact points and unchanged actors only within this call.
        goal = self._step(obs, target, stats, eligible, deadline)
        self.last_report['ms'] = (time.perf_counter()-begin)*1000
        if self.pair is not None:
            self.last_report.update({k: self.pair[k] for k in ('phase', 'target_id', 'P', 'S',
                'started_at', 'entry_tick', 'radius', 'height', 'reload_end')})
            self.last_report['active'] = True
        return goal

    def _step(self, obs, target, stats, eligible, deadline):
        me, t = obs['self'], obs['t']
        equipped = self._gun(me)
        if (not eligible or target is None or target.get('kind') != 'mech' or
                (target.get('hp') is not None and target['hp'] <= 0) or
                not self.arena.available or not me.get('grounded') or not me.get('in_zone') or
                not getattr(self.arena, '_cover', None) or equipped is None or
                not self.ground._ground_scope(me['pos'])):
            self.cancel('ineligible')
            return None
        slot, gun = equipped
        actors = self._actors(obs)
        if actors is None or not any(a['id'] == target['id'] for a in actors):
            self.cancel('unsupported_threats')
            return None
        others = [a for a in actors if a['id'] != target['id']]
        p = tuple(me['pos'])
        if self.pair is not None:
            return self._continue(obs, target, actors, others, stats, gun, deadline)
        reload = gun.get('reload', 0.)
        if reload <= 0 or t < self._blocked_until or time.perf_counter() >= deadline:
            self.last_report['reason'] = 'no_reload_or_budget'
            return None
        report = self.combat.last_report
        if not self._same_report(report, obs, target, slot):
            self.last_report['reason'] = 'no_current_firing_solution'
            return None
        if self._protected(p, others, stats, deadline) is not True:
            self.last_report['reason'] = 'other_opponent_at_peek'
            return None
        solution = report['solution']
        key = (target['id'], stats['radius'], stats['height'], round(t+reload, 1))
        if key != self._search_key:
            self._search_key, self._cursor = key, 0
        candidates = list(self._candidates(p, stats, deadline))
        for _ in range(len(candidates)):
            if time.perf_counter() >= deadline:
                break
            s = candidates[self._cursor % len(candidates)]
            trip = (self._travel(p, s, me['vel'], stats) + self._travel(s, p, (0, 0), stats)
                    + self._turn(me, solution, stats))
            if (trip > reload or not self._zone_safe(obs, (p, s), stats['radius'], t+reload+self.combat.action_dt)
                    or self._cube_corridor(obs, p, s)):
                self._cursor += 1
                continue
            protected = self._protected(s, actors, stats, deadline)
            if protected is None:
                break  # Retry the unfinished candidate with fresh rays next call.
            if not protected:
                self._cursor += 1
                continue
            outbound = self._route(p, s, stats, deadline)
            if outbound is None:
                break
            if not outbound:
                self._cursor += 1
                continue
            returning = self._route(s, p, stats, deadline)
            if returning is None:
                break
            if not returning:
                self._cursor += 1
                continue
            self.pair = {'P': p, 'S': s, 'target_id': target['id'], 'slot': slot,
                         'radius': stats['radius'], 'height': stats['height'],
                         'phase': 'out', 'started_at': t, 'entry_tick': obs['tick'],
                         'reload_end': t+reload, 'progress_t': t, 'progress_d': distance(p, s)}
            self.last_report.update(admitted=True, static_complete=True, incoming_complete=True, reason='admitted')
            return s
        self.last_report['reason'] = 'no_complete_pair'
        return None

    def _continue(self, obs, target, actors, others, stats, gun, deadline):
        pair, me, t = self.pair, obs['self'], obs['t']
        p, P, S = tuple(me['pos']), pair['P'], pair['S']
        if (target['id'] != pair['target_id'] or self._gun(me)[0] != pair['slot'] or
                (stats['radius'], stats['height']) != (pair['radius'], pair['height']) or
                t > pair['reload_end']+self.combat.action_dt*2):
            self.cancel('body_target_or_cycle_changed')
            return None
        # Abort tactical displacement outside the fixed corridor; a new straight
        # connector still must be proved for smaller deviations within it.
        length = distance(P, S)
        if distance(p, P)+distance(p, S) > length+stats['radius']:
            self.cancel('displaced')
            return None
        if (not self._zone_safe(obs, (p, P, S), stats['radius'], pair['reload_end']+self.combat.action_dt)
                or self._cube_corridor(obs, p, S) or self._cube_corridor(obs, S, P)
                or self._cube_corridor(obs, p, P)):
            self.cancel('zone_or_growth')
            return None
        if self._protected(S, actors, stats, deadline) is not True or self._protected(P, others, stats, deadline) is not True:
            self.cancel('shelter_or_isolation_unknown')
            return None
        solution = self._outgoing(P, obs, target, stats, gun, deadline)
        if solution is None:
            self.cancel('return_shot_unknown')
            return None
        return_time = self._travel(p, P, me['vel'], stats)+self._turn(me, solution, stats)
        remaining = gun.get('reload', 0.)
        protected = None
        if pair['phase'] == 'hold' or distance(p, S) <= self.ARRIVAL:
            protected = self._protected(p, actors, stats, deadline)
            self.last_report['actual_protected'] = protected
            if pair['phase'] == 'hold' and protected is not True:
                self.cancel('actual_shelter_unknown')
                return None
            if protected is True and pair['phase'] == 'out':
                pair.update(phase='hold', progress_t=t, progress_d=0.)
        if remaining <= return_time:
            if pair['phase'] != 'return':
                pair.update(phase='return', progress_t=t, progress_d=distance(p, P))
        goal = P if pair['phase'] == 'return' else S
        if pair['phase'] == 'return' and distance(p, P) <= self.ARRIVAL and remaining <= 0:
            self.cancel('returned_ready')
            return None
        if (self._route(p, goal, stats, deadline) is not True or
                self._route(S, P, stats, deadline) is not True):
            self.cancel('current_route_unknown')
            return None
        d = distance(p, goal)
        if d < pair['progress_d']-self.PROGRESS_M:
            pair.update(progress_d=d, progress_t=t)
        if pair['phase'] != 'hold' and t-pair['progress_t'] >= self.NO_PROGRESS_S:
            self.cancel('no_observed_progress')
            return None
        self.last_report.update(static_complete=True, incoming_complete=True, reason='continuing')
        return goal
