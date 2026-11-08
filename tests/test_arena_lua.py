"""Synthetic ciphertext only: do not commit game code or runtime keys."""
import gzip
from pathlib import Path
import sys
import pytest

pytest.importorskip('Crypto')
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_lua import decode_lua,recover
KEY=bytes(range(32));IV=bytes(range(16))


def encrypt(packed):return AES.new(KEY,AES.MODE_CBC,IV).encrypt(pad(packed,16))


def test_source_bytes_roundtrip_without_executing_lua():
    plain='-- 中文测试\r\nreturn {speed = 8}\n'.encode()
    assert decode_lua(encrypt(gzip.compress(plain)),KEY,IV)==plain


def test_bad_keys_padding_header_and_crc_are_rejected():
    source=encrypt(gzip.compress(b'return 1'))
    for data,key,iv in [(source,KEY[:3],IV),(source,KEY,IV[:2]),(source[:-1],KEY,IV),(source,bytes(32),IV),
                        (encrypt(b'not gzip'),KEY,IV)]:
        with pytest.raises(ValueError):decode_lua(data,key,iv)
    gz=bytearray(gzip.compress(b'return 1'));gz[-8]^=1
    with pytest.raises(OSError):decode_lua(encrypt(gz),KEY,IV)


def test_expansion_limit_is_enforced():
    with pytest.raises(ValueError,match='decompression exceeds'):
        decode_lua(encrypt(gzip.compress(b'a'*10000)),KEY,IV,limit=1000)


def test_conflicting_existing_sources_are_not_replaced(tmp_path):
    src=tmp_path/'input';src.mkdir();out=tmp_path/'output'
    (src/'Example.lua.txt').write_bytes(encrypt(gzip.compress(b'return 1')))
    assert not recover(src,out,KEY,IV)['errors']
    (src/'Example.lua.txt').write_bytes(encrypt(gzip.compress(b'return 2')))
    report=recover(src,out,KEY,IV)
    assert len(report['errors'])==1
    assert (out/'Example.lua').read_bytes()==b'return 1'
    assert KEY.hex() not in str(report)
    with pytest.raises(ValueError,match='No raw'):
        recover(tmp_path/'absent',out,KEY,IV)
