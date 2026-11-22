"""Bounded one-opponent probes; estimates are policy models, never guaranteed kills."""
from __future__ import annotations

from collections import deque
import math
import time


def angle_delta(a, b):
    return (a-b+math.pi) % math.tau-math.pi


class DuelController:
    # Experimental policy parameters. The health latch retains baseline values.
    LOW_HP = .55
    HEALED_HP = .93
    ATTACKER_MEMORY_S = 3.0
    LOST_EXPOSED_MEMORY_S = 1.0
    PROBE_S = 2.0
    MAX_PROBE_S = 3.5
    PROGRESS_S = 2.0
    LOSS_FRACTION = .25
    REMAINING_S = 8.0
    MAX_DUEL_S = 20.0
    FINISH_S = 1.5
    RETRY_S = 6.0
    ENCOUNTER_MEMORY_S = 6.0
    MAX_PENDING_HIT_S = 1.0

    def __init__(self, config):
        self.config = config
        self.health_recover = False
        self.attackers = {}
        self.last_exposed = {}
        self.dead = set()
        self.encounter = None
        self.last_tick = None
        self.last_combat = -math.inf
        self.report = {}

    def _range(self, kinds):
        ranges = []
        for kind in kinds:
            weapon = self.config['weapons'].get(kind, {})
            if kind == 'mortar':
                ranges.append(weapon.get('speed', 0)**2/max(weapon.get('gravity', 1), 1e-6))
            else:
                ranges.append(weapon.get('range', 0))
        return max(ranges, default=0)

    def _events(self, obs):
        if obs['tick'] == self.last_tick:
            return
        self.last_tick = obs['tick']
        now = obs['t']
        for event in obs.get('events', ()):
            if event['type'] in ('hit', 'damaged'):
                self.last_combat = now
            if event['type'] == 'kill':
                self.dead.add(event['target'])
                self.attackers.pop(event['target'], None)
                self.last_exposed.pop(event['target'], None)
            if event['type'] == 'damaged':
                ident = event.get('by')
                if (event.get('weapon') != 'zone' and isinstance(ident, int)
                        and 0 <= ident < self.config['match']['mechs']
                        and ident != obs['self']['id']):
                    self.attackers[ident] = now
                if self.encounter is not None:
                    # Dealt/taken events, not net HP: cubes and healing do not
                    # reimburse the health already spent on this encounter.
                    self.encounter['spent'] += max(0., event.get('amount', 0.))
            if (event['type'] == 'hit' and self.encounter is not None
                    and event.get('target') == self.encounter['target'] and event.get('amount', 0.) > 0):
                self.encounter['hits'].append((now, max(0., event.get('amount', 0.))))
                self.encounter['pending_hit_until'] = None

    def ideal_schedule(self, obs, target, stats):
        """Own live cooldown/reload/turn/flight schedule, ideal unarmored hits.

        Shared aim, moving targets, enemy armor, misses and future geometry are
        not simulated. This is a readiness/finish bound, not expected DPS.
        """
        me = obs['self']
        cube = self.config['cubes']
        scale = 1 + cube['damage_per_cube']*min(me['cubes'], cube['stat_cap'])
        target_h = self.config['mech']['height']*(1+cube['size_per_cube']*target.get('cubes', 0))
        dx, dy = target['pos'][0]-me['pos'][0], target['pos'][1]-me['pos'][1]
        horizontal = math.hypot(dx, dy)
        yaw = math.atan2(dy, dx)
        events = []
        first_opportunities = []
        horizon = self.MAX_DUEL_S + self.FINISH_S
        for weapon in me.get('weapons', ()):
            if not weapon:
                continue
            kind = weapon['kind']
            live = {**self.config['weapons'][kind], **weapon.get('stats', {})}
            muzzle = stats['height']+.5 if kind == 'mortar' else stats['muzzle_height']
            dz = target['pos'][2]+target_h*.5-me['pos'][2]-muzzle
            distance = math.hypot(horizontal, dz)
            pitch = math.atan2(dz, max(horizontal, 1e-9))
            flight = 0.
            if kind == 'mortar':
                v, g = live['speed'], live['gravity']
                discriminant = v**4-g*(g*horizontal**2+2*dz*v*v)
                if discriminant < 0 or horizontal < 1e-6:
                    continue
                pitch = math.atan((v*v-math.sqrt(discriminant))/(g*horizontal))
                flight = horizontal/max(1e-6, v*math.cos(pitch))
            elif distance > live['range']:
                continue
            elif kind == 'gun':
                flight = distance/live['speed']
            if kind in ('gun', 'laser'):
                # Same interior body envelope as Combat; center pitch alone
                # rejects reachable upper bodies when our mech is larger.
                low = math.atan2(dz-target_h*.4, max(horizontal, 1e-9))
                high = math.atan2(dz+target_h*.4, max(horizontal, 1e-9))
                low, high = max(low, stats['min_pitch']), min(high, stats['max_pitch'])
                if low > high:
                    continue
                pitch = max(low, min(high, pitch))
            elif kind == 'lightning':
                pitch = me['aim'][1]  # The existing controller gates yaw only.
            if not stats['min_pitch'] <= pitch <= stats['max_pitch']:
                continue
            turn = max(abs(angle_delta(yaw, me['aim'][0]))/stats['turn_rate'],
                       abs(pitch-me['aim'][1])/stats['pitch_rate'])
            ready = max(0., weapon.get('cooldown', 0.))
            damage = live['damage']*scale
            event_start = len(events)
            if kind == 'gun':
                ammo = int(weapon.get('ammo', live['mag']))
                reload = max(0., weapon.get('reload', 0.))
                if reload > 0 or ammo <= 0:
                    ready = max(ready, reload if reload > 0 else live['reload'])
                    ammo = int(live['mag'])
                shot = max(ready, turn)
                for _ in range(128):
                    if shot+flight > horizon:
                        break
                    events.append((shot+flight, damage))
                    ammo -= 1
                    if ammo <= 0:
                        shot += live['reload']
                        ammo = int(live['mag'])
                    else:
                        shot += live['cooldown']
            elif kind == 'laser':
                charge = weapon.get('charge', 0.)
                shot = max(turn, (max(0., live['charge']-charge) if charge > 0 else ready+live['charge']))
                damage *= 1+live.get('cookoff', 0) if 'mortar' in target.get('weapons', ()) else 1
                for _ in range(32):
                    if shot > horizon:
                        break
                    events.append((shot, damage))
                    shot += live['cooldown']+live['charge']
            else:
                shot = max(ready, turn)
                count = int(max(0., me['energy']-18.)/live['energy']) if kind == 'lightning' else 32
                damage += live.get('splash', 0)*scale if kind == 'mortar' else 0
                for _ in range(min(128, count)):
                    if shot+flight > horizon:
                        break
                    events.append((shot+flight, damage))
                    shot += live['cooldown']
            if len(events) > event_start:
                first_opportunities.append(events[event_start][0])
        events.sort()
        hp = target.get('hp')
        known_hp = isinstance(hp, (int, float)) and math.isfinite(hp) and hp > 0
        total, finish = 0., None
        for when, damage in events:
            total += damage
            if known_hp and total >= hp:
                finish = when
                break
        return {'first_hit_s': events[0][0] if events else None, 'ideal_finish_s': finish,
                'pending_cycle_s': max(first_opportunities, default=None),
                'known_hp': known_hp, 'model': 'ideal own unarmored hits; not a kill guarantee'}

    def _stop(self, now, reason, ids, *, heal=False, commit=True):
        if self.encounter is not None and commit:
            self.encounter.setdefault('retreat_until', now+self.RETRY_S)
            self.encounter.setdefault('stop_reason', reason)
        self.health_recover = self.health_recover or heal
        self.report.update(phase='retreat', retreat=True, reason=reason, opponents=sorted(ids),
                           health_recover=self.health_recover)
        return self.report

    def decide(self, obs, threats, target, stats, *, urgent=False, acquire_weapon=None):
        now, me = obs['t'], obs['self']
        had_encounter = self.encounter is not None
        self._events(obs)
        fraction = me['hp']/max(me['max_hp'], 1)
        if fraction < self.LOW_HP:
            self.health_recover = True
        elif fraction >= self.HEALED_HP:
            self.health_recover = False
        current = {q['actor']['id']: q for q in threats if q['actor']['kind'] == 'mech'
                   and q['actor']['id'] not in self.dead and q['actor'].get('hp', 1) > 0}
        own_range = max((w.get('stats', {}).get('range', self._range([w['kind']]))
                         for w in me['weapons'] if w), default=0)
        exposed = {ident for ident, q in current.items()
                   if q['los'] and q['d'] <= self._range(q['actor'].get('weapons', ()))}
        # The selected reachable opponent is the duel, even when we outrange
        # it. Other bystanders do not inherit OUR longer weapon reach.
        if target and target.get('kind') == 'mech' and target['id'] in current:
            q = current[target['id']]
            if q['los'] and q['d'] <= own_range:
                exposed.add(target['id'])
        for ident in exposed:
            self.last_exposed[ident] = now
        self.attackers = {i:t for i,t in self.attackers.items()
                          if now-t < self.ATTACKER_MEMORY_S and i not in self.dead}
        self.last_exposed = {i:t for i,t in self.last_exposed.items()
                             if now-t < self.LOST_EXPOSED_MEMORY_S and i not in self.dead}
        # An observed occluded actor is not automatically an active fighter.
        # An absent actor briefly retains its last exposure; actual hits last longer.
        ids = exposed | set(self.attackers) | {i for i in self.last_exposed if i not in current}
        if self.encounter is not None:
            fight = self.encounter
            if fight['target'] in exposed:
                fight['last_contact'] = now
            elif fight['target'] in self.attackers:
                fight['last_contact'] = max(fight['last_contact'], self.attackers[fight['target']])
            if (fight['target'] in self.dead or
                    now-fight['last_contact'] >= self.ENCOUNTER_MEMORY_S):
                self.encounter = None
        self.report = {'retreat': False, 'phase': 'idle', 'reason': 'no_contact',
                       'opponents': sorted(ids), 'health_recover': self.health_recover,
                       'count_model': 'current outgoing LOS/range plus recent damage/exposure memory'}
        if self.health_recover:
            return self._stop(now, 'health_recovery', ids)
        if len(ids) > 1:
            return self._stop(now, 'multiple_opponents', ids)
        if not ids:
            # An LOS flicker must not refund cost, time or a used extension.
            if self.encounter is not None and 'retreat_until' in self.encounter:
                return self._stop(now, 'retreat_commitment', ids)
            return self.report
        if target is None or target.get('kind') != 'mech' or target['id'] not in exposed or ids != {target['id']}:
            return self._stop(now, 'unresolved_contact', ids, commit=False)
        schedule = self.ideal_schedule(obs, target, stats)
        self.report.update(schedule)
        if (self.encounter is not None and self.encounter['target'] == target['id']
                and 'retreat_until' in self.encounter):
            if now >= self.encounter['retreat_until'] and fraction >= self.HEALED_HP:
                # A real retreat interval plus healing can fund another probe;
                # a one-frame LOS break or merely elapsed retry time cannot.
                self.encounter = None
            else:
                return self._stop(now, 'retreat_commitment', ids)
        if schedule['first_hit_s'] is None:
            return self._stop(now, 'no_current_weapon_solution', ids)
        # Visibility alone need not abandon a vetted weapon approach. Existing
        # encounters (including one reset for retry above) keep their policy;
        # an observed hit starts the fight ledger even during acquisition.
        if (not had_encounter and self.encounter is None and fraction >= self.HEALED_HP
                and not urgent and acquire_weapon is not None
                and not any(e['type'] == 'hit' and e.get('target') == target['id']
                            and e.get('amount', 0.) > 0 for e in obs.get('events', ()))
                and acquire_weapon()):
            self.report.update(phase='acquire', reason='weapon_acquisition')
            return self.report
        if self.encounter is None or self.encounter['target'] != target['id']:
            self.encounter = {'target': target['id'], 'start': now, 'spent': 0.,
                'hits': deque(), 'grace': now+min(self.MAX_PROBE_S, max(self.PROBE_S, schedule['first_hit_s']+1.)),
                'finish_until': None, 'finish_used': False, 'reload_until': now, 'last_reload': 0.,
                'last_contact': now, 'entry_max_hp': me['max_hp'], 'pending_hit_until': None}
            for event in obs.get('events', ()):
                # Entry HP already includes this frame's incoming damage;
                # the cost ledger starts after this observation.
                if event['type'] == 'hit' and event.get('target') == target['id'] and event.get('amount', 0.) > 0:
                    self.encounter['hits'].append((now, max(0., event.get('amount', 0.))))
        fight = self.encounter
        reload = max((w.get('reload', 0.) for w in me['weapons'] if w and w['kind'] == 'gun'), default=0.)
        if reload > fight['last_reload']+.1:
            fight['reload_until'] = now+reload+min(1., schedule['first_hit_s'])
        fight['last_reload'] = reload
        while fight['hits'] and fight['hits'][0][0] < now-self.PROGRESS_S:
            fight['hits'].popleft()
        dealt = sum(amount for _, amount in fight['hits'])
        elapsed = now-fight['start']
        rate = dealt/max(1., min(self.PROGRESS_S, elapsed))
        remaining = target['hp']/rate if schedule['known_hp'] and rate > 0 else None
        self.report.update(spent=fight['spent'], recent_dealt=dealt, observed_remaining_s=remaining,
                           remaining_over_diagnostic=remaining is not None and remaining > self.REMAINING_S,
                           elapsed=elapsed, grace_until=fight['grace'], reload_until=fight['reload_until'])
        reason = None
        if elapsed >= self.MAX_DUEL_S:
            reason = 'duel_time_limit'
        elif fight['finish_until'] is not None:
            if now >= fight['finish_until']:
                reason = 'finish_extension_expired'
        elif fight['spent'] >= self.LOSS_FRACTION*fight['entry_max_hp']:
            reason = 'health_cost'
        elif now >= fight['grace']:
            if dealt <= 0:
                if fight['pending_hit_until'] is not None and now >= fight['pending_hit_until']:
                    reason = 'no_effective_progress'
                elif fight['pending_hit_until'] is None and now >= fight['reload_until']:
                    action_dt = self.config['match']['decide_every']/self.config['match']['tick_hz']
                    # A later first gun arrival is still pending even if a
                    # laser had an earlier opportunity. The allowance is fixed
                    # once per actual target hit, and never exceeds one second.
                    fight['pending_hit_until'] = now+min(self.MAX_PENDING_HIT_S, schedule['pending_cycle_s']+action_dt)
            elif not schedule['known_hp']:
                reason = 'unknown_remaining_hp'
        # One fixed final-shot attempt can override soft cost/progress limits,
        # never multi-attacker, health, unknown contact, or the hard duration cap.
        fast = schedule['ideal_finish_s']
        if (reason in ('health_cost', 'no_effective_progress') and not urgent and fraction > self.LOW_HP
                and dealt > 0 and not fight['finish_used'] and fast is not None and fast <= self.FINISH_S
                and elapsed+self.FINISH_S <= self.MAX_DUEL_S):
            fight['finish_used'] = True
            fight['finish_until'] = now+self.FINISH_S
            fight['finish_reason'] = reason
            reason = None
        self.report['pending_hit_until'] = fight['pending_hit_until']
        if reason:
            heal = reason == 'health_cost' or (reason == 'finish_extension_expired' and fight.get('finish_reason') == 'health_cost')
            return self._stop(now, reason, ids, heal=heal)
        self.report.update(phase='finish' if fight['finish_until'] is not None else
                           'probe' if now < fight['grace'] else 'duel', reason='bounded_duel',
                           finish_until=fight['finish_until'])
        return self.report

    def quiet_healing(self, obs, threats, stats, line_of_fire, deadline):
        """Narrow current-position protection samples; never a cover-route claim.

        Unseen recent attackers, mortar arcs, existing projectiles and budget
        exhaustion remain uncertain. All sampled direct rays must be blocked.
        """
        if obs['self']['hp'] >= self.HEALED_HP*obs['self']['max_hp'] or not obs['self']['in_zone']:
            return False
        actors = {q['actor']['id']: q['actor'] for q in threats}
        if any(i not in actors for i in self.attackers) or obs.get('projectiles'):
            return False
        count = 0
        me = obs['self']
        for actor in actors.values():
            kinds = actor.get('weapons', ['npc'] if actor['kind'] == 'npc' else ['gun'])
            if 'mortar' in kinds:
                return False
            scale = 1+self.config['cubes']['size_per_cube']*actor.get('cubes', 0)
            h = self.config['npc'].get('muzzle_height', self.config['npc']['height']) if actor['kind'] == 'npc' else self.config['mech']['muzzle_height']*scale
            origin = [actor['pos'][0], actor['pos'][1], actor['pos'][2]+h]
            dx, dy = me['pos'][0]-origin[0], me['pos'][1]-origin[1]
            length = max(1e-6, math.hypot(dx, dy))
            samples = [(0., .9), (0., .5), (-.8, .9), (.8, .9)]
            for side, height in samples:
                if count >= 8 or time.perf_counter() >= deadline:
                    return False
                point = [me['pos'][0]-side*stats['radius']*dy/length,
                         me['pos'][1]+side*stats['radius']*dx/length,
                         me['pos'][2]+height*stats['height']]
                count += 1
                if line_of_fire(origin, point):
                    return False
        return True
