"""Tests for architecture-specific release artifacts."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _release_lanes(job_name: str) -> list[dict]:
    """Return platform matrix lanes from release workflow."""
    workflow_path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    return workflow["jobs"][job_name]["strategy"]["matrix"]["include"]


def _release_macos_lanes(job_name: str) -> set[tuple[str, str]]:
    """Return macOS platform and runner pairs from a release workflow matrix."""
    lanes = _release_lanes(job_name)
    return {(lane["platform"], lane["runner"]) for lane in lanes if lane.get("macos")}


def test_release_workflow_packages_and_verifies_apple_silicon():
    """Keep explicit Intel and Apple Silicon release lanes in both release jobs."""
    expected_lanes = {("macOS-Intel", "macos-26-intel"), ("macOS-Apple-Silicon", "macos-26")}

    assert _release_macos_lanes("package-release-artifacts") == expected_lanes
    assert _release_macos_lanes("verify-release-artifacts") == expected_lanes


EXPECTED_PACKAGING = {
    "Windows": "exe",
    "Linux": "linux-packages",
    "macOS-Intel": "pkg",
    "macOS-Apple-Silicon": "pkg",
}


def test_release_workflow_packaging_formats():
    """Verify that release workflow targets native installers (exe, packages, pkg)."""
    lanes = _release_lanes("package-release-artifacts")
    actual = {lane["platform"]: lane.get("artifact_type") for lane in lanes}
    assert actual == EXPECTED_PACKAGING
