#!/usr/bin/env python3
"""Recover client Lua assets with explicitly supplied local runtime key/IV files.

No process/device access and no key logging. AES-CBC + PKCS7 + GZip is the
observed LuaManager.CustomLoaderMethod pipeline for the recorded client.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
from arena_fidelity_assets import write_exact


def decode_lua(payload, key, iv, limit=64*1024*1024):
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    if len(key) not in (16,24,32) or len(iv)!=16:
        raise ValueError('Invalid AES key or IV length')
    if not payload or len(payload)%16 or len(payload)>limit:
        raise ValueError('Invalid encrypted Lua length')
    packed=unpad(AES.new(key,AES.MODE_CBC,iv).decrypt(payload),16)
    if not packed.startswith(b'\x1f\x8b'):
        raise ValueError('Decrypted payload is not GZip')
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
        plain=stream.read(limit+1)
    if len(plain)>limit:
        raise ValueError('Lua decompression exceeds limit')
    plain.decode('utf-8')
    return plain


def recover(input_dir,output,key,iv):
    files=sorted(input_dir.glob('*.lua.txt'))
    if not files:raise ValueError('No raw *.lua.txt assets found')
    report={'status':'lua_source_recovery_not_game_equivalence','decoded':[],'errors':[]}
    output.mkdir(parents=True,exist_ok=True)
    for source in files:
        try:
            encrypted=source.read_bytes();plain=decode_lua(encrypted,key,iv)
            name=source.name[:-4]
            row={'name':name,'source_sha256':hashlib.sha256(encrypted).hexdigest(),
                 **write_exact(output/name,plain)}
            report['decoded'].append(row)
        except Exception as exc:
            report['errors'].append({'name':source.name,'error':str(exc)})
    (output/'recovery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--key-file',type=Path,required=True)
    p.add_argument('--iv-file',type=Path,required=True)
    a=p.parse_args()
    r=recover(a.input_dir,a.output,a.key_file.read_bytes(),a.iv_file.read_bytes())
    print(json.dumps({'decoded':len(r['decoded']),'errors':len(r['errors'])}))
    if r['errors']:raise SystemExit(1)


if __name__=='__main__':main()
