#!/usr/bin/env python3
"""Build an isolated synthetic VM fixture; never connects to an Android instance.

Nyx-Lite and a compatible ELF kernel are explicit local inputs. The experiment
does not install a kernel/module, change networking, or migrate the arena client.
"""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def command(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy_elf_libraries(binary, root):
    libraries = subprocess.check_output(['ldd', str(binary)], text=True)
    if 'not found' in libraries:
        raise RuntimeError(libraries)
    for source in set(re.findall(r'(/[^\s()]+)', libraries)):
        source = Path(source)
        destination = root / source.relative_to('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def prepare(nyx_root, kernel, output, mem_mib=1024, *, software_gl=False,
            android_primitives=False, virtio_module=None, initrd=False, clocksource=None):
    nyx_root, kernel, output = map(lambda p: Path(p).resolve(), (nyx_root, kernel, output))
    if not (nyx_root / 'src/nyx_vm.rs').is_file() or not kernel.is_file():
        raise ValueError('Supply the existing Nyx-Lite source and ELF guest kernel')
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / 'sources'
    frozen.mkdir()
    for source in HERE.iterdir():
        if source.is_file():
            shutil.copy2(source, frozen / source.name)
    root = output / 'rootfs'
    root.mkdir()
    for name in ('proc', 'sys', 'dev', 'tmp'):
        (root / name).mkdir()
    guest = root / 'init'
    flags = []
    if android_primitives:
        flags.append('-DCHECKPOINT_ANDROID_PRIMITIVES')
    if software_gl:
        flags += ['-DCHECKPOINT_SOFTWARE_GL', '-lEGL', '-lGLESv2']
    command('gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread', HERE / 'guest.c', '-o', guest, *flags)
    copy_elf_libraries(guest, root)
    if software_gl:
        for source in (Path('/usr/lib64/libEGL_mesa.so.0'), Path('/usr/lib64/dri/swrast_dri.so')):
            destination = root / source.relative_to('/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copy_elf_libraries(source, root)
        (root / 'egl-vendor.json').write_text(json.dumps({
            'file_format_version': '1.0.0', 'ICD': {'library_path': '/usr/lib64/libEGL_mesa.so.0'}}))
    if virtio_module:
        with lzma.open(virtio_module, 'rb') as stream:
            (root / 'virtio_mmio.ko').write_bytes(stream.read())
    disk = output / 'rootfs.ext4'
    with disk.open('wb') as stream:
        stream.truncate(512 * 1024 * 1024)
    command('mke2fs', '-q', '-F', '-t', 'ext4', '-b', '4096', '-d', root, disk)
    cargo = nyx_root / 'Cargo.toml'
    before = cargo.read_text()
    entry = '\n[[bin]]\nname = "arena_snapshot_bench"\npath = "src/arena_snapshot_bench.rs"\n'
    if 'name = "arena_snapshot_bench"' not in before:
        cargo.write_text(before + entry)
    shutil.copy2(HERE / 'bench.rs', nyx_root / 'src/arena_snapshot_bench.rs')
    config = {
        'boot-source': {
            'kernel_image_path': str(kernel),
            'boot_args': 'rw console=ttyS0 reboot=k panic=1 pci=off nomodules random.trust_cpu=on init=/init',
        },
        'drives': [{'drive_id': 'rootfs', 'path_on_host': str(disk),
                    'is_root_device': True, 'is_read_only': False, 'io_engine': 'Cow'}],
        'network-interfaces': [],
        'machine-config': {'vcpu_count': 1, 'mem_size_mib': mem_mib},
    }
    if initrd:
        ramdisk = output / 'initramfs.cpio'
        names = [str(p.relative_to(root)) for p in sorted(root.rglob('*'))]
        with ramdisk.open('wb') as stream:
            command('cpio', '--quiet', '--null', '-o', '-H', 'newc', cwd=root,
                    input=b'\0'.join(name.encode() for name in names) + b'\0', stdout=stream)
        config['boot-source']['initrd_path'] = str(ramdisk)
    if clocksource:
        config['boot-source']['boot_args'] += ' clocksource=' + clocksource
    core_patch = subprocess.check_output([
        'git', '-C', str(nyx_root), 'diff', '--', 'src/nyx_vm.rs', 'src/snapshot.rs'])
    (output / 'nyx-core.patch').write_bytes(core_patch)
    (output / 'vmconfig.json').write_text(json.dumps(config, indent=2))
    manifest = {
        'scope': 'Synthetic fixture only. Not an Android/game checkpoint implementation.',
        'nyx_revision': subprocess.check_output(['git', '-C', str(nyx_root), 'rev-parse', 'HEAD'], text=True).strip(),
        'kernel_sha256': sha(kernel), 'base_disk_sha256': sha(disk),
        'guest_sha256': sha(guest),
        'nyx_firecracker_revision': subprocess.check_output([
            'git', '-C', str(nyx_root / 'vendor/firecracker-nyx-patches'), 'rev-parse', 'HEAD'], text=True).strip(),
        'cargo_lock_sha256': sha(nyx_root / 'Cargo.lock'),
        'nyx_core_patch_sha256': sha(output / 'nyx-core.patch'),
        'source_sha256': {p.name: sha(p) for p in HERE.iterdir() if p.is_file()},
        'mem_mib': mem_mib, 'vcpu_count': 1, 'network': False,
        'software_gl': software_gl, 'android_primitives': android_primitives,
    }
    shutil.copy2(nyx_root / 'Cargo.lock', output / 'Cargo.lock')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'config': str(output / 'vmconfig.json'), 'scope': manifest['scope']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nyx-root', type=Path, required=True)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mem-mib', type=int, choices=(256, 512, 1024, 2048, 3072), default=1024)
    parser.add_argument('--software-gl', action='store_true', help='Guest llvmpipe/EGL test, no host GPU')
    parser.add_argument('--android-primitives', action='store_true', help='Require a guest Binder-capable kernel')
    parser.add_argument('--virtio-module', type=Path, help='Matching guest virtio_mmio.ko.xz, if modular')
    parser.add_argument('--initrd', action='store_true', help='Boot the fixture from an isolated initramfs')
    parser.add_argument('--clocksource', choices=('tsc', 'kvm-clock'), help='Exercise a specific guest clock')
    args = parser.parse_args()
    prepare(args.nyx_root, args.kernel, args.output, args.mem_mib,
            software_gl=args.software_gl, android_primitives=args.android_primitives,
            virtio_module=args.virtio_module, initrd=args.initrd, clocksource=args.clocksource)
