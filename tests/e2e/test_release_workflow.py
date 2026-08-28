"""Tests for architecture-specific release artifacts."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _release_macos_lanes(job_name: str) -> set[tuple[str, str]]:
    """Return macOS platform and runner pairs from a release workflow matrix."""
    workflow_path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    lanes = workflow["jobs"][job_name]["strategy"]["matrix"]["include"]
    return {(lane["platform"], lane["runner"]) for lane in lanes if lane.get("macos")}


def test_release_workflow_packages_and_verifies_apple_silicon():
    """Keep explicit Intel and Apple Silicon release lanes in both release jobs."""
    expected_lanes = {("macOS-Intel", "macos-26-intel"), ("macOS-Apple-Silicon", "macos-26")}

    assert _release_macos_lanes("package-release-artifacts") == expected_lanes
    assert _release_macos_lanes("verify-release-artifacts") == expected_lanes
