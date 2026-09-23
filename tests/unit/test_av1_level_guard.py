"""Tests for the AV1 level guard and the pinned av1_nvenc level.

A real 5090 encode produced seq_level_idx 23 (AV1 level 7.3) for a 720x480
source because av1_nvenc was left to pick its own level. The AV1 spec does not
define the 7.x levels, so libaom refused the bitstream while dav1d accepted it.
The E2E suite missed it because it only read the container and stream header.
"""

import importlib

import pytest


def test_av1_nvenc_args_pin_a_level():
    """The NVENC argument list must pin a level rather than let the encoder choose."""
    encoders = importlib.import_module("modules.runtime.encoders")
    args = list(getattr(encoders, "AV1_NVENC_ARGS"))

    assert "-level" in args
    assert args[args.index("-level") + 1] == getattr(encoders, "AV1_NVENC_LEVEL")


def test_pinned_nvenc_level_is_one_the_spec_defines():
    """The pinned level must sit inside the range decoders actually implement."""
    encoders = importlib.import_module("modules.runtime.encoders")
    conftest = importlib.import_module("tests.e2e.conftest")

    major, minor = (int(part) for part in getattr(encoders, "AV1_NVENC_LEVEL").split("."))
    seq_level_idx = (major - 2) * 4 + minor

    assert seq_level_idx <= getattr(conftest, "AV1_MAX_DEFINED_SEQ_LEVEL_IDX")


@pytest.mark.parametrize(
    ("level", "should_pass"),
    [
        ("13", True),  # 5.1, the pinned level
        ("19", True),  # 6.3, the highest the spec defines
        ("23", False),  # 7.3, what av1_nvenc emitted unpinned
        ("", False),  # ffprobe could not report one
    ],
)
def test_av1_level_guard_rejects_undefined_levels(monkeypatch, level, should_pass):
    """The guard accepts defined levels and rejects the undefined 7.x range."""
    conftest = importlib.import_module("tests.e2e.conftest")
    monkeypatch.setattr(conftest, "probe_stream_entry", lambda _path, _entry: level)
    check = getattr(conftest, "_assert_av1_level_is_defined")

    if should_pass:
        check("clip.mkv")
        return
    with pytest.raises(AssertionError):
        check("clip.mkv")
