#!/usr/bin/env python3
"""Resume independent fixed-board cases using the leased original search VM."""
import argparse
from pathlib import Path
import sys
import time
import os

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
sys.path.insert(0,str(ROOT/'tools/arena_checkpoint_lab'))
from runtime import InstanceSession
from runtime.checkpoint_sandbox import ArenaCheckpointSandbox
from batch import WorkQueue
from boot_client import start


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--file-ram',action='store_true')
    parser.add_argument('--case',action='append',default=[],help='Prioritize a canonical case before the remaining queue')
    args=parser.parse_args()
    if(args.queue/'stop-after-current.json').exists():
        print('This queue has a retained stop-after-current request; not starting another search epoch.',flush=True)
        return
    session=InstanceSession('arena-search')
    binary=ROOT/'debug/arena-client/rewind-research-v1/nyx-lite/target/release/arena_checkpoint_worker'
    if args.file_ram:
        binary=binary.with_name('arena_checkpoint_file_worker')
        os.environ['MR3A_CHECKPOINT_FILE_RAM']='1'
    with ArenaCheckpointSandbox(session).running(binary)as vm:
        # Acquiring the name must precede any coverage write too.
        queue=WorkQueue(args.queue)
        unknown=set(args.case)-queue.cases.keys()
        if unknown:raise ValueError('Unknown canonical cases: '+', '.join(sorted(unknown)))
        if not queue.pending(require_margin=args.file_ram):
            print('All native cases already have exit evidence and references.',flush=True)
            return
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            if vm.request('run',ms=500)['result'].get('agent_ready'):break
        else:raise TimeoutError('The private Android boot agent did not become ready')
        # This initializes a new case after process loss. Search undo always
        # uses real gate checkpoints, never bootstrap or input-history replay.
        gate=start(vm)
        work=[queue.cases[key]for key in dict.fromkeys(args.case)]
        work.extend(case for case in queue.pending(require_margin=args.file_ram)if case['key']not in args.case)
        print(queue.run(gate,cases=work,retain_history=args.file_ram),flush=True)


if __name__=='__main__':
    main()
