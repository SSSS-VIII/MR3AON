#!/usr/bin/env python3
"""Run the internal-model fixed-board queue in its leased checkpoint guest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
sys.path.insert(0,str(ROOT/'tools/arena_checkpoint_lab'))

from arena_privileged_catalog import build
from arena_privileged_runner import json_safe
from runtime import InstanceSession
from runtime.checkpoint_sandbox import ArenaCheckpointSandbox
from boot_client import start
from batch import initialize
from render import prepare
from privileged_search import run
from arena_privileged_revisions import freeze,activate,digest_sources,MODEL_MODULES


SOURCES=('arena_privileged_batch.py','arena_privileged_catalog.py','arena_privileged_families.py',
    'arena_privileged_revisions.py',
    'arena_privileged_geometry.py','arena_privileged_pinball.py',
    'arena_privileged_model.py','arena_privileged_policy.py','arena_privileged_runner.py',
    'arena_privileged_state.lua','arena_checkpoint_lab/privileged_search.py',
    'arena_checkpoint_lab/gate.py','arena_checkpoint_lab/clock_step.lua',
    'arena_checkpoint_lab/boot_client.py','arena_checkpoint_lab/batch.py','arena_checkpoint_lab/render.py',
    'arena_checkpoint_lab/client.py',
    'arena_checkpoint_lab/timing_margin.py','arena_checkpoint_lab/endpoint_rollout.py')


class EntryTimeoutRestored(RuntimeError):
    """One original entry timed out; its complete pre-entry VM was restored."""


def initialize_case(gate,case,progress,seed):
    before=gate.call('state');point=gate.snapshot()['result']['id']
    try:
        return initialize(gate,case,progress,seed=seed)
    except TimeoutError as error:
        if getattr(gate.vm,'uncertain_operation',None):
            raise
        gate.restore(point)
        if gate.call('state')!=before:
            raise RuntimeError('Timed-out entry restore differs from its complete native baseline') from error
        raise EntryTimeoutRestored(str(error)) from error
    finally:
        if not getattr(gate.vm,'uncertain_operation',None) and point in gate.points:
            gate.drop(point)


def install(gate, source_root=ROOT/'tools'):
    # The mailbox is bounded by encoded UTF-8 bytes, not Lua source length.
    # A small bounded chunk count avoids an expensive command per short line.
    for name in ('arena_privileged_state.lua','arena_checkpoint_lab/clock_step.lua'):
        source=(source_root/name).read_text()
        gate.call('exec',code='MR3A.privilegedChunks={};return true')
        for offset in range(0,len(source),1900):
            code='table.insert(MR3A.privilegedChunks,'+json.dumps(source[offset:offset+1900])+');return true'
            if len(json.dumps(dict(op='exec',code=code)).encode())>=4096:
                raise ValueError('Encoded model installation exceeds gate mailbox')
            gate.call('exec',code=code)
        gate.call('exec',code="assert(load(table.concat(MR3A.privilegedChunks),'@privileged-reader'))();MR3A.privilegedChunks=nil;return true")


def atomic(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(json_safe(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    temporary.replace(path)


def pending_cases(cases,ledger,revision,requested=()):
    """Cover untouched contexts before revisiting a failed source revision."""
    def priority(c):
        missing=len(c['unimplemented_enemy_classes'])+len(c['unbound_enemy_ids'])
        return (bool(ledger[c['key']]['attempts']),missing>0,c['kind']!='ordinary',
                c['level'] not in (5,6),c['slot']!=1,missing,c['key'])
    explicit=list(dict.fromkeys(requested))
    work=[cases[key] for key in explicit]
    work.extend(sorted((c for key,c in cases.items() if key not in explicit),key=priority))
    # Native nominal exits retain their frozen evidence for later certification;
    # model updates must not regenerate them or starve the rest of the catalog.
    return [c for c in work if not ledger[c['key']]['nominal_complete']
            and not any(a.get('revision')==revision and a.get('finished_at')
                        for a in ledger[c['key']]['attempts'])]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--case',action='append',default=[])
    parser.add_argument('--max-cases',type=int)
    parser.add_argument('--wall-seconds',type=float,default=1800)
    parser.add_argument('--defer-certification',action='store_true',
                        help='First-pass coverage only; retain nominal candidates for separate native endpoint validation')
    args=parser.parse_args()
    if args.max_cases is not None and args.max_cases<1 or not 30<=args.wall_seconds<=7200:
        parser.error('Use a positive case count and bounded case duration')
    args.queue.mkdir(parents=True,exist_ok=True)
    revision,source_dir,source_hashes=freeze(ROOT/'tools',args.queue/'sources',SOURCES)
    expert,build_manifest=activate(source_dir)
    manifest=build_manifest();atomic(args.queue/'inventory.json',manifest)
    reloadable={('arena_checkpoint_lab/' if name=='privileged_search' else '')+name+'.py'
                for name in MODEL_MODULES}|{'arena_privileged_state.lua'}
    core_hashes={name:value for name,value in source_hashes.items() if name not in reloadable}
    native_modules=('environment','native_mount','native_selection','native_boss','native_menu')
    native_hashes={name:hashlib.sha256((ROOT/'arena/Local'/f'{name}.lua').read_bytes()).hexdigest()
                   for name in native_modules}
    atomic(args.queue/'native-environment-hashes.json',native_hashes)
    path=args.queue/'coverage.json'
    state=json.loads(path.read_text()) if path.exists() else dict(schema=1,cases={},active=None)
    state.pop('stopped_reason',None)
    for key,case in manifest['cases'].items():
        state['cases'].setdefault(key,dict(status='pending',attempts=[],nominal_complete=False,timing_robust=False))
    state.update(source_hashes=source_hashes,revision=revision,denominator=manifest['counts'])

    def save():
        state['updated_at']=time.time()
        state['counts']={name:sum(bool(c.get(name)) for c in state['cases'].values())
                         for name in ('nominal_complete','timing_robust')}
        state['counts']['attempted']=sum(bool(c['attempts']) for c in state['cases'].values())
        atomic(path,state)

    unknown=set(args.case)-manifest['cases'].keys()
    if unknown:
        parser.error('Unknown canonical contexts: '+', '.join(sorted(unknown)))
    def pending():
        return pending_cases(manifest['cases'],state['cases'],revision,args.case)
    work=pending()
    save()
    if not work:
        print('This source revision has no unattempted contexts.',flush=True);return
    os.environ['MR3A_CHECKPOINT_FILE_RAM']='1'
    binary=ROOT/'debug/arena-client/rewind-research-v1/nyx-lite/target/release/arena_checkpoint_file_worker'
    session=InstanceSession('arena-search')
    with ArenaCheckpointSandbox(session).running(binary) as vm:
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if vm.request('run',ms=500)['result'].get('agent_ready'):
                break
        else:
            raise TimeoutError('Private checkpoint guest did not become ready')
        try:
            # Bootstrap on the known original first-level opening. Requested
            # cases still initialize independently through native selection.
            gate=start(vm,seed=42,chapter=1,level=1)
        except BaseException as error:
            boot_error=dict(error=repr(error),phase='cold_initialization',search_started=False)
            if not getattr(vm,'arena_game_gate',False):
                try:
                    from client import CheckpointClient
                    boot_error['native']=CheckpointClient(vm).execute('return {state=MR3A.state(),reset=MR3A.resetJob}')
                except Exception as diagnostic_error:
                    boot_error['state_error']=repr(diagnostic_error)
                try:
                    boot_error['logcat']=vm.command('logcat -d -t 500 2>&1',timeout=30)
                except Exception as diagnostic_error:
                    boot_error['diagnostic_error']=repr(diagnostic_error)
            atomic(args.queue/'boot-error.json',boot_error)
            raise
        try:
            number=0
            while args.max_cases is None or number<args.max_cases:
                if (args.queue/'stop.json').exists():
                    break
                current=digest_sources(ROOT/'tools',SOURCES)
                if any(current[n]!=h for n,h in core_hashes.items()):
                    state['stopped_reason']='worker_core_changed';break
                if any(hashlib.sha256((ROOT/'arena/Local'/f'{n}.lua').read_bytes()).hexdigest()!=h
                       for n,h in native_hashes.items()):
                    state['stopped_reason']='native_environment_changed';break
                if current!=source_hashes:
                    # The preceding run has returned to its own initial VM
                    # point and released every branch. Only now switch the
                    # immutable Python model/reader as one independent epoch.
                    revision,source_dir,source_hashes=freeze(ROOT/'tools',args.queue/'sources',SOURCES)
                    expert,build_manifest=activate(source_dir);manifest=build_manifest()
                    state.update(revision=revision,source_hashes=source_hashes)
                    atomic(args.queue/'inventory.json',manifest);save()
                    print(json.dumps(dict(phase='model_revision_activated',revision=revision)),flush=True)
                work=pending()
                if not work:
                    state['stopped_reason']='revision_pass_finished';break
                case=work[0]
                key=case['key'];item=state['cases'][key]
                folder=args.queue/'runs'/key/str(time.time_ns())
                attempt=dict(revision=revision,started_at=time.time(),output=str(folder),status='initializing')
                item['attempts'].append(attempt);item['status']='initializing';state['active']=key;save()
                print(json.dumps(dict(case=key,number=number+1,total=len(work),phase='initializing')),flush=True)
                def progress(value):
                    attempt['progress']=value;save()
                    print(json.dumps(json_safe(dict(case=key,**value)),ensure_ascii=False),flush=True)
                try:
                    entry=initialize_case(gate,case,progress,seed=75200)
                    attempt['entry']=entry;prepare(gate);install(gate,source_dir)
                    item['status']='searching';attempt['status']='searching';save()
                    result=expert(gate,folder,wall_seconds=args.wall_seconds,progress=progress,
                               certify=not args.defer_certification)
                    attempt.update(status=result['status'],nominal_complete=result['nominal_complete'],
                        timing_robust=result['timing_robust'],wall_seconds=result['wall_seconds'],
                        game_seconds=result['game_seconds'],backtracks=result['backtracks'])
                    item.update(status=result['status'],nominal_complete=result['nominal_complete'],
                        timing_robust=result['timing_robust'])
                    if result.get('missing'):
                        item['missing']=result['missing']['evidence']
                except KeyboardInterrupt:
                    attempt['status']=item['status']='interrupted';raise
                except Exception as error:
                    status='entry_timeout_restored' if isinstance(error,EntryTimeoutRestored) else 'error'
                    attempt.update(status=status,error=repr(error));item['status']=status
                    if isinstance(error,TimeoutError) or gate.waiting or getattr(vm,'uncertain_operation',None):
                        raise
                finally:
                    attempt['finished_at']=time.time();save()
                # A new baseline between independent cases bounds history.
                # It is never used as undo inside a case.
                number+=1
                if len(work)>1 and (args.max_cases is None or number<args.max_cases):
                    gate.rebase()
        finally:
            state['active']=None;save()


if __name__=='__main__':
    main()
