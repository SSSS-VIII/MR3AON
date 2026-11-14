#!/usr/bin/env python3
"""离线全剩余牌库组合收益/耗时测量；无设备、识别或点击调用。"""
import argparse
import json
from pathlib import Path
from intelligence_simulator.model import count_space, prepare_state, simulate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario',type=Path,help='JSON局面或局面数组')
    parser.add_argument('--name',action='append',help='只运行指定名称，可重复')
    parser.add_argument('--seconds',type=float,default=2,help='每个局面原生计算时限；0不限时')
    parser.add_argument('--max-layouts',type=int,default=0)
    parser.add_argument('--samples',type=int,default=0,help='0全量；正数为对整个合法组合空间的随机采样数')
    parser.add_argument('--physical-sampling',action='store_true')
    parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--profile',choices=['full','refresh_v1'],default='full')
    parser.add_argument('--growth-mode',choices=['since_entry','board_count'],default='since_entry')
    parser.add_argument('--count-only',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    raw=json.loads(args.scenario.read_text());states=raw if isinstance(raw,list) else [raw]
    if args.name:
        available={state.get('name','custom') for state in states}
        if set(args.name)-available:parser.error('未知局面名称')
        states=[state for state in states if state.get('name','custom') in args.name]
    results=[]
    for state in states:
        if args.count_only:result={'name':state.get('name','custom'),'space':count_space(prepare_state(state))}
        else:result=simulate(state,seconds=args.seconds,max_layouts=args.max_layouts,samples=args.samples,
                             seed=args.seed,physical_sampling=args.physical_sampling,growth_mode=args.growth_mode,profile=args.profile)
        results.append(result)
        summary=result.get('statistics',result.get('sample_estimate',{}))
        stats=summary.get('unique_combinations',summary.get('sampled_distribution'))
        print(json.dumps({k:result[k] for k in ('name','mode','complete','all_combinations_evaluated','combinations','layouts','elapsed_s') if k in result} |
                         {'space':result['space'],'stats':stats},ensure_ascii=False),flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
