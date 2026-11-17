#!/usr/bin/env python3
"""Internal console for the isolated named Android checkpoint guest."""
import code
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
sys.path.insert(0, str(ROOT / 'tools/arena_checkpoint_lab'))
from runtime import InstanceSession
from runtime.checkpoint_sandbox import ArenaCheckpointSandbox


def main():
    session = InstanceSession('arena-search')
    binary = ROOT / 'debug/arena-client/rewind-research-v1/nyx-lite/target/release/arena_checkpoint_worker'
    with ArenaCheckpointSandbox(session).running(binary) as vm:
        until = time.monotonic() + 40
        while time.monotonic() < until:
            if vm.request('run', ms=500)['result'].get('agent_ready'):
                break
        else:
            raise TimeoutError('Android boot agent unavailable; inspect the private worker.log')
        def sh(command, timeout=30):
            return vm.command(command, timeout=timeout)
        def start_client():
            from boot_client import start
            return start(vm)
        code.interact(banner='arena-search guest agent ready; vm and sh are bound to its named lease.',
                      local=dict(vm=vm, sh=sh, session=session, start_client=start_client))


if __name__ == '__main__':
    main()
