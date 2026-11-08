#!/usr/bin/env python3
"""Preserve referenced Unity player GPU programs, including the newer schema.

Does not claim ShaderLab reconstruction or rendered-frame equivalence. Parameter
blobs must never be interpreted as GPU programs merely because they share a table.
"""

import argparse
import json
import re
import struct
from pathlib import Path
from arena_fidelity_assets import write_exact


def program_references(parsed):
    found = []
    for si, sub in enumerate(parsed.get("m_SubShaders", [])):
        for pi, pass_ in enumerate(sub.get("m_Passes", [])):
            for stage, program in pass_.items():
                if not stage.startswith("prog") or not isinstance(program, dict):
                    continue

                def visit(value):
                    if isinstance(value, dict):
                        if "m_BlobIndex" in value:
                            found.append(
                                {
                                    "subshader": si,
                                    "pass": pi,
                                    "stage": stage,
                                    "blob_index": value["m_BlobIndex"],
                                    "gpu_program_type": value.get("m_GpuProgramType"),
                                    "metadata": value,
                                }
                            )
                        else:
                            for x in value.values():
                                visit(x)
                    elif isinstance(value, list):
                        for x in value:
                            visit(x)

                visit(program.get("m_PlayerSubPrograms", []))
                visit(program.get("m_SubPrograms", []))
    return found


def stage_source(source, macro):
    """Unwrap exactly one outer stage guard; keep shader expressions unchanged."""
    lines = []
    active = False
    depth = 0
    for line in source.splitlines():
        text = line.strip()
        if not active:
            if text == "#ifdef " + macro:
                active = True
                depth = 1
            continue
        if re.match(r"#\s*(if|ifdef|ifndef)\b", text):
            depth += 1
        elif re.match(r"#\s*endif\b", text):
            depth -= 1
            if depth == 0:
                return "\n".join(lines) + "\n"
        lines.append(line)
    if active:
        raise ValueError("Unbalanced stage guard")
    return None


def referenced_programs(tree, version):
    from UnityPy.helpers import CompressionHelper
    from UnityPy.streams import EndianBinaryReader
    from UnityPy.export.ShaderConverter import ShaderSubProgram

    refs = program_references(tree["m_ParsedForm"])

    def entries(values):
        return values if isinstance(values, list) else [values]

    blob = bytes(tree["compressedBlob"])
    out = []
    for i, platform in enumerate(tree["platforms"]):
        segments = []
        for offset, size, plain_size in zip(
            entries(tree["offsets"][i]),
            entries(tree["compressedLengths"][i]),
            entries(tree["decompressedLengths"][i]),
            strict=True,
        ):
            if offset < 0 or size < 0 or offset + size > len(blob):
                raise ValueError("Compressed shader segment outside blob")
            segments.append(
                CompressionHelper.decompress_lz4(
                    blob[offset : offset + size], plain_size
                )
            )
        raw = segments[0]
        count = struct.unpack_from("<I", raw, 0)[0]
        if 4 + count * 12 > len(raw):
            raise ValueError("Invalid GPU program directory")
        for index in sorted({r["blob_index"] for r in refs}):
            if not 0 <= index < count:
                raise ValueError("Referenced GPU program absent")
            offset, length, segment = struct.unpack_from("<3I", raw, 4 + index * 12)
            if (
                not 0 <= segment < len(segments)
                or offset + length > len(segments[segment])
                or length < 32
            ):
                raise ValueError("GPU program outside segment")
            data = segments[segment][offset : offset + length]
            program = ShaderSubProgram(EndianBinaryReader(data, endian="<"))
            out.append(
                {
                    "platform": platform,
                    "blob_index": index,
                    "segment": segment,
                    "version": program.m_Version,
                    "gpu_program_type": int(program.m_ProgramType),
                    "keywords": program.m_Keywords,
                    "references": [r for r in refs if r["blob_index"] == index],
                    "raw_subprogram": data,
                    "code": program.m_ProgramCode,
                }
            )
    return out


def recover(serialized, output):
    import UnityPy

    env = UnityPy.load(str(serialized))
    report = {
        "status": "gpu_program_recovery_not_renderer_equivalence",
        "shaders": [],
        "errors": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    for obj in env.objects:
        if obj.type.name != "Shader":
            continue
        try:
            tree = obj.read_typetree()
            name = tree["m_ParsedForm"]["m_Name"]
            folder = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name) + "-" + str(obj.path_id)
            row = {"name": name, "path_id": obj.path_id, "programs": []}
            write_exact(
                output / folder / "shader-structure.json",
                (json.dumps(tree, ensure_ascii=True, indent=2) + "\n").encode(),
            )
            for program in referenced_programs(tree, obj.version):
                prefix = (
                    f"platform-{program['platform']}-program-{program['blob_index']}"
                )
                code = program.pop("code")
                raw = program.pop("raw_subprogram")
                program["code"] = write_exact(output / folder / (prefix + ".bin"), code)
                write_exact(output / folder / (prefix + ".subprogram"), raw)
                try:
                    source = code.decode("utf8").rstrip("\0")
                except UnicodeDecodeError:
                    source = None
                program["stages"] = []
                if source:
                    for macro, stage in [("VERTEX", "vert"), ("FRAGMENT", "frag")]:
                        stage_text = stage_source(source, macro)
                        if stage_text:
                            path = output / folder / (prefix + "." + stage)
                            write_exact(path, stage_text.encode())
                            program["stages"].append(
                                {"stage": stage, "file": str(path.relative_to(output))}
                            )
                row["programs"].append(program)
            report["shaders"].append(row)
        except Exception as exc:
            report["errors"].append({"path_id": obj.path_id, "error": str(exc)})
    (output / "recovery.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serialized", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    r = recover(a.serialized, a.output)
    print(
        json.dumps(
            {
                "shaders": len(r["shaders"]),
                "programs": sum(len(s["programs"]) for s in r["shaders"]),
                "errors": len(r["errors"]),
            }
        )
    )
    if r["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
