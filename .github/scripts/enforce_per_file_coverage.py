"""Fail when any measured source file is below a coverage threshold."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from defusedxml import ElementTree as et


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def _is_python_source(path_str: str) -> bool:
    normalized = _normalize_path(path_str)
    if not normalized.endswith(".py"):
        return False

    allowed_prefixes = (
        "auto_deinterlancer.py",
        "modules/",
        "core/",
        "runtime/",
    )
    if normalized == "auto_deinterlancer.py":
        return True
    return normalized.startswith(allowed_prefixes[1:])


def _extract_coverage_entry(cls) -> tuple[str, float] | None:
    """Parse a Cobertura class node into a normalized file coverage tuple."""
    filename = cls.get("filename")
    line_rate_raw = cls.get("line-rate")
    if not filename or line_rate_raw is None:
        return None

    normalized = _normalize_path(filename)
    if not _is_python_source(normalized):
        return None

    try:
        line_rate = float(line_rate_raw) * 100.0
    except ValueError:
        return None
    return normalized, line_rate


def _read_file_coverages(xml_path: Path) -> list[tuple[str, float]]:
    tree = et.parse(xml_path)
    root = tree.getroot()

    file_coverages: list[tuple[str, float]] = []
    for cls in root.findall(".//class"):
        coverage_entry = _extract_coverage_entry(cls)
        if coverage_entry is not None:
            file_coverages.append(coverage_entry)

    return sorted(file_coverages, key=lambda item: item[0])


def _print_file_coverages(file_coverages: list[tuple[str, float]], threshold: float):
    """Print pass or fail status for each measured file."""
    print(f"[coverage-gate] Per-file threshold: {threshold:.2f}%")
    print("[coverage-gate] Evaluated files:")
    for path_str, pct in file_coverages:
        status = "PASS" if pct >= threshold else "FAIL"
        print(f"  - {path_str}: {pct:.2f}% ({status})")


def _collect_failures(file_coverages: list[tuple[str, float]], threshold: float) -> list[tuple[str, float]]:
    """Return files whose line coverage is below the configured threshold."""
    return [(path_str, pct) for path_str, pct in file_coverages if pct < threshold]


def enforce_per_file_coverage(xml_path: Path, threshold: float) -> int:
    """Return process exit code: 0 on pass, 1 on fail."""
    try:
        file_coverages = _read_file_coverages(xml_path)
    except (OSError, et.ParseError) as error:
        print(f"[coverage-gate] Failed to parse report {xml_path}: {error}")
        return 1

    if not file_coverages:
        print("[coverage-gate] No Python source files found in coverage report.")
        return 1

    failures = _collect_failures(file_coverages, threshold)
    _print_file_coverages(file_coverages, threshold)

    if failures:
        print("[coverage-gate] Coverage gate failed. Files below threshold:")
        for path_str, pct in failures:
            print(f"  - {path_str}: {pct:.2f}%")
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
