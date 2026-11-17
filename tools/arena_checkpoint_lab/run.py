#!/usr/bin/env python3
"""Run the synthetic checkpoint benchmark and retain failures/integrity evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clock_checks(rows):
    clocks = [row for row in rows if row.get('metric') == 'clock_and_pending_timer']
    if len(clocks) != 3 or {row.get('index') for row in clocks} != {0, 15, 30}:
        return False
    return all(row.get('expired') == 0 and all(
        type(row.get(key)) is int and 0 <= row[key] < 10_000_000
        for key in ('clock_error_ns', 'timer_error_ns')) for row in clocks)


def run(binary, output, rounds=300):
    output = Path(output).resolve()
    binary = Path(binary).resolve()
    config = json.loads((output / 'vmconfig.json').read_text())
    manifest = json.loads((output / 'manifest.json').read_text())
    if config.get('network-interfaces') or config['machine-config']['vcpu_count'] != 1:
        raise ValueError('This lab only supports an isolated single-vCPU fixture without network')
    drives = config.get('drives', [])
    if len(drives) != 1 or drives[0].get('io_engine') != 'Cow':
        raise ValueError('This lab requires exactly one private COW fixture disk')
    disk = Path(drives[0]['path_on_host']).resolve()
    if not disk.is_relative_to(output):
        raise ValueError('The fixture disk must be inside this prepared output directory')
    if sha(disk) != manifest['base_disk_sha256']:
        raise ValueError('Fixture disk changed since preparation')
    if sha(output / 'rootfs/init') != manifest['guest_sha256']:
        raise ValueError('Fixture binary changed since preparation')
    if not 1 <= rounds <= 10_000:
        raise ValueError('rounds must be 1..10000')
    start = time.monotonic()
    report = dict(schema=1, scope=manifest['scope'], game_rollback_complete=False,
                  benchmark_binary_sha256=sha(binary), rounds=rounds)
    log = output / 'benchmark.log'
    with log.open('xb') as stream:
        try:
            process = subprocess.run([str(binary), str(output / 'vmconfig.json'), str(rounds)],
                                     stdout=stream, stderr=subprocess.STDOUT, timeout=300)
            report['exit_code'] = process.returncode
        except subprocess.TimeoutExpired:
            report['exit_code'] = None
            report['timeout'] = True
    report['wall_seconds'] = time.monotonic() - start
    report['base_disk_unchanged'] = sha(disk) == manifest['base_disk_sha256']
    rows = []
    for line in log.read_text(errors='replace').splitlines():
        if line.startswith('{'):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    report['metrics'] = rows
    report['clock_checks_pass'] = clock_checks(rows)
    capabilities = next((row for row in rows if row.get('metric') == 'guest_capabilities'), {})
    report['capabilities_match'] = (
        (not manifest.get('android_primitives') or capabilities.get('binder_protocol') == 8)
        and (not manifest.get('software_gl') or capabilities.get('software_gl') == 1))
    report['pass'] = (report['exit_code'] == 0 and report['base_disk_unchanged']
                      and report['capabilities_match'] and bool(rows)
                      and report['clock_checks_pass'] and rows[-1].get('result') == 'pass')
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != 'metrics'}))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=300)
    args = parser.parse_args()
    raise SystemExit(run(args.binary, args.output, args.rounds))
