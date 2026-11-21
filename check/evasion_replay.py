"""Offline full-prefix replay; future beams are evaluation labels only.

The bot receives each recorded observation normally, with its own persistent
state. Its actions cannot change the trace, so this is not a match comparison.
After every action has been chosen, evaluate selected warning actions against
the later recorded ray, assuming that action and the enemy aim were held.
"""
import argparse
import copy
import gzip
import hashlib
import importlib
import json
import math
from pathlib import Path
import statistics
import sys
import time


def ray_miss(position,stats,beam,reach):
    source,end=beam['path'][0],beam['path'][1]
    length=math.dist(source,end)
    vector=[(end[i]-source[i])/length for i in range(3)]
    low,high=0.,reach
    if abs(vector[2])<1.e-9:
        if not position[2]<=source[2]<=position[2]+stats['height']:return None
    else:
        vertical=[(position[2]-source[2])/vector[2],(position[2]+stats['height']-source[2])/vector[2]]
        low=max(low,min(vertical));high=min(high,max(vertical))
        if low>high:return None
    along=((position[0]-source[0])*vector[0]+(position[1]-source[1])*vector[1])/max(1.e-9,vector[0]**2+vector[1]**2)
    along=max(low,min(high,along))
    return math.hypot(source[0]+along*vector[0]-position[0],source[1]+along*vector[1]-position[1])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--trace',type=Path,required=True)
    p.add_argument('--map-dir',type=Path,required=True)
    p.add_argument('--runs',type=int,default=1)
    args=p.parse_args();sys.path.insert(0,str(args.repo.resolve()))
    Bot=importlib.import_module('bot').Bot
    with gzip.open(args.trace,'rt',encoding='utf-8') as f:rows=[json.loads(s)['data'] for s in f]
    hello=next(x for x in rows if x.get('type')=='hello');hello['map']['dir']=str(args.map_dir.resolve())
    observations=[x for x in rows if x.get('type')=='obs']
    focus={548,556,1062,1112,1116}
    for run in range(args.runs):
        bot=Bot(hello);assert bot.map.available and len(bot.map.prisms)==259
        captured={};actions={};timing=[];errors=[];gates=[]
        original=bot.tactical.choose
        def capture(obs,navigation,threats,stats,**kwargs):
            result=original(obs,navigation,threats,stats,**kwargs)
            gate=bot.tactical.last_report.get('emergency_boost',False)
            if gate or obs['tick'] in focus:
                captured[obs['tick']]=dict(obs=copy.deepcopy(obs),navigation=navigation,
                    threats=copy.deepcopy(threats),stats=stats.copy(),report=dict(bot.tactical.last_report))
            if gate:gates.append(dict(tick=obs['tick'],t=obs['t'],boost=result[1]))
            return result
        bot.tactical.choose=capture
        for obs in observations:
            started=time.perf_counter()
            try:action=bot.act(obs)
            except Exception as exc:errors.append(dict(tick=obs['tick'],error=repr(exc)));continue
            elapsed=(time.perf_counter()-started)*1000
            timing.append(elapsed);actions[obs['tick']]=action
        # No future beam is examined before all bot decisions are completed.
        evaluations=[]
        for tick,state in captured.items():
            obs=state['obs'];stats=state['stats'];action=actions[tick]
            direction=tuple(action['move']);boost=action['boost'];me=obs['self']
            path=bot.tactical.rollout(me,direction,boost,stats)
            charging=any(w and w['kind']=='laser' and w.get('charge',0)>0 for w in me['weapons'])
            corrected=bot.tactical._geometry(path,stats,time.perf_counter()+1,direction,boost,charging)
            pressure=sorted(state['threats'],key=lambda q:bot.tactical._strength(q['actor'],q['d']),reverse=True)[:3]
            nav_path=bot.tactical.rollout(me,state['navigation'],False,stats)
            labels=[]
            for later in observations:
                if not obs['t']<later['t']<=obs['t']+.7:continue
                for damage in later.get('events',[]):
                    if damage['type']!='damaged' or damage.get('weapon')!='laser':continue
                    beam=next((b for b in later.get('beams',[]) if b['kind']=='laser' and b['by']==damage.get('by')),None)
                    if beam is None:continue
                    delay=later['t']-beam['age']+bot.tactical.dt-obs['t']
                    if not 0<delay<=bot.tactical.horizon:continue
                    prefix=path[:int(math.ceil((delay-1.e-8)/bot.tactical.dt))+1]
                    until=bot.tactical._geometry(prefix,stats,time.perf_counter()+1,direction,boost,charging)
                    miss=ray_miss(bot.tactical._at(until,delay),stats,beam,hello['config']['weapons']['laser']['range']) if until else None
                    labels.append(dict(hit_t=later['t'],delay=delay,attacker=damage.get('by'),
                        geometry_valid_to_release=until is not None,miss=miss,
                        clear=until is not None and (miss is None or miss>stats['radius']+.1)))
            evaluations.append(dict(tick=tick,t=obs['t'],energy=me['energy'],radius=stats['radius'],
                navigation=state['navigation'],action=action,report=state['report'],
                nav_warning_cost=bot.tactical._beam_cost(nav_path,pressure,stats),
                selected_warning_cost=bot.tactical._beam_cost(path,pressure,stats),
                geometry_valid=corrected is not None,remaining_energy=corrected[-1][7] if corrected else None,
                hindsight_labels=labels))
        ordered=sorted(timing)
        print(json.dumps(dict(run=run+1,observations=len(timing),errors=errors,
            over50=sum(t>50 for t in timing),wall_ms=dict(p50=statistics.median(ordered),p99=ordered[int(.99*len(ordered))],max=max(ordered)),
            gates=gates,evaluations=evaluations)),flush=True)
    print(json.dumps(dict(type='complete',source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.repo.glob('*.py')})),flush=True)


if __name__=='__main__':main()
