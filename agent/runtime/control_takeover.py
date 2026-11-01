"""Stop the kernel-identified holder of one instance's control lease."""

from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import select
import signal
import time


def _key(stat):
    return os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino


def _locks():
    result = []
    for line in Path('/proc/locks').read_text().splitlines():
        fields = line.split()
        if len(fields) < 6 or fields[1:4] != ['FLOCK', 'ADVISORY', 'WRITE']:
            continue
        major, minor, inode = fields[5].split(':')
        result.append((int(fields[4]), (int(major, 16), int(minor, 16), int(inode))))
    return result


def _other_instance_keys(spec):
    paths = [spec.project_root / 'deps/bin/control.lock']
    paths.extend((spec.project_root / '.mr3a-instances').glob('*/control.lock'))
    own = spec.work_root / 'control.lock'
    return {_key(path.stat()) for path in paths if path != own and path.exists()}


def _children(pid):
    parents = {}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            stat = (proc / 'stat').read_text()
            parents[int(proc.name)] = int(stat[stat.rfind(')') + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            pass
    descendants = set()
    pending = [pid]
    while pending:
        parent = pending.pop()
        for child, ppid in parents.items():
            if ppid == parent and child not in descendants:
                descendants.add(child)
                pending.append(child)
    return descendants


def _alive(fd):
    poll = select.poll()
    poll.register(fd, select.POLLIN)
    return not poll.poll(0)


def _send(fd, sig):
    try:
        signal.pidfd_send_signal(fd, sig)
    except ProcessLookupError:
        pass


def _acquire(lock):
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def acquire_by_stopping_controller(lock, spec, timeout):
    """Acquire the same inode; never unlink a busy lease or accept a caller PID."""
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('当前系统不支持安全的实例接管')
    key = _key(os.fstat(lock.fileno()))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _acquire(lock):
            return
        owners = [pid for pid, entry in _locks() if entry == key]
        if not owners:
            time.sleep(0.05)
            continue
        owner = owners[0]
        if owner <= 1 or owner == os.getpid():
            raise RuntimeError('无法安全接管当前控制者')
        with ExitStack() as stack:
            try:
                fd = os.pidfd_open(owner)
            except ProcessLookupError:
                continue
            stack.callback(os.close, fd)
            # Re-read after pidfd_open: neither a reused PID nor stale metadata
            # can authorize a signal to a process that no longer owns our lock.
            locks = _locks()
            if (owner, key) not in locks or not _alive(fd):
                continue
            if Path(f'/proc/{owner}').stat().st_uid != os.getuid():
                raise RuntimeError('不能接管其它用户的控制进程')
            descendants = _children(owner)
            family = descendants | {owner}
            other = _other_instance_keys(spec)
            if any(pid in family and entry in other for pid, entry in locks):
                raise RuntimeError('当前控制进程也持有其它实例，拒绝跨实例停止')
            children = []
            for pid in descendants:
                try:
                    child_fd = os.pidfd_open(pid)
                except ProcessLookupError:
                    continue
                stack.callback(os.close, child_fd)
                # Only retain handles still in this owner's process tree.
                if pid in _children(owner):
                    children.append(child_fd)
            try:
                executable = Path(os.readlink(f'/proc/{owner}/exe')).name.removesuffix(' (deleted)')
            except OSError:
                continue
            is_picli = executable == 'MaaPiCli'
            _send(fd, signal.SIGUSR1 if is_picli else signal.SIGTERM)
            grace = min(deadline, time.monotonic() + (5 if is_picli else 1))
            while _alive(fd) and time.monotonic() < grace:
                time.sleep(0.05)
            if _alive(fd):
                _send(fd, signal.SIGTERM)
                grace = min(deadline, time.monotonic() + 1)
                while _alive(fd) and time.monotonic() < grace:
                    time.sleep(0.05)
            if _alive(fd):
                _send(fd, signal.SIGKILL)
            # Do not leave an inherited lease or input subprocess behind.
            for child_fd in children:
                if _alive(child_fd):
                    _send(child_fd, signal.SIGTERM)
            grace = min(deadline, time.monotonic() + 0.5)
            while any(_alive(child_fd) for child_fd in children) and time.monotonic() < grace:
                time.sleep(0.05)
            for child_fd in children:
                if _alive(child_fd):
                    _send(child_fd, signal.SIGKILL)
        # A different owner could have won the lock during shutdown. Only the
        # original controller is stopped by this request, never a stream of peers.
        while time.monotonic() < deadline:
            if _acquire(lock):
                return
            if any(pid != owner and entry == key for pid, entry in _locks()):
                raise RuntimeError('控制权已被新的请求取得，请重新检查状态')
            time.sleep(0.05)
        break
    raise RuntimeError(f'接管实例 {spec.name} 超时，控制锁尚未释放')
