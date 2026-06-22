"""Runtime path resolution.

The launcher may switch cwd so Maa can resolve pipeline/resource-relative paths.
Python code should read paths from this module instead of assuming cwd directly.
"""

from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # agent/utils → agent → project root


@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    work_root: Path
    assets_dir: Path
    resource_dir: Path
    config_dir: Path
    deps_dir: Path


def build_runtime_paths(project_root=None, work_root=None):
    resolved_project_root = Path(project_root or _DEFAULT_PROJECT_ROOT).resolve()
    resolved_work_root = Path(work_root or resolved_project_root).resolve()
    return RuntimePaths(
        project_root=resolved_project_root,
        work_root=resolved_work_root,
        assets_dir=resolved_project_root / "assets",
        resource_dir=resolved_work_root / "resource",
        config_dir=resolved_work_root / "config",
        deps_dir=resolved_project_root / "deps",
    )


_runtime_paths = build_runtime_paths()


def configure_runtime_paths(project_root=None, work_root=None):
    global _runtime_paths
    _runtime_paths = build_runtime_paths(project_root=project_root, work_root=work_root)
    return _runtime_paths


def get_runtime_paths():
    return _runtime_paths
