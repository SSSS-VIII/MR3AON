#!/usr/bin/env python3
"""对比JSON数组中的策略参数；仅离线，训练种子与最终验证种子由调用方分开。"""
import argparse
import json
from pathlib import Path
from intelligence_simulator.single_player import aggregate,play,target_checks
from intelligence_simulator.tuned import resolve_policy

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--policies',type=Path,required=True)
p.add_argument('--games',type=int,default=100)
p.add_argument('--first-seed',type=int,default=0)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if not 1<=a.games<=10000:p.error('games必须为1..10000')
policies=json.loads(a.policies.read_text())
if not isinstance(policies,list) or not policies:p.error('policies必须是非空JSON数组')
rows=[]
for overrides in policies:
    policy=resolve_policy(overrides)
    games=[play(seed,'tuned',policy=policy,stop_at_100=False)
           for seed in range(a.first_seed,a.first_seed+a.games)]
    summary=aggregate(games)
    row={'policy':policy,'summary':summary,'acceptance_actual_stop':target_checks(summary),
         'acceptance_five_rounds':target_checks(summary,five_rounds=True)}
    rows.append(row)
    print(json.dumps(row,ensure_ascii=False),flush=True)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps({'first_seed':a.first_seed,'games':a.games,'rows':rows},ensure_ascii=False,indent=2)+'\n')
