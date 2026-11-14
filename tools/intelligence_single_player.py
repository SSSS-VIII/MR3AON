#!/usr/bin/env python3
"""固定种子单边五回合回归，不运行任何游戏实例。"""
import argparse
import json
from pathlib import Path
from intelligence_simulator.refresh import build_reference_table
from intelligence_simulator.single_player import run_regression

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--games',type=int,default=50)
p.add_argument('--first-seed',type=int,default=0)
p.add_argument('--reference',type=Path)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
reference=json.loads(a.reference.read_text()) if a.reference else build_reference_table()
result=run_regression(a.games,a.first_seed,reference)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({name:data['summary'] for name,data in result['strategies'].items()},ensure_ascii=False))
