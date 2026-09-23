"""Behavioural tests for the QTGMC fallback chain emitted into the VPY script.

The chain lives in ``_QTGMC_FALLBACK_BODY`` as generated source rather than as
importable functions, so it never runs in-process and no test or CI job had ever
executed it. These tests load the real template as a module and drive it against
stubs, covering the branches that only fire when a plugin, a QTGMC keyword or
fmtc is unavailable.
"""

import importlib
import importlib.util
import sys
import types

import pytest


def _load_fallback(tmp_path, qtgmc, bob=None):
    """Import the generated body as a module with ``haf`` and ``sys`` supplied.

    VapourSynth runs this code as a script, so importing it from a file is a
    closer match to production than evaluating the string would be.
    """
    vspipe = importlib.import_module("modules.runtime.vspipe")
    script = tmp_path / "qtgmc_fallback_body.py"
    script.write_text(getattr(vspipe, "_QTGMC_FALLBACK_BODY"), encoding="utf-8")

    spec = importlib.util.spec_from_file_location("qtgmc_fallback_body", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # The generated script resolves these from the VPY's own globals.
    module.haf = types.SimpleNamespace(QTGMC=qtgmc, Bob=bob if bob else (lambda *a, **k: "bob"))
    module.sys = sys
    return getattr(module, "_run_qtgmc_with_fallback"), getattr(module, "_run_bob_fallback")


def _recording_qtgmc(errors):
    """Return a QTGMC stub that raises each queued error once, then succeeds."""
    calls = []

    def qtgmc(_src_clip, **kwargs):
        calls.append(dict(kwargs))
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return "qtgmc"

    return qtgmc, calls


def test_qtgmc_retries_without_device_when_keyword_is_unsupported(tmp_path):
    """An older QTGMC that rejects 'device' is retried without it."""
    qtgmc, calls = _recording_qtgmc([TypeError("QTGMC() got an unexpected keyword argument 'device'")])
    run_with_fallback, _ = _load_fallback(tmp_path, qtgmc)

    result = run_with_fallback("clip", {"opencl": True, "device": 0})

    assert result == "qtgmc"
    assert "device" not in calls[1]


def test_qtgmc_unrelated_type_error_is_not_swallowed(tmp_path):
    """A TypeError that is not about 'device' propagates instead of retrying."""
    qtgmc, _ = _recording_qtgmc([TypeError("QTGMC() got an unexpected keyword argument 'Preset'")])
    run_with_fallback, _ = _load_fallback(tmp_path, qtgmc)

    with pytest.raises(TypeError):
        run_with_fallback("clip", {"device": 0})


@pytest.mark.parametrize("symbol", ["EEDI3CL", "NNEDI3CL"])
def test_qtgmc_disables_opencl_when_the_gpu_plugin_is_missing(tmp_path, symbol):
    """A missing OpenCL plugin retries on the CPU path with device dropped."""
    qtgmc, calls = _recording_qtgmc([ValueError(f"There is no function named {symbol}")])
    run_with_fallback, _ = _load_fallback(tmp_path, qtgmc)

    result = run_with_fallback("clip", {"opencl": True, "device": 0})

    assert result == "qtgmc"
    assert calls[1]["opencl"] is False
    assert "device" not in calls[1]


def test_qtgmc_drops_source_match_when_fmtc_is_unavailable(tmp_path):
    """A missing fmtc retries with the settings that depend on it disabled."""
    qtgmc, calls = _recording_qtgmc([ValueError("fmtc plugin not found")])
    run_with_fallback, _ = _load_fallback(tmp_path, qtgmc)

    result = run_with_fallback("clip", {"SourceMatch": 3, "Lossless": 2})

    assert result == "qtgmc"
    assert (calls[1]["SourceMatch"], calls[1]["Lossless"]) == (0, 0)


def test_qtgmc_falls_back_to_bob_on_an_unrecognised_failure(tmp_path, capsys):
    """An unrecognised failure degrades to Bob and says so on stderr."""
    qtgmc, _ = _recording_qtgmc([RuntimeError("something else entirely")])
    run_with_fallback, _ = _load_fallback(tmp_path, qtgmc)

    result = run_with_fallback("clip", {"TFF": True})

    assert result == "bob"
    assert "[QTGMC FALLBACK]" in capsys.readouterr().err


def test_qtgmc_falls_back_to_bob_when_every_retry_is_exhausted(tmp_path):
    """Repeated recoverable failures stop at the retry ceiling rather than looping."""
    qtgmc, calls = _recording_qtgmc([ValueError("fmtc plugin not found")] * 6)
    run_with_fallback, _ = _load_fallback(tmp_path, qtgmc)

    result = run_with_fallback("clip", {"SourceMatch": 3, "Lossless": 2})

    assert result == "bob"
    assert len(calls) == 4


def test_bob_fallback_uses_separate_fields_when_bob_itself_fails(tmp_path):
    """When haf.Bob is unavailable the clip's own field operations are used."""

    def failing_bob(*_args, **_kwargs):
        raise RuntimeError("Bob unavailable")

    weaved = types.SimpleNamespace(std=types.SimpleNamespace(DoubleWeave=lambda tff: f"weaved:{tff}"))
    clip = types.SimpleNamespace(std=types.SimpleNamespace(SeparateFields=lambda tff: weaved))
    _, run_bob = _load_fallback(tmp_path, lambda *a, **k: "qtgmc", bob=failing_bob)

    assert run_bob(clip, {"TFF": False}) == "weaved:False"
