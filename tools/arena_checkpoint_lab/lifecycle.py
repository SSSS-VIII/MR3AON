"""Bounded native lifecycle evidence; every undo restores the complete guest."""
import hashlib
import json
from pathlib import Path
import shutil
import time

TOPOLOGY = """
local U=CS.UnityEngine
local f=CS.System.Reflection.BindingFlags.__CastFrom(52)
local l=CS.LevelManager.Instance.GameLevelInfo
local n=CS.NinjaController.Instance.NinjaScript
local g=n._GroundCollider
local stages=l:GetType():GetField('_stageList',f):GetValue(l)
local index=g and g.BelongToStageIndex or -1
local stage=index>=0 and index<stages.Count and stages[index] or nil
local enemies=U.Object.FindObjectsOfType(typeof(CS.EnemyBase))
local objects={}
for i=0,enemies.Length-1 do
 local e=enemies[i]
 if e.gameObject.activeInHierarchy and e.isActive then
  objects[#objects+1]={id=e:GetInstanceID(),type=e:GetType().Name,name=e.name}
 end
end
table.sort(objects,function(a,b)return a.id<b.id end)
return {stage_index=index,block_index=g and g.BelongToBlockIndex or -1,
 stage_id=stage and stage:GetType():GetField('_stageBaseInfo',f):GetValue(stage)._stageID or -1,
 objects=objects}
"""


def observe(gate):
    return dict(native=gate.call('probe'), topology=gate.call('exec', code=TOPOLOGY))


def run_boundary(gate, output, *, ticks=30, max_steps=30):
    """Start shortly before an ordinary board exit, cross, undo and compare.

    No checkpoints are discarded/rebased in this operation: both branches
    remain descendants of the same real VM point until verification finishes.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = dict(pass_=False, game_rollback_complete=False, uses_restart_replay=False,
                  scope='Finite native board transition and active enemy instance lifecycle',
                  checks={}, first=[], repeat=[])
    try:
        before = observe(gate)
        first_stage = before['topology']['stage_index']
        if first_stage < 0:
            raise ValueError('Begin this check on an original grounded board')
        root = gate.snapshot()
        report.update(root=root, before=before)
        for index in range(max_steps):
            job = gate.step(ticks)
            observation = observe(gate)
            report['first'].append(dict(job=job, observation=observation))
            print(f'跨板检查 {index + 1}: 帧{job["after"]["episodeFrame"]}, '
                  f'板序{observation["topology"]["stage_index"]}', flush=True)
            if job.get('terminated'):
                raise RuntimeError('Native death occurred before a board transition')
            stage = observation['topology']['stage_index']
            if stage >= 0 and stage != first_stage:
                break
        else:
            raise RuntimeError('No native board transition within the bounded audit')
        final = report['first'][-1]['observation']
        report['restore'] = gate.restore(root['result']['id'])
        report['checks']['before_restored'] = observe(gate) == before
        for index, row in enumerate(report['first']):
            job = gate.step(ticks)
            observation = observe(gate)
            report['repeat'].append(dict(job=job, observation=observation))
            print(f'跨板重复 {index + 1}/{len(report["first"])}', flush=True)
        report['checks']['each_interval_equal'] = report['repeat'] == report['first']
        report['checks']['entered_next_board'] = final['topology']['stage_index'] != first_stage
        initial_ids = {row['id'] for row in before['topology']['objects']}
        active_sets = [{item['id'] for item in row['observation']['topology']['objects']}
                       for row in report['first']]
        # Objects can be created and retired before the final interval. The
        # recorded timeline, rather than just its last (possibly empty) set,
        # establishes which lifecycle events the check actually exercised.
        report['checks']['native_objects_created'] = any(ids - initial_ids for ids in active_sets)
        report['checks']['native_objects_retired'] = any(initial_ids - ids for ids in active_sets)
        image_point = gate.snapshot()
        image = gate.screenshot()
        (output / 'crossed.png').write_bytes(image)
        gate.step(3, 'jump')
        gate.restore(image_point['result']['id'])
        restored_image = gate.screenshot()
        (output / 'crossed-restored.png').write_bytes(restored_image)
        report['checks']['crossed_png_equal'] = restored_image == image
        report['image_sha256'] = hashlib.sha256(image).hexdigest()
        report['pass_'] = all(report['checks'].values())
        return report
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        report['saved_at'] = time.time()
        for name in ('lifecycle.py', 'gate.py', 'game_gate.lua', 'worker.rs'):
            shutil.copy2(Path(__file__).parent / name, output / name)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


def run_native_death(gate, output):
    """Exercise the original Die entrypoint, not a fabricated HP=0 state.

    This checks the synchronous die state and its pending native callbacks;
    it does not claim a natural lethal collision or the completed results UI.
    Die changes timeScale to .5. Park it at zero just as the step adapter does,
    so the gate remains available without altering the original Die method.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = dict(pass_=False, game_rollback_complete=False, uses_restart_replay=False,
                  scope='Original Die entrypoint and pending callbacks; not completed death/results lifecycle',
                  checks={})
    command = ("local U=CS.UnityEngine;local n=CS.NinjaController.Instance.NinjaScript;"
               "local ok,err=pcall(function()n:Die(nil,false)end);local scale=U.Time.timeScale;"
               "U.Time.timeScale=0;assert(ok,tostring(err));"
               "return {nativeTimeScale=scale,physics=MR3A.state().physics,hp=n.CurrentHp}")
    try:
        before = observe(gate)
        root = gate.snapshot()
        report.update(before=before, root=root)
        result = gate.call('exec', code=command)
        after = observe(gate)
        image = gate.screenshot()
        (output / 'die.png').write_bytes(image)
        report['first'] = dict(result=result, observation=after)
        report['restore'] = gate.restore(root['result']['id'])
        report['checks']['living_state_restored'] = observe(gate) == before
        repeated = gate.call('exec', code=command)
        again = observe(gate)
        repeated_image = gate.screenshot()
        (output / 'die-repeated.png').write_bytes(repeated_image)
        report['repeat'] = dict(result=repeated, observation=again)
        report['checks']['original_die_reached'] = result['physics'] == 'die: 31'
        report['checks']['die_fields_repeated'] = result == repeated and again == after
        report['checks']['die_png_repeated'] = repeated_image == image
        gate.restore(root['result']['id'])
        living = gate.step(3, 'jump')
        report['living_alternative'] = living
        report['checks']['living_input_after_restore'] = (
            living['after']['health'] == before['native']['state']['health']
            and living['after']['physics'] != 'die: 31')
        gate.restore(root['result']['id'])
        report['pass_'] = all(report['checks'].values())
        return report
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        for name in ('lifecycle.py', 'gate.py', 'game_gate.lua', 'worker.rs'):
            shutil.copy2(Path(__file__).parent / name, output / name)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


def run_death_frames(gate, output, *, lethal=False):
    """Continue original Die for 300 render frames, then compare both branches.

    Use rendered frames because native physics counters can stop during death.
    Retain original death time scaling until the final parked boundary. The
    actual state trace establishes how much of the lifecycle was exercised.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = dict(pass_=False, game_rollback_complete=False, uses_restart_replay=False,
                  scope='Original DamageSelf to zero HP followed by 300 render frames; controlled native damage'
                        if lethal else 'Original Die followed by 300 render frames; natural lethal collision not exercised',
                  lethal=lethal,
                  checks={}, branches=[])
    command = """
local E,U=MR3A,CS.UnityEngine
local C=E.checkpointGate
local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
C.deathFrames={trace={},done=false}
E.busy=true
runner:StartCoroutine(require('common/util').cs_generator(function()
 local ok,err=pcall(function()
  local first=U.Time.frameCount
  -- CHECKPOINT_NATIVE_DEATH_TRIGGER
  local previous=nil
  while U.Time.frameCount-first<300 do
   local valid,s=pcall(E.state)
   local key=valid and (s.state..'|'..s.content..'|'..tostring(s.physics)) or tostring(s)
   if key~=previous then
    C.deathFrames.trace[#C.deathFrames.trace+1]={state=valid and s or nil,error=not valid and tostring(s)or nil}
    previous=key
   end
   coroutine.step()
  end
  C.deathFrames.frames=U.Time.frameCount-first
 end)
 U.Time.timeScale=0
 C.deathFrames.done=true
 if not ok then C.deathFrames.error=tostring(err)end
 E.busy=false
end))
return true
"""
    trigger = ('local n=CS.NinjaController.Instance.NinjaScript;n:DamageSelf(n.MaxHp*2)' if lethal else
               'CS.NinjaController.Instance.NinjaScript:Die(nil,false)')
    command = command.replace('-- CHECKPOINT_NATIVE_DEATH_TRIGGER', trigger)
    try:
        before = observe(gate)
        root = gate.snapshot()
        report.update(before=before, root=root)
        for index in range(2):
            report.setdefault('restores', []).append(gate.restore(root['result']['id']))
            gate.call('exec', code=command)
            trace = gate.call('exec', code='return MR3A.checkpointGate.deathFrames')
            picture = gate.screenshot()
            (output / f'death-{index}.png').write_bytes(picture)
            report['branches'].append(dict(trace=trace, stopped=gate.view['state'],
                                           image_sha256=hashlib.sha256(picture).hexdigest()))
            transitions = [(row.get('state') or {}).get('content', row.get('error'))
                           for row in trace.get('trace', [])]
            print(f'原Die后300渲染帧分支 {index + 1}/2: {transitions}', flush=True)
        report['restore_living'] = gate.restore(root['result']['id'])
        report['checks']['living_native_restored'] = observe(gate) == before
        report['checks']['death_trace_and_png_repeated'] = report['branches'][0] == report['branches'][1]
        report['checks']['full_render_interval_exercised'] = all(
            b['trace'].get('frames') == 300 and b['trace'].get('done') and not b['trace'].get('error')
            for b in report['branches'])
        if lethal:
            report['checks']['native_zero_health_observed'] = all(
                any((row.get('state') or {}).get('health') == 0 for row in b['trace'].get('trace', []))
                for b in report['branches'])
        job = gate.step(3, 'jump')
        report['living_input'] = job
        report['checks']['living_input_after_callbacks_restored'] = (
            job['after']['health'] == before['native']['state']['health'] and job['after']['physics'] != 'die: 31')
        gate.restore(root['result']['id'])
        report['pass_'] = all(report['checks'].values())
        return report
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        for name in ('lifecycle.py', 'gate.py', 'game_gate.lua', 'worker.rs'):
            shutil.copy2(Path(__file__).parent / name, output / name)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
