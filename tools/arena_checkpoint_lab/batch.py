"""Resumable fixed-board work queue within the one leased search VM.

Native selection initializes a new case. Every search undo is a VM restore;
failed cases remain explicit and never become passes merely by being visited.
"""
import json
from pathlib import Path
import time

from arena_fixed_catalog import load_inventory
from collector import References, install_observer
from route import export
import search


def lua(value):
    if isinstance(value, dict):
        return '{' + ','.join('[' + json.dumps(str(k)) + ']=' + lua(v) for k, v in value.items()) + '}'
    return json.dumps(value)


def native_call(gate, code, progress, timeout=900):
    started = time.monotonic()
    try:
        return gate.call('exec', code=code)
    except TimeoutError:
        pass
    # Continue exactly the same pending command; do not issue another command
    # or reinitialize the scene to conceal a slow original asynchronous load.
    while time.monotonic() - started < timeout:
        progress(dict(phase='native_selection_pending', seconds=time.monotonic() - started))
        try:
            view = gate._wait(timeout=20)
        except TimeoutError:
            continue
        last = view.get('last') or {}
        if not last.get('ok'):
            raise RuntimeError(last.get('error', 'Original selection command failed'))
        return last.get('result')
    raise TimeoutError('The same native selection did not finish within the case deadline')


def initialize(gate, case, progress, seed=55200):
    root = gate.snapshot()['result']['id']
    try:
        native_call(gate, 'return MR3A.native_select(' + lua(case['selection']) + ',' + str(seed) + ')', progress)
        travel = gate.call('exec', code='return MR3A.travel')
        progress(dict(phase='native_selection_completed',native_travel=travel))
        # The original wait_ready can expire while software rendering finishes
        # the same scene. Finish that initialization, not a search rollback.
        for attempt in range(85):
            state = gate.call('state')
            if state.get('state') == 'Game: 8':
                board = gate.call('exec', code=search.BOARD)
                ready = (state.get('content') == 'Running: 1' and state.get('health') == 5000
                         and board['map'] == case['map'] and board['stage_id'] == case['stage']
                         and board['stage_index'] == case['slot'] - 1 and not board['god'] and not board['mounted'])
                if ready:
                    return dict(travel=travel, state=state, board=board, continued_steps=attempt)
                if case['slot'] != 1 or state.get('health', 0) <= 0:
                    break
                try:
                    gate.step(1)
                except RuntimeError as error:
                    if 'Physics ticks stopped advancing' not in str(error):
                        raise
            else:
                break
        progress(dict(phase='native_entry_rejected',rejected_state=state,
                      rejected_board=board if state.get('state')=='Game: 8' else None))
        raise RuntimeError('Original selection did not produce the requested safe, unmounted board entry')
    except BaseException:
        gate.restore(root)
        raise


class WorkQueue:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / 'coverage.json'
        self.inventory = load_inventory()
        self.state = json.loads(path.read_text()) if path.exists() else dict(schema=1, cases={})
        self.cases = {c['key']: c for c in self.inventory['contexts']}
        for key, case in self.cases.items():
            self.state['cases'].setdefault(key, dict(status='pending', attempts=[],
                native_passed=False, detector_verified=False, live_runner_verified=False))
        (self.folder / 'inventory.json').write_text(json.dumps(self.inventory, ensure_ascii=False, indent=2))
        self.save()

    def save(self):
        cases = list(self.state['cases'].values())
        self.state['counts'] = dict(self.inventory['counts'], native_passed=sum(c['native_passed'] for c in cases),
            detector_verified=sum(c['detector_verified'] for c in cases),
            live_runner_verified=sum(c['live_runner_verified'] for c in cases))
        self.state['updated_at'] = time.time()
        temporary = self.folder / 'coverage.tmp'
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
        temporary.replace(self.folder / 'coverage.json')

    def pending(self):
        cases = [c for key, c in self.cases.items() if not (self.state['cases'][key]['native_passed']
                 and self.state['cases'][key].get('reference_count', 0) >= 3)]
        return sorted(cases, key=lambda c: (bool(self.state['cases'][c['key']]['attempts']),c['kind'] != 'ordinary',
            c['level'] not in (5, 6),c['slot']!=1,
            len(self.inventory['stages'][str(c['stage'])]['groups']), c['key']))

    def adopt(self, artifact):
        artifact = Path(artifact)
        route = json.loads(artifact.read_text())
        start = route['start']
        if (not route.get('complete') or route.get('uses_restart_replay') is not False
                or start['board']['god'] or any(row['before']['health'] != start['health']
                or row['after']['health'] != start['health'] for row in route['steps'])):
            raise ValueError('Existing route does not prove an undamaged native exit')
        matches = [c for c in self.cases.values() if (c['map'], c['slot'] - 1, c['stage']) == (
            start['board']['map'], start['board']['stage_index'], start['board']['stage_id'])]
        if len(matches) != 1:
            raise ValueError('Existing route context is not unique in the canonical catalog')
        item = self.state['cases'][matches[0]['key']]
        item.update(native_passed=True, status='needs_references', route=str(artifact), reference_count=0)
        self.save()

    def accept(self, case, report, report_path, references):
        passed = bool(report.get('complete') and report.get('no_health_loss')
                      and report['start']['board']['stage_id'] == case['stage']
                      and report['start']['board']['map'] == case['map']
                      and report['start']['board']['stage_index'] == case['slot'] - 1
                      and not report['start']['board']['god'])
        item = self.state['cases'][case['key']]
        if passed:
            artifact = Path(report_path).parent / 'route.json'
            export([report_path], artifact)
            item.update(route=str(artifact), references=str(references.folder / 'references.json'),
                        reference_count=len(references.rows), reference_errors=references.errors)
        item.update(status='native_passed' if passed else 'search_stalled',
                    native_passed=item['native_passed'] or passed)
        self.save()
        return passed

    def run(self, gate, *, cases=None,retain_history=False):
        work = self.pending() if cases is None else cases
        for index, case in enumerate(work):
            item = self.state['cases'][case['key']]
            if item['native_passed'] and item.get('reference_count', 0) >= 3:
                continue
            name = str(time.time_ns())
            output = self.folder / 'runs' / case['key'] / name
            output.mkdir(parents=True, exist_ok=False)
            attempt = dict(output=str(output), started_at=time.time(), status='initializing')
            item['attempts'].append(attempt)
            item['status'] = 'initializing'
            self.state['active'] = case['key']
            self.save()
            print(f'固定板队列 {index + 1}/{len(work)}: {case["key"]}', flush=True)
            try:
                def progress(value):
                    attempt.update(value)
                    self.save()
                attempt['entry'] = initialize(gate, case, progress)
                attempt['observer_sha256'] = install_observer(gate)
                references = References(output / 'references')
                item['status'] = attempt['status'] = 'searching'
                self.save()
                report = search.run(gate, output / 'search', collector=references, max_windows=600,
                                    retain_history=retain_history)
                attempt['status'] = 'native_passed' if self.accept(
                    case, report, output / 'search/report.json', references) else 'search_stalled'
            except KeyboardInterrupt:
                attempt['status'] = item['status'] = 'interrupted'
                self.save()
                raise
            except Exception as error:
                attempt.update(status='failed', error=repr(error))
                item['status'] = 'failed'
                self.save()
                print(f'保留失败案例 {case["key"]}: {error}', flush=True)
                # Never overwrite an unfinished gate command. Initialization
                # restores its known VM point; search itself parks at a root.
                vm=getattr(gate,'vm',None)
                process=getattr(vm,'process',None)
                if (gate.waiting or getattr(vm,'uncertain_operation',None)
                        or process is not None and process.poll()is not None):
                    raise
            finally:
                attempt['finished_at'] = time.time()
                self.save()
        self.state['active'] = None
        self.save()
        return self.state['counts']
