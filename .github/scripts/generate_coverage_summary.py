"""Generate a markdown coverage summary from a Cobertura XML report."""

import sys
from datetime import datetime

from coverage_paths import extract_source_roots, resolve_repo_relative
from defusedxml import ElementTree as ET


def _parse_coverage_root(xml_path):
    """Load and return the Cobertura XML root element."""
    tree = ET.parse(xml_path)
    return tree.getroot()


def _extract_global_rates(root) -> tuple[float, float]:
    """Read total line and branch coverage percentages from the Cobertura root."""
    line_rate = float(root.get("line-rate", 0)) * 100
    branch_rate = float(root.get("branch-rate", 0)) * 100
    return line_rate, branch_rate


def _extract_class_row(cls, source_roots):
    """Parse a Cobertura class node into a summary row tuple."""
    filename = cls.get("filename")
    line_rate_raw = cls.get("line-rate")
    branch_rate_raw = cls.get("branch-rate")

    if not filename or line_rate_raw is None or branch_rate_raw is None:
        raise ValueError("missing required class attributes")

    simplified_name = resolve_repo_relative(filename, source_roots)
    if not simplified_name:
        raise ValueError("unresolvable class filename")
    c_line_rate = float(line_rate_raw) * 100
    c_branch_rate = float(branch_rate_raw) * 100
    return simplified_name, c_line_rate, c_branch_rate


def _iter_class_rows(root):
    """Yield per-class coverage table rows from the Cobertura payload."""
    source_roots = extract_source_roots(root)
    for package in root.findall(".//package"):
        for cls in package.findall(".//class"):
            try:
                yield _extract_class_row(cls, source_roots)
            except (AttributeError, TypeError, ValueError) as error:
                print(f"Skipping malformed class entry: {error}", file=sys.stderr)


def _build_markdown(line_rate: float, branch_rate: float, timestamp: str, rows) -> str:
    """Render the markdown coverage summary."""
    markdown_lines = [
        "## 📊 Code Coverage Report",
        "",
        f"**Total Coverage:** {line_rate:.2f}%",
        f"**Branch Coverage:** {branch_rate:.2f}%",
        f"**Generated:** {timestamp}",
        "",
        "| File | Coverage | Branches |",
        "| :--- | :---: | :---: |",
    ]
    for filename, c_line_rate, c_branch_rate in rows:
        markdown_lines.append(f"| {filename} | {c_line_rate:.1f}% | {c_branch_rate:.1f}% |")
    return "\n".join(markdown_lines)


def generate_summary(xml_path):
    """Print a markdown summary for the given Cobertura XML file."""

    try:
        root = _parse_coverage_root(xml_path)
        line_rate, branch_rate = _extract_global_rates(root)
    except (ET.ParseError, OSError, ValueError) as error:
        print(f"Error parsing {xml_path}: {error}")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = list(_iter_class_rows(root))
    print(_build_markdown(line_rate, branch_rate, timestamp, rows))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate_summary(sys.argv[1])
    else:
        print("Usage: python generate_coverage_summary.py coverage.xml")
