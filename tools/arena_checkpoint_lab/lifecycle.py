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
