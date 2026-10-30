"""Regression tests: modules planted in a per-video workspace must never be imported.

vspipe evaluates ``restore.vpy`` with the script folder (the workspace next to
the source video) as its working directory, so a ``havsfunc.py`` planted there
would shadow the venv copy unless the generated ``sys.path`` header excludes it.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.runtime import workspace as ws_module

vspipe = importlib.import_module("modules.runtime.vspipe")
_collect_trusted_vpy_paths = getattr(vspipe, "_collect_trusted_vpy_paths")
_get_vpy_sys_path_lines = getattr(vspipe, "_get_vpy_sys_path_lines")

PLANTED_MODULE = "from pathlib import Path\nPath('pwned.marker').write_text('x')\nORIGIN = 'planted'\n"
TRUSTED_MODULE = "ORIGIN = 'trusted'\n"


def _build_layout(tmp_path: Path):
    """Create a trusted site-packages copy and an attacker-planted workspace copy."""
    project_root = tmp_path / "app"
    site_packages = project_root / ".venv" / "lib" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "havsfunc.py").write_text(TRUSTED_MODULE, encoding="utf-8")

    source = tmp_path / "videos" / "tape.mp4"
    source.parent.mkdir()
    source.write_bytes(b"source")
    workspace = ws_module.build_workspace(source, source.with_name("tape_out.mov"))
    workspace.root.mkdir()
    (workspace.root / "havsfunc.py").write_text(PLANTED_MODULE, encoding="utf-8")
    return project_root, site_packages, workspace


def _run_in_workspace(workspace_root: Path, code: str) -> subprocess.CompletedProcess:
    """Run ``code`` like vspipe does: with the script folder as working directory."""
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSAFEPATH"}}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=workspace_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _render_header(project_root: Path, site_packages: Path, workspace_root: Path) -> str:
    """Render the generated sys.path header followed by the havsfunc import."""
    trusted = _collect_trusted_vpy_paths(project_root.as_posix(), [site_packages.as_posix()], (project_root / ".venv/vs").as_posix())
    lines = ["import sys", "import os"]
    lines += [f"sys.path.append({str(workspace_root)!r})"]
    lines += _get_vpy_sys_path_lines(trusted, workspace_root.as_posix())
    lines += ["import havsfunc", "print(havsfunc.ORIGIN)"]
    return "\n".join(lines)


def test_planted_module_shadows_venv_without_isolation(tmp_path):
    """Control case: with the old append-only header the planted module wins."""
    _, site_packages, workspace = _build_layout(tmp_path)
    code = f"import sys\nsys.path.append({str(site_packages)!r})\nimport havsfunc\nprint(havsfunc.ORIGIN)"

    result = _run_in_workspace(workspace.root, code)

    assert result.stdout.strip() == "planted"


def test_generated_header_imports_venv_havsfunc_from_planted_workspace(tmp_path):
    """The generated header resolves havsfunc from site-packages, never the workspace."""
    project_root, site_packages, workspace = _build_layout(tmp_path)

    result = _run_in_workspace(workspace.root, _render_header(project_root, site_packages, workspace.root))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "trusted"
    assert not (workspace.root / "pwned.marker").exists()


def test_collect_trusted_vpy_paths_orders_roots_and_skips_missing_mvsfunc(tmp_path):
    """Trusted roots keep their order, drop duplicates and add mvsfunc only when present."""
    root = tmp_path.as_posix()

    assert _collect_trusted_vpy_paths(root, ["/site", "/site"], "/vs") == [root, "/site", "/vs"]
    (tmp_path / "mvsfunc").mkdir()
    assert _collect_trusted_vpy_paths(root, ["/site"], "/vs") == [root, "/site", "/vs", f"{root}/mvsfunc"]


def test_create_vpy_script_header_excludes_workspace(tmp_path):
    """The real generated script never puts its own folder on sys.path."""
    workspace_root = tmp_path / "tape.mp4.autovhs-tmp"
    workspace_root.mkdir()
    script = workspace_root / "restore.vpy"
    settings = {"cpu_threads": 2, "ram_cache_mb": 512, "use_gpu_opencl": False, "gpu_device_index": 0}

    # get_fps shells out to ffprobe, an external boundary.
    with patch("modules.runtime.vspipe.get_fps", return_value=25.0):
        vspipe.create_vpy_script(str(tmp_path / "tape.mp4"), str(script), "QTGMC", override_settings=settings)

    content = script.read_text(encoding="utf-8")
    header = content.split("import havsfunc as haf", 1)[0]
    assert "sys.path.insert(" not in header
    assert "sys.path.append(" not in header
    assert "_UNTRUSTED_DIRS" in header
    assert repr(workspace_root.as_posix()) in header


def test_prepare_workspace_removes_planted_entries(tmp_path):
    """Foreign files, folders and symlinks in the workspace root are deleted on prepare."""
    _, _, workspace = _build_layout(tmp_path)
    (workspace.root / "__pycache__").mkdir()
    (workspace.root / "__pycache__" / "havsfunc.cpython-312.pyc").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    workspace.segments_dir.symlink_to(outside, target_is_directory=True)
    workspace.state_file.write_text("{}", encoding="utf-8")
    workspace.script.write_text("old", encoding="utf-8")

    ws_module.prepare_workspace(workspace)

    names = sorted(path.name for path in workspace.root.iterdir())
    assert names == ["index", "restore.vpy", "segments", "state.json"]
    assert not workspace.segments_dir.is_symlink()
    assert (outside / "keep.txt").exists()


def test_prepare_workspace_replaces_symlinked_root(tmp_path):
    """A workspace root that is a symlink is replaced by a real folder."""
    _, _, workspace = _build_layout(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    workspace.root.rename(elsewhere)
    workspace.root.symlink_to(elsewhere, target_is_directory=True)

    ws_module.prepare_workspace(workspace)

    assert workspace.root.is_dir() and not workspace.root.is_symlink()
    assert (elsewhere / "havsfunc.py").exists()
    assert sorted(path.name for path in workspace.root.iterdir()) == ["index", "segments"]


def test_remove_foreign_entries_ignores_missing_root(tmp_path):
    """Nothing happens when the workspace does not exist yet."""
    source = tmp_path / "tape.mp4"
    workspace = ws_module.build_workspace(source, tmp_path / "out.mov")

    ws_module.remove_foreign_entries(workspace)

    assert not workspace.root.exists()


def test_native_runner_does_not_add_script_folder_to_sys_path(tmp_path, monkeypatch):
    """The native fallback executes the script without extending sys.path."""
    monkeypatch.setitem(sys.modules, "vapoursynth", SimpleNamespace(VideoNode=object, VideoOutputTuple=tuple))
    native = importlib.reload(importlib.import_module("modules.runtime.vspipe_native"))
    script = tmp_path / "restore.vpy"
    script.write_text("VALUE = 1\n", encoding="utf-8")
    before = list(sys.path)

    getattr(native, "_run_vpy_script")(str(script))

    assert sys.path == before
    sys.modules.pop("modules.runtime.vspipe_native", None)


@pytest.mark.parametrize("entry", ["", "."])
def test_header_drops_relative_entries(tmp_path, entry):
    """Relative sys.path entries resolve to the working folder and are dropped."""
    project_root, site_packages, workspace = _build_layout(tmp_path)
    header = _render_header(project_root, site_packages, workspace.root)
    code = header.replace("import sys\n", f"import sys\nsys.path.insert(0, {entry!r})\n", 1)
    code = code.replace("import havsfunc", f"print({entry!r} in sys.path)\nimport havsfunc", 1)

    result = _run_in_workspace(workspace.root, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["False", "trusted"]


def test_prepare_workspace_treats_junctions_as_links(tmp_path):
    """A Windows junction standing in for an owned folder is removed, not followed."""
    _, _, workspace = _build_layout(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    # Junctions only exist on NTFS. Emulate one with a directory symlink that,
    # like a junction, reports is_symlink() False and is_junction() True.
    workspace.index_dir.symlink_to(outside, target_is_directory=True)
    real_is_symlink, real_is_junction = Path.is_symlink, Path.is_junction

    def fake_is_symlink(path):
        return path != workspace.index_dir and real_is_symlink(path)

    def fake_is_junction(path):
        return (path == workspace.index_dir and real_is_symlink(path)) or real_is_junction(path)

    with patch.object(Path, "is_symlink", fake_is_symlink), patch.object(Path, "is_junction", fake_is_junction):
        ws_module.prepare_workspace(workspace)

    assert workspace.index_dir.is_dir() and not workspace.index_dir.is_symlink()
    assert (outside / "keep.txt").exists()


def test_prepare_workspace_stops_when_foreign_entry_cannot_be_removed(tmp_path):
    """A planted file that cannot be deleted aborts preparation instead of continuing."""
    _, _, workspace = _build_layout(tmp_path)

    with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
        with pytest.raises(PermissionError):
            ws_module.prepare_workspace(workspace)

    assert (workspace.root / "havsfunc.py").exists()
    assert not workspace.segments_dir.exists()
