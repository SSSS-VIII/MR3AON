"""Live original-client checks. All undo operations restore VM snapshots."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import time

HERE = Path(__file__).resolve().parent


def rss(vm):
    for line in Path(f'/proc/{vm.process.pid}/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('Owned worker RSS unavailable')


def run(gate, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    report = dict(scope='Original game gate, finite observed native fields and native damage; broader lifecycle checks pending',
                  game_rollback_complete=False, pass_=False, uses_restart_replay=False,
                  instance=gate.vm.session.spec.name, checks={}, steps=[])
    try:
        # Finish the client's own next-map preload, without another reset.
        for _ in range(60):
            if not gate.view.get('loading'):
                break
            job = gate.step(2, 'none')
            if job['after']['health'] < job['before']['health']:
                raise RuntimeError('Native damage occurred before preload finished')
        if gate.view.get('loading'):
            raise RuntimeError('Native next-map preload did not finish')
        baseline = gate.call('probe')
        report['checks']['main_thread_observation_frozen'] = gate.call('probe') == baseline
        root = gate.snapshot()
        report['root'] = root
        repeats = []
        for index in range(4):
            restore = gate.restore(root['result']['id'])
            started = time.monotonic()
            job = gate.step(3, 'none')
            probe = gate.call('probe')
            repeats.append(dict(restore=restore, job=job, probe=probe, seconds=time.monotonic() - started))
            print(f'原生重复分支 {index + 1}/4，物理帧 {job["after"]["episodeFrame"]}', flush=True)
        report['repeats'] = repeats
        report['checks']['repeated_native_fields_equal'] = all(row['probe'] == repeats[0]['probe'] for row in repeats)
        gate.restore(root['result']['id'])

        marker = "CS.UnityEngine.Application.persistentDataPath..'/arena-control/gate-disk-marker'"
        future_file = "CS.UnityEngine.Application.persistentDataPath..'/arena-control/gate-disk-future'"
        gate.call('exec', code=f"local p={marker};CS.System.IO.File.WriteAllText(p,'past');"
                  "local f=CS.System.IO.FileStream(p,CS.System.IO.FileMode.Open,CS.System.IO.FileAccess.ReadWrite);f:Flush(true);f:Close();return true")
        disk_point = gate.snapshot()
        gate.call('exec', code=f"CS.System.IO.File.WriteAllText({marker},'future');"
                  f"CS.System.IO.File.WriteAllText({future_file},'created');"
                  f"local f=CS.System.IO.FileStream({marker},CS.System.IO.FileMode.Open,CS.System.IO.FileAccess.ReadWrite);f:Flush(true);f:Close();return true")
        gate.restore(disk_point['result']['id'])
        disk_state = gate.call('exec', code=f'return {{text=CS.System.IO.File.ReadAllText({marker}),future=CS.System.IO.File.Exists({future_file})}}')
        report['disk_restore'] = disk_state
        report['checks']['guest_file_state_restored'] = disk_state == dict(text='past', future=False)

        for index in range(12):
            started = time.monotonic()
            job = gate.step(2 if index % 2 == 0 else 3, 'none')
            if job['after']['health'] != job['before']['health']:
                raise RuntimeError('Unexpected early damage in the RAM baseline check')
            point = gate.snapshot()
            report['steps'].append(dict(job=job, point=point, seconds=time.monotonic() - started))
        before_rebase = gate.call('probe')
        expected_job = gate.step(3, 'jump')
        expected_probe = gate.call('probe')
        gate.restore(point['result']['id'])
        memory_before = rss(gate.vm)
        rebase = gate.rebase()
        memory_after = rss(gate.vm)
        same_now = gate.call('probe') == before_rebase
        actual_job = gate.step(3, 'jump')
        actual_probe = gate.call('probe')
        report['rebase'] = dict(operation=rebase, rss_before=memory_before, rss_after=memory_after,
                                native_before=before_rebase, expected=expected_probe, actual=actual_probe,
                                expected_job=expected_job, actual_job=actual_job)
        report['checks']['rebase_preserves_stopped_fields'] = same_now
        report['checks']['rebase_preserves_running_branch'] = actual_probe == expected_probe
        report['checks']['old_ram_tree_released'] = memory_after < memory_before
        gate.restore(rebase['result']['id'])
        after_disk = gate.call('exec', code=f'return {{text=CS.System.IO.File.ReadAllText({marker}),future=CS.System.IO.File.Exists({future_file})}}')
        report['checks']['disk_survives_ram_parent_release'] = after_disk == dict(text='past', future=False)
        print('原关卡RAM新基线继续运行/磁盘读取检查完成', flush=True)

        # Record an actual native collision and retry the same short boundary.
        for index in range(80):
            before = gate.call('probe')
            point = gate.snapshot()
            ticks = 2 if index % 2 == 0 else 3
            job = gate.step(ticks, 'none')
            if job['after']['health'] < job['before']['health']:
                after = gate.call('probe')
                restore = gate.restore(point['result']['id'])
                restored = gate.call('probe')
                repeated = gate.step(ticks, 'none')
                repeated_probe = gate.call('probe')
                alternatives = {}
                for action in ('jump', 'down'):
                    gate.restore(point['result']['id'])
                    alternatives[action] = gate.step(ticks, action)
                gate.restore(point['result']['id'])
                report['injury'] = dict(before=before, after=after, restore=restore, restored=restored,
                                        job=job, repeated=repeated, repeated_probe=repeated_probe,
                                        alternatives=alternatives)
                report['checks']['native_injury_restored'] = restored == before
                report['checks']['same_injury_reproduced'] = repeated_probe == after
                report['checks']['alternative_avoids_native_damage'] = any(
                    row['after']['health'] == row['before']['health'] for row in alternatives.values())
                print(f'原碰撞 {job["before"]["episodeFrame"]}→{job["after"]["episodeFrame"]}，'
                      f'{job["before"]["health"]}→{job["after"]["health"]}，恢复{restore["ms"]:.2f}ms', flush=True)
                break
        else:
            raise RuntimeError('No native damage observed within the bounded live audit')
        image_point = gate.snapshot()
        picture = gate.screenshot()
        (output / 'game.png').write_bytes(picture)
        gate.step(3, 'down')
        gate.restore(image_point['result']['id'])
        picture_again = gate.screenshot()
        (output / 'game-restored.png').write_bytes(picture_again)
        report['checks']['rendered_png_restored'] = picture_again == picture
        report['renderer_sha256'] = hashlib.sha256(picture).hexdigest()
        report['worker_status'] = gate.vm.request('status')['result']
        report['pass_'] = all(report['checks'].values())
        return report
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        for name in ('worker.rs', 'game_gate.c', 'game_gate.lua', 'gate.py', 'Gate.java', 'java_transport.c',
                     'client.py', 'client_bootstrap.lua', 'boot_client.py', 'build_bridge.py', 'audit.py'):
            shutil.copy2(HERE / name, output / name)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
