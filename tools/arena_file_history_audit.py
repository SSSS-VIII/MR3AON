#!/usr/bin/env python3
"""Audit retained original-game VM roots without restarting or replaying undo."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
sys.path.insert(0,str(ROOT/'tools/arena_checkpoint_lab'))
from runtime import InstanceSession
from runtime.checkpoint_sandbox import ArenaCheckpointSandbox
from boot_client import start
from batch import WorkQueue,initialize
from collector import References,install_observer
import search


class AuditReferences(References):
    def begin(self,gate,point,start):
        super().begin(gate,point,start)
        self.start_probe=gate.call('probe')
        gate.restore(point)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--continue-queue',action='store_true')
    parser.add_argument('--case',default='L5-M42-S1-B50012')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    os.environ['MR3A_CHECKPOINT_FILE_RAM']='1'
    session=InstanceSession('arena-search')
    binary=ROOT/'debug/arena-client/rewind-research-v1/nyx-lite/target/release/arena_checkpoint_file_worker'
    with ArenaCheckpointSandbox(session).running(binary)as vm:
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            if vm.request('run',ms=500)['result'].get('agent_ready'):break
        else:raise TimeoutError('Private boot agent did not register')
        gate=start(vm)
        queue=WorkQueue(ROOT/'debug/arena-client/fixed-route-work/batch-all')
        case=queue.cases[args.case]
        item=queue.state['cases'][case['key']]
        attempt=dict(output=str(args.output),started_at=time.time(),status='initializing')
        item['attempts'].append(attempt);item['status']='initializing'
        queue.state['active']=case['key'];queue.save()
        try:
            def progress(value):attempt.update(value);queue.save();print(value.get('phase'),flush=True)
            attempt['entry']=initialize(gate,case,progress)
            attempt['observer_sha256']=install_observer(gate)
            references=AuditReferences(args.output/'references')
            attempt['status']=item['status']='searching';queue.save()
            report=search.run(gate,args.output/'search',collector=references,retain_history=True,max_windows=600)
            endpoint=gate.snapshot()['result']['id']
            end_probe=gate.call('probe')
            restored=gate.restore(report['initial_ram_root']['result']['id'])
            start_equal=gate.call('probe')==references.start_probe
            alternate=gate.step(3,'jump')
            future=gate.restore(endpoint)
            end_equal=gate.call('probe')==end_probe
            result=dict(schema=1,game_rollback_complete=False,complete_native_exit=report['complete'],
                health=gate.call('state')['health'],start_projection_equal=start_equal,end_projection_equal=end_equal,
                old_root_restore_ms=restored['ms'],retained_future_restore_ms=future['ms'],
                alternate_action=alternate,backtracks=len(report['backtracks']),
                scope='Full VM restore; the exported game projection is finite, not an entire-engine hash')
            (args.output/'audit.json').write_text(json.dumps(result,indent=2))
            print(json.dumps({k:v for k,v in result.items()if k!='alternate_action'}),flush=True)
            if not(start_equal and end_equal and result['health']==5000):raise RuntimeError('Retained game projection mismatch')
            passed=queue.accept(case,report,args.output/'search/report.json',references)
            attempt['status']='native_passed'if passed else'search_stalled'
        except BaseException as error:
            attempt.update(status='interrupted'if isinstance(error,KeyboardInterrupt)else'failed',error=repr(error))
            item['status']=attempt['status']
            raise
        finally:
            attempt['finished_at']=time.time();queue.state['active']=None;queue.save()
        if args.continue_queue:print(queue.run(gate,retain_history=True),flush=True)


if __name__=='__main__':main()
