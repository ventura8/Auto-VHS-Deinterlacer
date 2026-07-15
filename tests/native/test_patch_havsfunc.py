"""Unit tests for havsfunc patching helpers."""

from unittest.mock import mock_open, patch

import pytest

from modules.core import patch_havsfunc


def test_patch_havsfunc_path_uses_workspace_venv():
    """Resolve havsfunc.py under the workspace .VENV directory."""
    with patch("modules.core.patch_havsfunc.get_project_root", return_value="C:/repo"):
        path_value = getattr(patch_havsfunc, "_get_havsfunc_path")()

    assert path_value.replace("\\", "/") == "C:/repo/.VENV/Lib/site-packages/havsfunc.py"


def _run_patch_havsfunc_main(original: str) -> str:
    """Execute the patcher against in-memory file content and return the written text."""
    m_open = mock_open(read_data=original)
    with (
        patch("modules.core.patch_havsfunc.os.path.exists", return_value=True),
        patch("builtins.open", m_open),
        patch("builtins.print"),
    ):
        patch_havsfunc.main()
    return "".join(call.args[0] for call in m_open().write.call_args_list)


def _assert_limited_qtgmc_patches(written: str):
    """Check that only the QTGMC functions receive device patches."""
    expected_fragments = (
        "def helper(opencl=False):\n    myNNEDI3 = core.nnedi3cl.NNEDI3CL\n    return MatchEnhance, TFF, opencl)",
        "def helper2(a, opencl):\n    return TFF=TFF, opencl=opencl)",
        "def QTGMC(opencl=False, device=0):",
        "def QTGMC_Interpolate(opencl=False, device=0):",
        "myNNEDI3 = functools.partial(core.nnedi3cl.NNEDI3CL, device=device)",
        "myEEDI3 = functools.partial(core.eedi3m.EEDI3CL, device=device)",
    )
    for fragment in expected_fragments:
        assert fragment in written


def test_patch_havsfunc_missing_file_exits_cleanly():
    """Exit successfully and print information when the target file is missing."""
    with (
        patch("modules.core.patch_havsfunc.os.path.exists", return_value=False),
        patch("modules.core.patch_havsfunc.sys.exit", side_effect=SystemExit(0)) as mock_exit,
        patch("builtins.print") as mock_print,
        pytest.raises(SystemExit),
    ):
        patch_havsfunc.main()

    mock_exit.assert_called_once_with(0)
    assert mock_print.called


def test_patch_havsfunc_applies_replacements_and_writes():
    """Apply the baseline compatibility replacements."""
    original = (
        "vs.get_core()\n"
        "f(a, _global = x)\n"
        "g(a, _lambda = y)\n"
        "def QTGMC(opencl=False):\n"
        "    return TFF, opencl)\n"
        "def QTGMC_Interpolate(opencl=False):\n"
        "    myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "    tmp = 0\n"
        "    myEEDI3 = core.eedi3m.EEDI3CL\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "def helper(a, opencl):\n"
        "    return TFF, opencl)\n"
        "def helper2():\n"
        "    return TFF=TFF, opencl=opencl)\n"
        "def helper3():\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "myEEDI3 = core.eedi3m.EEDI3CL\n"
    )
    written = _run_patch_havsfunc_main(original)
    assert "vs.core" in written
    assert "_global" not in written
    assert "_lambda" not in written
    assert "device=0" in written


def test_patch_havsfunc_applies_opencl_device_wrappers():
    """Apply device-aware OpenCL wrapper replacements in the legacy block."""
    original = (
        "vs.get_core()\n"
        "f(a, _global = x)\n"
        "g(a, _lambda = y)\n"
        "def QTGMC(opencl=False):\n"
        "    return TFF, opencl)\n"
        "def QTGMC_Interpolate(opencl=False):\n"
        "    myNNEDI3=core.nnedi3cl.NNEDI3CL\n"
        "    tmp = 0\n"
        "    myEEDI3\t=\tcore.eedi3m.EEDI3CL\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "def helper(a, opencl):\n"
        "    return TFF, opencl)\n"
        "def helper2():\n"
        "    return TFF=TFF, opencl=opencl)\n"
        "def helper3():\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "myEEDI3 = core.eedi3m.EEDI3CL\n"
    )

    written = _run_patch_havsfunc_main(original)
    assert "myNNEDI3=functools.partial(core.nnedi3cl.NNEDI3CL, device=device)" in written
    assert "myEEDI3\t=\tfunctools.partial(core.eedi3m.EEDI3CL, device=device)" in written


def test_patch_havsfunc_limits_device_patches_to_qtgmc_functions():
    """Leave unrelated helper functions unchanged even when they use matching opencl text."""
    original = (
        "vs.get_core()\n"
        "def helper(opencl=False):\n"
        "    myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "def QTGMC(opencl=False):\n"
        "    return TFF, opencl)\n"
        "def QTGMC_Interpolate(opencl=False):\n"
        "    myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "    myEEDI3 = core.eedi3m.EEDI3CL\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "def helper2(a, opencl):\n"
        "    return TFF=TFF, opencl=opencl)\n"
        "myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "myEEDI3 = core.eedi3m.EEDI3CL\n"
    )

    written = _run_patch_havsfunc_main(original)
    _assert_limited_qtgmc_patches(written)


def test_patch_havsfunc_direct_functools_import_requires_top_level_binding():
    """Only a top-level plain import functools should satisfy the generated patch guard."""
    has_direct_import = getattr(patch_havsfunc, "_has_direct_functools_import")

    assert has_direct_import("import functools\n") is True
    assert has_direct_import("import os, functools\n") is True
    assert has_direct_import("    import functools\n") is False
    assert has_direct_import("import functools as ft\n") is False


def test_patch_havsfunc_replace_text_success_path():
    """Replace-text helper should report one successful substitution."""
    updated, count = getattr(patch_havsfunc, "_replace_text")("foo", "demo", "foo", "bar")
    assert updated == "bar"
    assert count == 1


def test_patch_havsfunc_replace_text_warning_path():
    """Replace-text helper should warn when a target is missing."""
    with patch("builtins.print") as mock_print:
        unchanged, count = getattr(patch_havsfunc, "_replace_text")("foo", "missing", "zzz", "bar")
    assert unchanged == "foo"
    assert count == 0
    assert mock_print.called


def test_patch_havsfunc_replace_text_required_path():
    """Replace-text helper should raise on missing required targets."""
    with pytest.raises(RuntimeError):
        getattr(patch_havsfunc, "_replace_text")("foo", "required", "zzz", "bar", required=True)


def test_patch_havsfunc_replace_regex_success_path():
    """Replace-regex helper should report one successful substitution."""
    updated_regex, count_regex = getattr(patch_havsfunc, "_replace_regex")("ab12", "rx", r"\d+", "")
    assert updated_regex == "ab"
    assert count_regex == 1


def test_patch_havsfunc_replace_regex_warning_path():
    """Replace-regex helper should warn when a target is missing."""
    with patch("builtins.print") as mock_print:
        unchanged_regex, count_regex = getattr(patch_havsfunc, "_replace_regex")("ab", "missing_rx", r"\d+", "")
    assert unchanged_regex == "ab"
    assert count_regex == 0
    assert mock_print.called


def test_patch_havsfunc_replace_regex_required_path():
    """Replace-regex helper should raise on missing required targets."""
    with pytest.raises(RuntimeError):
        getattr(patch_havsfunc, "_replace_regex")("ab", "required_rx", r"\d+", "", required=True)


def test_patch_havsfunc_handles_multiline_docstring_and_future_import_insertion():
    """Insert functools import after a module docstring and future imports."""
    original = (
        "#!/usr/bin/env python\n"
        '"""module doc\n'
        "still doc\n"
        '"""\n'
        "from __future__ import annotations\n"
        "# keep grouped future imports\n"
        "\n"
        "from __future__ import division\n"
        "\n"
        "# another comment inside the block\n"
        "\n"
        "from __future__ import print_function\n"
        "vs.get_core()\n"
        "def QTGMC(opencl=False):\n"
        "    return TFF, opencl)\n"
        "def QTGMC_Interpolate(opencl=False):\n"
        "    myNNEDI3 = core.nnedi3cl.NNEDI3CL\n"
        "    myEEDI3 = core.eedi3m.EEDI3CL\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "def helper2():\n"
        "    return TFF=TFF, opencl=opencl)\n"
        "def helper3():\n"
        "    return MatchEnhance, TFF, opencl)\n"
        "    return 1\n"
    )
    m_open = mock_open(read_data=original)

    with (
        patch("modules.core.patch_havsfunc.os.path.exists", return_value=True),
        patch("builtins.open", m_open),
        patch("builtins.print"),
    ):
        patch_havsfunc.main()

    written = "".join(call.args[0] for call in m_open().write.call_args_list)
    assert "import functools" in written
    assert written.index("from __future__ import print_function") < written.index("import functools")
    assert written.index("import functools") < written.index("vs.core")


def test_patch_havsfunc_skips_legacy_block_when_device_already_present():
    """Skip legacy patch section when device argument already exists."""
    original = "import functools\ndef QTGMC(opencl=False, device=0):\n    return 1\n"
    m_open = mock_open(read_data=original)

    with (
        patch("modules.core.patch_havsfunc.os.path.exists", return_value=True),
        patch("builtins.open", m_open),
        patch("builtins.print") as mock_print,
    ):
        patch_havsfunc.main()

    printed_messages = [call.args[0] for call in mock_print.call_args_list]
    assert any("skipping legacy device patch block" in msg for msg in printed_messages)
    assert any("Patched havsfunc.py" in msg for msg in printed_messages)


def test_patch_havsfunc_legacy_signature_stage_requires_each_function():
    """Rollback legacy patch when signature stage is incomplete for either target function."""
    original = (
        "def QTGMC(opencl=False):\n"
        "    return TFF, opencl)\n"
        "def QTGMC_Interpolate(opencl=False, device=0):\n"
        "    return MatchEnhance, TFF, opencl)\n"
    )

    patched = getattr(patch_havsfunc, "_apply_device_signature_patches")(original)

    assert patched == original


def test_patch_havsfunc_legacy_propagation_stage_requires_each_function():
    """Rollback legacy patch when propagation stage is incomplete for either function."""
    original = "".join(
        [
            "def QTGMC(opencl=False):\n",
            "    return TFF, opencl)\n",
            "def QTGMC_Interpolate(opencl=False):\n",
            "    return 1\n",
        ]
    )

    patched = getattr(patch_havsfunc, "_apply_device_signature_patches")(original)

    assert patched == original
