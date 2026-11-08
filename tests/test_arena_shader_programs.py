"""New player-program schema must not be mistaken for empty GPU source."""

from pathlib import Path
import sys
import struct
import pytest

pytest.importorskip("UnityPy")
from UnityPy.helpers import CompressionHelper

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from arena_shader_programs import program_references, stage_source, referenced_programs


def test_new_player_references_exclude_parameter_blobs_and_keep_variants():
    parsed = {
        "m_SubShaders": [
            {
                "m_Passes": [
                    {
                        "progVertex": {
                            "m_SubPrograms": [],
                            "m_PlayerSubPrograms": [
                                [],
                                [{"m_BlobIndex": 1, "m_GpuProgramType": 4}],
                            ],
                            "m_ParameterBlobIndices": [[0]],
                            "m_CommonParameters": {"m_BlobIndex": 0},
                        }
                    }
                ]
            }
        ]
    }
    refs = program_references(parsed)
    assert [r["blob_index"] for r in refs] == [1]
    assert refs[0]["stage"] == "progVertex"


def test_stage_guards_preserve_nested_preprocessor_and_program_expression():
    src = "#ifdef VERTEX\n#version 300 es\n#if FLAG\nvec4 x;\n#endif\n#endif\n#ifdef FRAGMENT\nvoid main() {}\n#endif\n"
    assert stage_source(src, "VERTEX") == "#version 300 es\n#if FLAG\nvec4 x;\n#endif\n"
    assert stage_source(src, "FRAGMENT") == "void main() {}\n"
    assert stage_source(src, "GEOMETRY") is None
    with pytest.raises(ValueError, match="Unbalanced"):
        stage_source("#ifdef VERTEX\nhello", "VERTEX")


def test_only_referenced_program_is_read_from_shared_code_parameter_directory():
    code = b"#ifdef VERTEX\n#version 300 es\nvoid main(){}\n#endif\n"
    payload = struct.pack("<8i", 202012090, 4, 0, 0, 0, 0, 0, len(code)) + code
    payload += b"\0" * (-len(payload) % 4)
    # Entry zero deliberately is not a ShaderSubProgram.
    raw = struct.pack("<I6I", 2, 28, 4, 0, 32, len(payload), 0) + b"PARM" + payload
    compressed = CompressionHelper.compress_lz4(raw)
    parsed = {
        "m_SubShaders": [
            {
                "m_Passes": [
                    {
                        "progVertex": {
                            "m_PlayerSubPrograms": [
                                [{"m_BlobIndex": 1, "m_GpuProgramType": 4}]
                            ]
                        }
                    }
                ]
            }
        ]
    }
    tree = {
        "m_ParsedForm": parsed,
        "platforms": [9],
        "offsets": [[0]],
        "compressedLengths": [[len(compressed)]],
        "decompressedLengths": [[len(raw)]],
        "compressedBlob": list(compressed),
    }
    programs = referenced_programs(tree, (2022, 3, 62, 2))
    assert len(programs) == 1 and programs[0]["code"] == code
    assert programs[0]["blob_index"] == 1
    tree["m_ParsedForm"]["m_SubShaders"][0]["m_Passes"][0]["progVertex"][
        "m_PlayerSubPrograms"
    ][0][0]["m_BlobIndex"] = 2
    with pytest.raises(ValueError, match="absent"):
        referenced_programs(tree, (2022, 3, 62, 2))
