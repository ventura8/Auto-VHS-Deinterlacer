"""Fail when any measured source file is below a coverage threshold."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coverage_paths import extract_source_roots, resolve_repo_relative
from defusedxml import ElementTree as et


def _is_measured_source(path_str: str) -> bool:
    """Return whether a repo-relative path is one of the measured source files."""
    if not path_str.endswith(".py"):
        return False
    return path_str == "auto_deinterlancer.py" or path_str.startswith("modules/")


def _extract_coverage_entry(cls, source_roots: list[str]) -> tuple[str, float] | None:
    """Parse a Cobertura class node into a repo-relative file coverage tuple."""
    filename = cls.get("filename")
    line_rate_raw = cls.get("line-rate")
    if not filename or line_rate_raw is None:
        return None

    resolved = resolve_repo_relative(filename, source_roots)
    if not resolved:
        return None

    try:
        line_rate = float(line_rate_raw) * 100.0
    except ValueError:
        return None
    return resolved, line_rate


def _read_file_coverages(xml_path: Path) -> tuple[list[tuple[str, float]], list[str]]:
    """Return measured per-file coverages plus any entries that could not be classified."""
    tree = et.parse(xml_path)
    root = tree.getroot()
    source_roots = extract_source_roots(root)

    file_coverages: list[tuple[str, float]] = []
    unclassified: list[str] = []
    for cls in root.findall(".//class"):
        coverage_entry = _extract_coverage_entry(cls, source_roots)
        if coverage_entry is None:
            unclassified.append(cls.get("filename") or "<missing filename>")
            continue
        if not _is_measured_source(coverage_entry[0]):
            unclassified.append(coverage_entry[0])
            continue
        file_coverages.append(coverage_entry)

    return sorted(file_coverages, key=lambda item: item[0]), sorted(unclassified)


def _print_file_coverages(file_coverages: list[tuple[str, float]], threshold: float):
    """Print pass or fail status for each measured file."""
    print(f"[coverage-gate] Per-file threshold: {threshold:.2f}%")
    print("[coverage-gate] Evaluated files:")
    for path_str, pct in file_coverages:
        status = "PASS" if pct >= threshold else "FAIL"
        print(f"  - {path_str}: {pct:.2f}% ({status})")


def _print_unclassified(unclassified: list[str]):
    """Print entries the gate could not attribute to a measured source file."""
    print("[coverage-gate] Coverage gate failed. Unclassified entries (not gated):")
    for path_str in unclassified:
        print(f"  - {path_str}")
    print("[coverage-gate] Resolve these against the report's <sources> roots or update the gate.")


def _print_failures(failures: list[tuple[str, float]]):
    """Print files that fell below the configured threshold."""
    print("[coverage-gate] Coverage gate failed. Files below threshold:")
    for path_str, pct in failures:
        print(f"  - {path_str}: {pct:.2f}%")


def _collect_failures(file_coverages: list[tuple[str, float]], threshold: float) -> list[tuple[str, float]]:
    """Return files whose line coverage is below the configured threshold."""
    return [(path_str, pct) for path_str, pct in file_coverages if pct < threshold]


def enforce_per_file_coverage(xml_path: Path, threshold: float) -> int:
    """Return process exit code: 0 on pass, 1 on fail."""
    try:
        file_coverages, unclassified = _read_file_coverages(xml_path)
    except (OSError, et.ParseError) as error:
        print(f"[coverage-gate] Failed to parse report {xml_path}: {error}")
        return 1

    _print_file_coverages(file_coverages, threshold)

    if unclassified:
        _print_unclassified(unclassified)
        return 1

    if not file_coverages:
        print("[coverage-gate] No Python source files found in coverage report.")
        return 1

    failures = _collect_failures(file_coverages, threshold)
    if failures:
        _print_failures(failures)
        return 1

    print("[coverage-gate] Coverage gate passed.")
    return 0


def main() -> int:
    """Parse CLI args and execute the per-file coverage gate."""
    parser = argparse.ArgumentParser(description="Enforce per-file coverage threshold from Cobertura XML.")
    parser.add_argument("xml_path", help="Path to coverage XML file")
    parser.add_argument("threshold", nargs="?", type=float, default=90.0, help="Minimum per-file line coverage percent")
    args = parser.parse_args()
    return enforce_per_file_coverage(Path(args.xml_path), args.threshold)


if __name__ == "__main__":
    sys.exit(main())
