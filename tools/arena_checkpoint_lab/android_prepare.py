#!/usr/bin/env python3
"""Prepare fresh Android images for the named arena-search checkpoint backend.

Reads only shared OS images, ARM translation files, and downloaded Weston RPMs.
No Android account/userdata is copied. Every writable image is private + COW.
"""
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
from runtime import InstanceSession
from runtime.instances import write_json
from prepare import sha, command

RESEARCH = ROOT / 'debug/arena-client/rewind-research-v1'
NYX = RESEARCH / 'nyx-lite'
KERNEL_VERSION = '7.1.12-200.fc44.x86_64'


def set_phase(session, phase):
    if not session._owns_control or session.spec.name!='arena-search' or phase not in ('provision','checkpoint'):
        raise ValueError('Phase changes require the named search lease')
    target=session.spec.work_root/'checkpoint'
    if (target/'control.sock').exists():
        raise RuntimeError('Stop the guest before changing its disk mode')
    path=target/'vmconfig.json'
    config=json.loads(path.read_text())
    found=False
    for drive in config['drives']:
        if drive['drive_id']=='userdata':
            drive['io_engine']='Sync' if phase=='provision' else 'Cow'
            found=True
    if not found:raise ValueError('Private userdata drive missing')
    write_json(path,config)
    write_json(target/'phase.json',{'phase':phase,'snapshot_allowed':phase=='checkpoint'})


def refresh_boot(session):
    """Rebuild only private boot programs/ramdisk; never replace userdata."""
    if not session._owns_control or session.spec.name != 'arena-search':
        raise RuntimeError('Boot image rebuild requires the named search lease')
    target = session.spec.work_root / 'checkpoint'
    if (target / 'control.sock').exists():
        raise RuntimeError('Stop the guest before rebuilding its boot image')
    root = target / 'guest-root'
    with lzma.open(Path('/usr/lib/modules') / KERNEL_VERSION / 'kernel/drivers/net/dummy.ko.xz', 'rb') as stream:
        (root / 'modules/dummy.ko').write_bytes(stream.read())
    for source,name in [('net/netfilter/nfnetlink.ko.xz','nfnetlink'),
                        ('net/netfilter/nfnetlink_log.ko.xz','nfnetlink_log'),
                        ('fs/fuse/fuse.ko.xz','fuse')]:
        with lzma.open(Path('/usr/lib/modules') / KERNEL_VERSION / 'kernel' / source,'rb') as stream:
            (root/'modules'/(name+'.ko')).write_bytes(stream.read())
    props=root/'waydroid.prop'
    text=props.read_text()
    if 'persist.waydroid.no_presentation=' not in text:
        props.write_text(text+'persist.waydroid.no_presentation=true\n')
    command('gcc', '-O2', '-Wall', '-Wextra', '-Werror', HERE / 'android_init.c', '-o', root / 'init')
    command('gcc', '-O2', '-Wall', '-Wextra', '-Werror', HERE / 'android_agent.c', '-o', root / 'checkpoint-agent')
    names = [str(p.relative_to(root)) for p in sorted(root.rglob('*'))]
    temporary = target / 'initramfs.cpio.tmp'
    with temporary.open('wb') as stream:
        command('cpio', '--quiet', '--null', '-o', '-H', 'newc', cwd=root,
                input=b'\0'.join(name.encode() for name in names) + b'\0', stdout=stream)
    temporary.replace(target / 'initramfs.cpio')
    build = target / 'build.json'
    data = json.loads(build.read_text())
    data['source_sha256'] = {name: sha(HERE / name) for name in ('android_init.c', 'android_agent.c', 'worker.rs')}
    data['initramfs_sha256'] = sha(target / 'initramfs.cpio')
    build.write_text(json.dumps(data, indent=2))


def libraries(binary, root):
    import re
    env = dict(os.environ, LD_LIBRARY_PATH=':'.join(str(root / name) for name in
               ('usr/lib64', 'usr/lib64/weston', 'usr/lib64/libweston-15')))
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, env=env)
    if result.returncode:
        if 'not a dynamic executable' in result.stderr + result.stdout:
            return
        raise RuntimeError(result.stderr)
    if 'not found' in result.stdout:
        raise RuntimeError(f'{binary}: {result.stdout}')
    for name in set(re.findall(r'(/[^\s()]+)', result.stdout)):
        source = Path(name)
        if source.is_relative_to(root):
            continue
        target = root / source.relative_to('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def prepare():
    session = InstanceSession('arena-search')
    with session.control():
        target = session.spec.work_root / 'checkpoint'
        if (target / 'vmconfig.json').exists():
            raise RuntimeError('Refuse to replace an already prepared named guest')
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        root = target / 'guest-root'
        root.mkdir(exist_ok=False)
        for path in ('dev', 'proc', 'sys', 'tmp', 'run', 'modules'):
            (root / path).mkdir()
        for rpm in sorted((RESEARCH / 'weston-rpms').glob('*.x86_64.rpm')):
            archive = subprocess.check_output(['rpm2cpio', str(rpm)])
            command('cpio', '--quiet', '-i', '-d', '--no-absolute-filenames', '--no-preserve-owner',
                    input=archive, cwd=root)
        if not (root / 'usr/bin/weston').is_file():
            raise RuntimeError('Download the weston + weston-libs x86_64 RPMs first')
        command('gcc', '-O2', '-Wall', '-Wextra', '-Werror', HERE / 'android_init.c', '-o', root / 'init')
        command('gcc', '-O2', '-Wall', '-Wextra', '-Werror', HERE / 'android_agent.c', '-o', root / 'checkpoint-agent')
        for binary in [root / 'init', root / 'checkpoint-agent', root / 'usr/bin/weston',
                       *list((root / 'usr/lib64').rglob('*.so*'))]:
            if binary.is_file():
                libraries(binary, root)
        module_root = Path('/usr/lib/modules') / KERNEL_VERSION / 'kernel'
        for source, name in [('drivers/virtio/virtio_mmio.ko.xz', 'virtio_mmio'),
                             ('fs/overlayfs/overlay.ko.xz', 'overlay'),
                             ('fs/binfmt_misc.ko.xz', 'binfmt_misc'),
                             ('drivers/net/dummy.ko.xz', 'dummy'),
                             ('net/netfilter/nfnetlink.ko.xz', 'nfnetlink'),
                             ('net/netfilter/nfnetlink_log.ko.xz', 'nfnetlink_log'),
                             ('fs/fuse/fuse.ko.xz', 'fuse')]:
            with lzma.open(module_root / source, 'rb') as stream:
                (root / 'modules' / (name + '.ko')).write_bytes(stream.read())
        props = '\n'.join([
            'sys.use_memfd=true', 'debug.stagefright.ccodec=0',
            'ro.hardware.gralloc=default', 'ro.hardware.egl=angle', 'ro.hardware.vulkan=pastel',
            'ro.hardware.camera=v4l2', 'ro.vndk.lite=true', 'ro.opengles.version=196609',
            'waydroid.updater.disabled=true', 'waydroid.tools_version=1.6.3',
            'waydroid.host.uid=1000', 'waydroid.host.gid=1000', 'waydroid.host.user=offline',
            'waydroid.host_data_path=/data', 'waydroid.xdg_runtime_dir=/run/xdg',
            'waydroid.pulse_runtime_path=/run/xdg/pulse', 'waydroid.wayland_display=wayland-0',
            'waydroid.stub_sensors_hal=1', 'waydroid.background_start=false',
            'persist.waydroid.no_presentation=true',
            'ro.product.cpu.abilist=x86_64,x86,arm64-v8a,armeabi-v7a,armeabi',
            'ro.product.cpu.abilist32=x86,armeabi-v7a,armeabi',
            'ro.product.cpu.abilist64=x86_64,arm64-v8a',
            'ro.dalvik.vm.native.bridge=libhoudini.so', 'ro.enable.native.bridge.exec=1',
            'ro.dalvik.vm.isa.arm=x86', 'ro.dalvik.vm.isa.arm64=x86_64', '',
        ])
        (root / 'waydroid.prop').write_text(props)
        images = target / 'images'
        images.mkdir()
        hashes = {}
        for name in ('system.img', 'vendor.img'):
            source = Path('/var/lib/waydroid/images') / name
            command('cp', '--reflink=auto', '--sparse=always', source, images / name)
            hashes[name] = sha(images / name)
        seed = target / 'userdata-seed'
        upper = seed / 'system-upper/system'
        upper.mkdir(parents=True)
        source_slot = InstanceSession('arena').spec.slot
        translation = Path(f'/var/lib/waydroid-mr3a{source_slot}/overlay/system')
        for name in ('lib', 'lib64'):
            shutil.copytree(translation / name, upper / name, symlinks=True)
        for name in ('bin/houdini', 'bin/houdini64', 'etc/init/houdini.rc',
                     'etc/cpuinfo.arm.txt', 'etc/cpuinfo.arm64.txt'):
            source = translation / name
            destination = upper / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                destination.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, destination)
        userdata = images / 'userdata.img'
        with userdata.open('xb') as stream:
            stream.truncate(8 * 1024**3)
        command('mke2fs', '-q', '-F', '-t', 'ext4', '-b', '4096', '-d', seed, userdata)
        ramdisk = target / 'initramfs.cpio'
        names = [str(p.relative_to(root)) for p in sorted(root.rglob('*'))]
        with ramdisk.open('xb') as stream:
            command('cpio', '--quiet', '--null', '-o', '-H', 'newc', cwd=root,
                    input=b'\0'.join(name.encode() for name in names) + b'\0', stdout=stream)
        config = {
            'boot-source': {'kernel_image_path': str(RESEARCH / 'vmlinux-host-binder'),
                            'initrd_path': str(ramdisk),
                            'boot_args': 'console=ttyS0 reboot=k panic=1 pci=off selinux=0 androidboot.selinux=permissive random.trust_cpu=off init=/init'},
            'drives': [dict(drive_id=name, path_on_host=str(images / (name + '.img')),
                            is_root_device=False, is_read_only=False, io_engine='Cow')
                       for name in ('system', 'vendor', 'userdata')],
            'network-interfaces': [], 'machine-config': {'vcpu_count': 1, 'mem_size_mib': 3072},
        }
        payload = RESEARCH / 'android-payload.img'
        if payload.exists():
            command('cp', '--reflink=auto', '--sparse=always', payload, images / 'payload.img')
            config['drives'].append(dict(drive_id='payload', path_on_host=str(images / 'payload.img'),
                                         is_root_device=False, is_read_only=False, io_engine='Cow'))
            hashes['payload.img'] = sha(images / 'payload.img')
        (target / 'vmconfig.json').write_text(json.dumps(config, indent=2))
        shutil.copy2(HERE / 'worker.rs', NYX / 'src/arena_checkpoint_worker.rs')
        cargo = NYX / 'Cargo.toml'
        text = cargo.read_text()
        if 'serde_json =' not in text:
            text = text.replace('[dependencies]', '[dependencies]\nserde_json = "1"', 1)
        if 'name = "arena_checkpoint_worker"' not in text:
            text += '\n[[bin]]\nname = "arena_checkpoint_worker"\npath = "src/arena_checkpoint_worker.rs"\n'
        cargo.write_text(text)
        (target / 'build.json').write_text(json.dumps(dict(instance=session.spec.name,
            copied_accounts=False, source_os_images=hashes, kernel_sha256=sha(RESEARCH / 'vmlinux-host-binder'),
            source_sha256={name:sha(HERE / name) for name in ('android_init.c', 'android_agent.c', 'worker.rs')},
            scope='Android boot integration in progress; no game rollback acceptance'), indent=2))
        print(target)


if __name__ == '__main__':
    prepare()
