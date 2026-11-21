"""Chronological forecasts; later observations are held-out position truth.

The four traces motivated this hypothesis, so this is causal forecast replay,
not an independent match validation or a claim about gun hit rate.
"""
import argparse
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from arena_map import ArenaMap
from target_motion import TargetMotion

TRACES=('baseline-39b-20261121-162954','correctness-ab878-20261121-163846',
        'aim-2dba505-20261121-165019','navigation-fc474fd-20261121-165508')
HORIZONS=(.1,.2,.4,.6,.8)


def summary(values):
    values=sorted(values)
    return {'n':len(values),'mean':statistics.mean(values),'median':statistics.median(values),
            'p90':values[min(len(values)-1,int(.9*len(values)))],
            'p99':values[min(len(values)-1,int(.99*len(values)))],'max':values[-1]}


def run(root,name):
    path=root/name
    hello=json.loads((path/'hello.json').read_text(encoding='utf-8'))
    config=hello['config']
    arena=ArenaMap(REPO/'arena',config)
    assert arena.available and len(arena.prisms)==259
    motion=TargetMotion(config,arena)
    with gzip.open(path/'trace.jsonl.gz','rt',encoding='utf-8') as file:
        observations=[row['data'] for row in map(json.loads,file) if row['data'].get('type')=='obs']
    truth={(obs['tick'],actor['id']):actor for obs in observations for actor in obs.get('mechs',())
           if actor['kind']=='mech'}
    errors=collections.defaultdict(list)
    times=collections.defaultdict(list)
    confirmed=0
    actors_seen=0
    dt=config['match']['decide_every']/config['match']['tick_hz']
    for obs in observations:
        before=time.perf_counter_ns()
        motion.update(obs)
        times['update_ms'].append((time.perf_counter_ns()-before)/1e6)
        for actor in obs.get('mechs',()):
            if actor['kind']!='mech':
                continue
            actors_seen+=1
            confirmed+=bool(motion._actors.get(actor['id'],{}).get('freefall',False))
            previous=truth.get((obs['tick']-config['match']['decide_every'],actor['id']))
            comparable=False
            if previous:
                acceleration=[(actor['vel'][i]-previous['vel'][i])/dt for i in range(3)]
                comparable=math.hypot(*acceleration[:2])<=65 and abs(acceleration[2])<=65
            for horizon in HORIZONS:
                future=truth.get((obs['tick']+round(horizon*config['match']['tick_hz']),actor['id']))
                if future is None:
                    continue
                cv=[actor['pos'][i]+actor['vel'][i]*horizon for i in range(3)]
                before=time.perf_counter_ns()
                predicted=motion.forecast(actor,horizon)
                times['forecast_ms'].append((time.perf_counter_ns()-before)/1e6)
                assert predicted[:2]==cv[:2], 'Horizontal model changed'
                supported=list(cv)
                supported[2]=max(cv[2],arena.support_height(cv[0],cv[1],actor['pos'][2]))
                for group in (('all','audit_comparable') if comparable else ('all',)):
                    for model,point in (('constant_velocity',cv),('supported_velocity',supported),('candidate',predicted)):
                        prefix=f'{group}/{horizon:.1f}/{model}'
                        errors[prefix+'/vertical'].append(abs(point[2]-future['pos'][2]))
                        errors[prefix+'/horizontal'].append(math.dist(point[:2],future['pos'][:2]))
    return {'actors_seen':actors_seen,'confirmed_freefall':confirmed,
            'errors':{key:summary(values) for key,values in errors.items()},
            'timing':{key:summary(values) for key,values in times.items()}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--traces',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result={'kind':'causal-forecast-replay-not-hit-rate',
            'sources':{name:hashlib.sha256((REPO/name).read_bytes()).hexdigest()
                       for name in ('target_motion.py','combat.py','bot.py')},
            'traces':{name:run(args.traces,name) for name in TRACES}}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    for name,trace in result['traces'].items():
        print(name)
        for group in ('all','audit_comparable'):
            print(group,{model:trace['errors'][f'{group}/0.4/{model}/vertical']
                         for model in ('constant_velocity','supported_velocity','candidate')})
        print('timing',trace['timing'])


if __name__=='__main__':
    main()
