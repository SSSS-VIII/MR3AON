#!/usr/bin/env python3
"""Copy the original arena APK and explicit game-resource whitelist, no accounts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
sys.path.insert(0, str(ROOT / 'tools'))
from runtime import InstanceSession
from arena_local import PACKAGE
from arena_bootstrap import APK_SHA256

WHITELIST = ('AssetBundles', 'FMODBanks', 'NCONFIG', 'AssetBundleMD5.bytes', 'Manifest',
             'PatchVersion', 'LeastPatchAppVersion', 'BankMoveVersion')


def prepare():
    output = ROOT / 'debug/arena-client/rewind-research-v1/android-payload'
    output.mkdir(mode=0o700, exist_ok=False)
    source = InstanceSession('arena')
    with source.control():
        paths = source.adb('shell', 'pm', 'path', PACKAGE).stdout.decode().splitlines()
        apk = next(line.removeprefix('package:') for line in paths if line.endswith('/base.apk'))
        source.adb('pull', apk, str(output / 'client.apk'), timeout=120).check_returncode()
        with (output / 'client.apk').open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != APK_SHA256:
            raise ValueError('Original arena APK changed; establish the new revision first')
        folder = f'/sdcard/Android/data/{PACKAGE}/files/DynamicContent'
        with source.adb_stream('exec-out', 'tar', '-C', folder, '-cf', '-', *WHITELIST) as process:
            with (output / 'game-assets.tar').open('xb') as stream:
                shutil.copyfileobj(process.stdout, stream, 4 * 1024 * 1024)
            error = process.stderr.read()
            if process.wait(timeout=10):
                raise RuntimeError(error.decode(errors='replace'))
    # This key is a resource decrypt parameter, not a login/Android account file.
    shutil.copy2(ROOT / 'debug/arena-client/raw/bundle-key', output / 'resource-key')
    (output / 'resource-key').chmod(0o600)
    for name in ('bootstrap.lua', 'environment.lua', 'native_mount.lua', 'native_selection.lua',
                 'native_boss.lua', 'native_menu.lua', 'vision_labels.lua', 'rewind_probe.lua'):
        shutil.copy2(ROOT / 'arena/Local' / name, output / name)
    shutil.copy2(ROOT / 'debug/arena-client/gameonly/gale-catalog-native.json', output / 'catalog-native.json')
    subprocess.run(['split', '-b', '1G', '-d', '-a', '2', str(output / 'game-assets.tar'),
                    str(output / 'assets.tar.')], check=True)
    (output / 'game-assets.tar').rename(output.parent / 'android-game-assets-original.tar')
    (output / 'manifest.json').write_text(json.dumps(dict(source_instance='arena',
        original_apk_sha256=actual, resource_paths=WHITELIST, copied_accounts=False,
        scope='Offline original-client inputs; no rollback acceptance yet'), indent=2))
    disk = output.parent / 'android-payload.img'
    size = sum(path.stat().st_size for path in output.iterdir())
    with disk.open('xb') as stream:
        stream.truncate(((size + 1024**3 + 4095) // 4096) * 4096)
    subprocess.run(['mke2fs', '-q', '-F', '-t', 'ext4', '-b', '4096', '-d', str(output), str(disk)], check=True)
    print(json.dumps(dict(files_bytes=size, payload=str(disk), copied_accounts=False)))


if __name__ == '__main__':
    prepare()
