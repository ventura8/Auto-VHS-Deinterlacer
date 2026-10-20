"""Tests for install.sh's build_nnedi3cl step.

Verifies SHA-256 integrity verification for VapourSynth API3 compatibility
headers (VapourSynth.h and VSHelper.h), commit SHA pinning for the NNEDI3CL
plugin repository, and version checking.
"""

import hashlib
import importlib
import re
import subprocess
from pathlib import Path

import pytest

_HELPERS = importlib.import_module("tests.unit.test_runtime_helpers")
_POSIX_BASH = getattr(_HELPERS, "POSIX_BASH")
_READ_INSTALL_SH = getattr(_HELPERS, "_read_install_sh")
_EXTRACT_SHELL_FUNCTION = getattr(_HELPERS, "_extract_shell_function")
_BASH_PATH = getattr(_HELPERS, "_bash_path")
NNEDI3CL_COMMIT = getattr(_HELPERS, "NNEDI3CL_COMMIT")

pytestmark = pytest.mark.skipif(
    _POSIX_BASH is None,
    reason="requires a POSIX bash (no Git Bash or system bash found)",
)


def _apply_pin_overrides(fn_text: str, pin_overrides: tuple[str, str, str] | None) -> str:
    """Substitute header SHA-256 and commit SHA pins in the shell function text."""
    if pin_overrides is None:
        return fn_text
    vs_h_pin, helper_pin, commit_pin = pin_overrides
    fn_text = re.sub(
        r'VAPOURSYNTH_H_EXPECTED_SHA256="[0-9a-f]{64}"',
        f'VAPOURSYNTH_H_EXPECTED_SHA256="{vs_h_pin}"',
        fn_text,
    )
    fn_text = re.sub(
        r'VSHELPER_H_EXPECTED_SHA256="[0-9a-f]{64}"',
        f'VSHELPER_H_EXPECTED_SHA256="{helper_pin}"',
        fn_text,
    )
    return re.sub(r'NNEDI3CL_COMMIT="[0-9a-f]{40}"', f'NNEDI3CL_COMMIT="{commit_pin}"', fn_text)


def _generate_shell_stubs(
    tmp_path: Path,
    build_dir: Path,
    checkout_commit: str,
    meson_ok: bool,
    vs_has_ok: bool,
) -> str:
    """Generate shell stub functions for curl, git, meson, ninja, and vs_has."""
    mirror = tmp_path / "mirror"
    curl_log = tmp_path / "curl.log"
    git_log = tmp_path / "git.log"
    meson_log = tmp_path / "meson.log"
    ninja_log = tmp_path / "ninja.log"
    meson_rc = "0" if meson_ok else "1"
    vs_has_rc = "0" if vs_has_ok else "1"
    return (
        "curl() {\n"
        '    url="${@: -3:1}"; dest="${@: -1}"\n'
        f'    echo "$url" >> "{_BASH_PATH(curl_log)}"\n'
        '    hdr="$(basename "$url")"\n'
        f'    src="{_BASH_PATH(mirror)}/$hdr"\n'
        '    [ -f "$src" ] || return 22\n'
        '    cp "$src" "$dest"\n'
        "}\n"
        "git() {\n"
        f'    echo "git $@" >> "{_BASH_PATH(git_log)}"\n'
        '    if [ "$1" = "clone" ]; then\n'
        '        dest="$3"\n'
        '        mkdir -p "$dest/build" "$dest/NNEDI3CL"\n'
        '        touch "$dest/NNEDI3CL/nnedi3_weights.bin"\n'
        "        return 0\n"
        '    elif [ "$1" = "-C" ] && [ "$3" = "checkout" ]; then\n'
        "        return 0\n"
        '    elif [ "$1" = "-C" ] && [ "$3" = "rev-parse" ]; then\n'
        f'        echo "{checkout_commit}"\n'
        "        return 0\n"
        "    fi\n"
        "    return 0\n"
        "}\n"
        "meson() {\n"
        f'    echo "meson $@" >> "{_BASH_PATH(meson_log)}"\n'
        f"    return {meson_rc}\n"
        "}\n"
        "ninja() {\n"
        f'    echo "ninja $@" >> "{_BASH_PATH(ninja_log)}"\n'
        f'    touch "{_BASH_PATH(build_dir)}/nnedi3cl/build/libnnedi3cl.so"\n'
        "    return 0\n"
        "}\n"
        "vs_has() {\n"
        f"    return {vs_has_rc}\n"
        "}\n"
    )


def _run_nnedi3cl_build(
    tmp_path: Path,
    *,
    vs_ver: str = "79",
    headers: dict[str, bytes] | None = None,
    checkout_commit: str = NNEDI3CL_COMMIT,
    pin_overrides: tuple[str, str, str] | None = None,
    meson_ok: bool = True,
    vs_has_ok: bool = True,
):
    """Execute install.sh's build_nnedi3cl() in an isolated environment with stubbed tools."""
    script = _READ_INSTALL_SH()
    fn_text = _apply_pin_overrides(_EXTRACT_SHELL_FUNCTION(script, "build_nnedi3cl"), pin_overrides)
    sha_fn = _EXTRACT_SHELL_FUNCTION(script, "sha256_of")

    mirror = tmp_path / "mirror"
    mirror.mkdir(parents=True, exist_ok=True)
    header_data = headers or {
        "VapourSynth.h": b"/* VapourSynth.h */\n",
        "VSHelper.h": b"/* VSHelper.h */\n",
    }
    for hname, hdata in header_data.items():
        (mirror / hname).write_bytes(hdata)

    build_dir = tmp_path / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    native_file = tmp_path / "native.ini"
    native_file.write_text("[binaries]\n", encoding="utf-8")

    stubs = _generate_shell_stubs(
        tmp_path,
        build_dir,
        checkout_commit,
        meson_ok,
        vs_has_ok,
    )
    fake_python = tmp_path / "fake_python"
    fake_python.write_text(f'#!/bin/sh\necho "{vs_ver}"\n', encoding="utf-8")
    fake_python.chmod(0o755)

    driver = (
        "set -u\n"
        f"{sha_fn}\n"
        f"{stubs}\n"
        f"{fn_text}\n"
        f'VENV_PYTHON="{_BASH_PATH(fake_python)}"\n'
        f'build_nnedi3cl "{_BASH_PATH(build_dir)}" "{_BASH_PATH(native_file)}" "{_BASH_PATH(plugin_dir)}"\n'
    )
    result = subprocess.run([_POSIX_BASH, "-c", driver], capture_output=True, text=True, check=False)
    return result, plugin_dir, build_dir, tmp_path / "meson.log"


def _assert_build_artifacts_present(result, plugin_dir, meson_log):
    """Verify that build artifacts exist and output indicates successful installation."""
    status = (
        result.returncode,
        meson_log.exists(),
        (plugin_dir / "libnnedi3cl.so").exists(),
        (plugin_dir / "nnedi3_weights.bin").exists(),
        "GPU QTGMC interpolation available" in result.stdout,
    )
    assert status == (0, True, True, True, True), result.stderr


def _assert_header_rejection_clean(result, plugin_dir, build_dir, meson_log):
    """Verify that a corrupted header aborts compilation and cleans up temporary files."""
    output = result.stdout + result.stderr
    status = (
        result.returncode != 0,
        meson_log.exists(),
        (plugin_dir / "libnnedi3cl.so").exists(),
        (build_dir / "api3" / "VapourSynth.h").exists(),
        "SHA-256 mismatch" in output,
        "Refusing to compile with unverified VapourSynth API3 headers" in output,
    )
    assert status == (True, False, False, False, True, True)


def test_build_nnedi3cl_accepts_matching_headers_and_commit(tmp_path):
    """When API3 headers match pinned digests and git checkout matches commit SHA, build succeeds."""
    headers = {
        "VapourSynth.h": b"/* valid VapourSynth.h */\n",
        "VSHelper.h": b"/* valid VSHelper.h */\n",
    }
    pins = (
        hashlib.sha256(headers["VapourSynth.h"]).hexdigest(),
        hashlib.sha256(headers["VSHelper.h"]).hexdigest(),
        NNEDI3CL_COMMIT,
    )

    result, plugin_dir, _, meson_log = _run_nnedi3cl_build(
        tmp_path,
        headers=headers,
        pin_overrides=pins,
    )
    _assert_build_artifacts_present(result, plugin_dir, meson_log)


def test_build_nnedi3cl_rejects_header_digest_mismatch(tmp_path):
    """When an API3 header hash does not match, it is deleted and compilation is refused."""
    headers = {
        "VapourSynth.h": b"/* tampered VapourSynth.h */\n",
        "VSHelper.h": b"/* valid VSHelper.h */\n",
    }
    pins = (
        "0000000000000000000000000000000000000000000000000000000000000000",
        hashlib.sha256(headers["VSHelper.h"]).hexdigest(),
        NNEDI3CL_COMMIT,
    )

    result, plugin_dir, build_dir, meson_log = _run_nnedi3cl_build(
        tmp_path,
        headers=headers,
        pin_overrides=pins,
    )
    _assert_header_rejection_clean(result, plugin_dir, build_dir, meson_log)


def test_build_nnedi3cl_rejects_commit_mismatch(tmp_path):
    """When git checkout does not match the reviewed commit SHA, compilation is refused."""
    headers = {
        "VapourSynth.h": b"/* valid VapourSynth.h */\n",
        "VSHelper.h": b"/* valid VSHelper.h */\n",
    }
    pins = (
        hashlib.sha256(headers["VapourSynth.h"]).hexdigest(),
        hashlib.sha256(headers["VSHelper.h"]).hexdigest(),
        NNEDI3CL_COMMIT,
    )

    result, plugin_dir, _, meson_log = _run_nnedi3cl_build(
        tmp_path,
        headers=headers,
        checkout_commit="badbadbadbadbadbadbadbadbadbadbadbadbadb",
        pin_overrides=pins,
    )

    assert result.returncode != 0
    assert not meson_log.exists()
    assert not (plugin_dir / "libnnedi3cl.so").exists()


def test_build_nnedi3cl_rejects_wrong_vs_version(tmp_path):
    """When VapourSynth is not R79, build_nnedi3cl skips without downloading or compiling."""
    result, _, _, meson_log = _run_nnedi3cl_build(tmp_path, vs_ver="80")

    assert result.returncode != 0
    assert not meson_log.exists()
    output = result.stdout + result.stderr
    assert "expected VapourSynth R79 for API3 headers, found R80" in output
