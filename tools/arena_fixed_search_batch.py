#!/usr/bin/env python3
"""Resume independent fixed-board cases using the leased original search VM."""
import argparse
from pathlib import Path
import sys
import time

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
    args=parser.parse_args()
    session=InstanceSession('arena-search')
    binary=ROOT/'debug/arena-client/rewind-research-v1/nyx-lite/target/release/arena_checkpoint_worker'
    with ArenaCheckpointSandbox(session).running(binary)as vm:
        # Acquiring the name must precede any coverage write too.
        queue=WorkQueue(args.queue)
        if not queue.pending():
            print('All native cases already have exit evidence and references.',flush=True)
            return
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            if vm.request('run',ms=500)['result'].get('agent_ready'):break
        else:raise TimeoutError('The private Android boot agent did not become ready')
        # This initializes a new case after process loss. Search undo always
        # uses real gate checkpoints, never bootstrap or input-history replay.
        gate=start(vm)
        print(queue.run(gate),flush=True)


if __name__=='__main__':
    main()
