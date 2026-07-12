"""Fail when any measured source file is below a coverage threshold."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as et
from pathlib import Path


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


def _read_file_coverages(xml_path: Path) -> list[tuple[str, float]]:
    tree = et.parse(xml_path)
    root = tree.getroot()

    file_coverages: list[tuple[str, float]] = []
    for cls in root.findall(".//class"):
        filename = cls.get("filename")
        line_rate_raw = cls.get("line-rate")
        if not filename or line_rate_raw is None:
            continue

        normalized = _normalize_path(filename)
        if not _is_python_source(normalized):
            continue

        try:
            line_rate = float(line_rate_raw) * 100.0
        except ValueError:
            continue
        file_coverages.append((normalized, line_rate))

    return sorted(file_coverages, key=lambda item: item[0])


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

    failures = [(path_str, pct) for path_str, pct in file_coverages if pct < threshold]

    print(f"[coverage-gate] Per-file threshold: {threshold:.2f}%")
    print("[coverage-gate] Evaluated files:")
    for path_str, pct in file_coverages:
        status = "PASS" if pct >= threshold else "FAIL"
        print(f"  - {path_str}: {pct:.2f}% ({status})")

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
