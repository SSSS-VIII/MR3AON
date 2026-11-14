#!/usr/bin/env python3
"""离线生成金币参考或分析一手牌；不接设备/生产队列。"""
import argparse
import json
from pathlib import Path
from intelligence_simulator.refresh import analyze_hand,build_reference_table,coin_reference

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--build-reference',action='store_true')
p.add_argument('--scenario',type=Path)
p.add_argument('--coin-value',type=float)
p.add_argument('--refreshes',type=int,default=1)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
if a.build_reference:result=build_reference_table()
else:
 if not a.scenario:p.error('需要--scenario或--build-reference')
 raw=json.loads(a.scenario.read_text())
 reference=coin_reference(raw)
 value=reference['median'] if a.coin_value is None else a.coin_value
 result={'reference':reference,'analysis':analyze_hand(raw,raw['hand'],value,a.refreshes)}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result if a.build_reference else {k:v for k,v in result['analysis'].items() if k not in {'choices','frontier'}},ensure_ascii=False))
