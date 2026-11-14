#!/usr/bin/env python3
"""整理已有全池数据，可补算白板版各回合的金币参考。"""
import argparse
import json
from pathlib import Path
from intelligence_simulator.gold_value import load_historical,recompute

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--historical',type=Path,default=Path('.mr3a-records/benchmarks/2026-11-15-intelligence-pool.json'))
p.add_argument('--recompute',action='store_true')
p.add_argument('--seconds',type=float,default=60)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
historical=load_historical(a.historical)
for row in historical:print(json.dumps({'historical_full_profile':row['name'],'mean_spent':row['mean_actual_spent'],'gain_per_coin':row['gold_value']},ensure_ascii=False),flush=True)
result=recompute(a.seconds,lambda row:print(json.dumps(row,ensure_ascii=False),flush=True)) if a.recompute else {'rows':[],'complete_reference':False}
result['historical_full_profile']=historical
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
