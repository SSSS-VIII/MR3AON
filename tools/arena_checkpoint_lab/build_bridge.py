"""Build only the tiny guest Java bridges; do not rebuild or resign the APK."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / 'debug/arena-client/rewind-research-v1'
OUTPUT = RESEARCH / 'client-bridge'
JNI_URL = 'https://android.googlesource.com/platform/libnativehelper/+/refs/heads/android13-release/include_jni/jni.h?format=TEXT'
JNI_SHA = '5df9074457c041b372f2c68ff646d6e8600cd673a223885e8df21c44c94ec667'


def build():
    include = RESEARCH / 'jni-include'
    include.mkdir(exist_ok=True)
    header = include / 'jni.h'
    if not header.exists():
        data = base64.b64decode(urllib.request.urlopen(JNI_URL, timeout=30).read())
        if hashlib.sha256(data).hexdigest() != JNI_SHA:
            raise ValueError('The recorded Android JNI header changed')
        header.write_bytes(data)
    if hashlib.sha256(header.read_bytes()).hexdigest() != JNI_SHA:
        raise ValueError('The Android JNI header does not match the recorded revision')
    OUTPUT.mkdir(exist_ok=True)
    for source, name in [('java_transport.c', 'java-transport.so'), ('game_gate.c', 'game-gate.so')]:
        subprocess.run(['gcc', '-shared', '-fPIC', '-nostdlib', '-fno-builtin', '-fno-stack-protector',
                        '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(include), str(HERE / source),
                        '-o', str(OUTPUT / name)], check=True)
    tools = ROOT / 'debug/arena-client/recovery-tools'
    sdk = tools / 'android-build-tools'
    classes, dex = OUTPUT / 'classes', OUTPUT / 'dex'
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)
    subprocess.run(['java', '-jar', str(tools / 'ecj-3.41.0.jar'), '-1.8', '-bootclasspath',
                    str(sdk / 'android.jar'), '-d', str(classes), str(HERE / 'Gate.java')], check=True)
    subprocess.run(['java', '-cp', str(sdk / 'd8.jar'), 'com.android.tools.r8.D8', '--lib',
                    str(sdk / 'android.jar'), '--min-api', '26', '--output', str(dex),
                    str(classes / 'dev/mr3a/checkpoint/Gate.class')], check=True)
    with zipfile.ZipFile(OUTPUT / 'gate-unaligned.jar', 'w') as archive:
        archive.write(dex / 'classes.dex', 'classes.dex')
    subprocess.run([str(sdk / 'zipalign'), '-f', '4', str(OUTPUT / 'gate-unaligned.jar'),
                    str(OUTPUT / 'gate.jar')], env=dict(os.environ, LD_LIBRARY_PATH=str(sdk)), check=True)
    inputs = ['Gate.java', 'game_gate.c', 'game_gate.lua', 'gate.py', 'java_transport.c', 'client_bootstrap.lua']
    manifest = dict(jni_source=JNI_URL, jni_sha256=JNI_SHA, modifies_apk=False,
                    source_sha256={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in inputs},
                    output_sha256={name: hashlib.sha256((OUTPUT / name).read_bytes()).hexdigest()
                                   for name in ('java-transport.so', 'game-gate.so', 'gate.jar')})
    (OUTPUT / 'build.json').write_text(json.dumps(manifest, indent=2))
    return OUTPUT


if __name__ == '__main__':
    print(build())
