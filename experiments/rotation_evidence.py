"""Inspect conditional replay decisions; never advances or connects to a match."""
import argparse
import copy
import gzip
import json
import math
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from bot import Bot


def summary(rows):
    times=sorted(row['compute_ms'] for row in rows)
    return {'frames':len(rows),
            'fallbacks':sum(row['telemetry']['tactical'].get('fallback',False) for row in rows),
            'neutral':sum(math.hypot(*row['action']['move'])<.1 for row in rows),
            'p50_ms':statistics.median(times),
            'p95_ms':times[math.ceil(.95*len(times))-1],
            'p99_ms':times[math.ceil(.99*len(times))-1],
            'max_ms':max(times),
            'over50':sum(value>50 for value in times)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    with gzip.open(args.trace,'rt',encoding='utf-8') as file:
        trace=[json.loads(line) for line in file]
    hello=next(row['data'] for row in trace if row['data'].get('type')=='hello')
    observations={row['data']['tick']:row['data'] for row in trace if row['data'].get('type')=='obs'}
    hello['map']['dir']=str(ROOT/'arena')
    bot=Bot(hello)
    assert bot.map.available,bot.map.error
    assert len(bot.map.prisms)==259
    baseline=json.loads(args.baseline.read_text(encoding='utf-8'))
    candidate=json.loads(args.candidate.read_text(encoding='utf-8'))
    previous={row['tick']:row for row in baseline}
    checked=[]
    for row in candidate:
        before=previous[row['tick']]
        if math.hypot(*before['action']['move'])>=.1 or math.hypot(*row['action']['move'])<.1:
            continue
        action=row['action']
        me=copy.deepcopy(observations[row['tick']]['self'])
        me['weapons']=[({**weapon,'charge':max(.001,weapon.get('charge',0)) if action['fire'][i] else 0}
                        if weapon and weapon['kind']=='laser' else weapon)
                       for i,weapon in enumerate(me['weapons'])]
        stats=bot.stats(me)
        charging=any(weapon and weapon['kind']=='laser' and weapon.get('charge',0)>0 for weapon in me['weapons'])
        direction=tuple(action['move'])
        rollout=bot.tactical.rollout(me,direction,action['boost'],stats)
        start=time.perf_counter()
        path=bot.tactical._geometry(rollout,stats,start+1,direction,action['boost'],charging)
        checked.append({'t':row['t'],'valid_full_0_6s':path is not None,
                        'geometry_ms':(time.perf_counter()-start)*1000})
    result={'kind':'conditional-decisions-not-counterfactual-match',
            'baseline':summary(baseline),'candidate':summary(candidate),
            'previous_neutral_now_moving':len(checked),
            'failed_geometry':sum(not item['valid_full_0_6s'] for item in checked),
            'geometry_checks':checked}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key!='geometry_checks'},indent=2))


if __name__=='__main__':
    main()
