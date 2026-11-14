#!/usr/bin/env python3
"""离线生成金币参考或分析一手牌；不接设备/生产队列。"""
import argparse
import json
from pathlib import Path
from intelligence_simulator.refresh import analyze_hand,build_reference_table
from intelligence_simulator.tuned import analyze_tuned

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--build-reference',action='store_true')
p.add_argument('--scenario',type=Path)
p.add_argument('--coin-value',type=float)
p.add_argument('--strategy',choices=['tuned','legacy'])
p.add_argument('--policy',type=Path)
p.add_argument('--cumulative-damage',type=int)
p.add_argument('--synergy',action='store_true',help='按场面与回合估计未触发被动潜力')
p.add_argument('--refreshes',type=int,default=1)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if a.build_reference:result=build_reference_table()
else:
 if not a.scenario:p.error('需要--scenario或--build-reference')
 raw=json.loads(a.scenario.read_text())
 strategy=a.strategy or ('legacy' if a.synergy or a.coin_value is not None else 'tuned')
 if strategy=='tuned':
  if a.coin_value is not None or a.synergy:p.error('tuned的分阶段权重通过--policy设置；--coin-value/--synergy用于legacy')
  result={'analysis':analyze_tuned(raw,raw['hand'],a.refreshes,
       policy=json.loads(a.policy.read_text()) if a.policy else None,
       cumulative_damage=a.cumulative_damage if a.cumulative_damage is not None else raw.get('cumulative_damage',0))}
 else:
  if a.policy:p.error('--policy用于tuned策略')
  result={'analysis':analyze_hand(raw,raw['hand'],7 if a.coin_value is None else a.coin_value,a.refreshes,synergy=a.synergy)}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result if a.build_reference else {k:v for k,v in result['analysis'].items() if k not in {'choices','frontier'}},ensure_ascii=False))
