#!/usr/bin/env python3
"""Install the opt-in host RAM backing patch into the private research clone."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout',type=Path,required=True)
    args=parser.parse_args();checkout=args.checkout.resolve()
    if not checkout.is_relative_to(ROOT/'debug/arena-client'):
        raise ValueError('Only a private arena research checkout may be patched')
    patches=[HERE/name for name in ('ram_file.patch','ram_restore.patch','restore_trace.patch')]
    paths=('Cargo.toml','src/snapshot.rs','src/nyx_vm.rs')
    backup={name:(checkout/name).read_bytes()for name in paths}
    try:
        # Later instrumentation overlaps earlier hunks. Peel supported layers
        # from the top before checking/reapplying the complete stack.
        for patch in reversed(patches):
            reverse=subprocess.run(['git','apply','-R','--check',str(patch)],cwd=checkout,capture_output=True)
            if reverse.returncode==0:subprocess.run(['git','apply','-R',str(patch)],cwd=checkout,check=True)
        for patch in patches:
            check=subprocess.run(['git','apply','--check',str(patch)],cwd=checkout,capture_output=True)
            if check.returncode:raise RuntimeError('Unsupported private patch state for '+patch.name)
            subprocess.run(['git','apply',str(patch)],cwd=checkout,check=True)
    except BaseException:
        for name,data in backup.items():(checkout/name).write_bytes(data)
        raise
    files={'ram_file.rs':'ram_file.rs','worker_file.rs':'arena_checkpoint_file_worker.rs',
           'bench_file.rs':'arena_file_snapshot_bench.rs'}
    for source,target in files.items():shutil.copyfile(HERE/source,checkout/'src'/target)
    print(json.dumps(dict(installed=True,checkout=str(checkout),feature='arena-file-ram')))


if __name__=='__main__':main()
