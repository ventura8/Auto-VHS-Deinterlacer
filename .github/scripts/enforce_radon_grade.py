"""Run radon complexity checks and enforce an all-A-grade policy."""

import argparse
import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

DEFAULT_TARGETS = [
    "auto_deinterlancer.py",
    "modules",
    "tests",
    ".github/scripts",
]

VALID_RADON_RANKS = {"A", "B", "C", "D", "E", "F"}


def _create_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for the radon enforcement script."""
    parser = argparse.ArgumentParser(description="Run radon checks and fail when any analyzed item is below grade A.")
    parser.add_argument("targets", nargs="*", help="Files or directories to analyze")
    parser.add_argument("--summary-out", dest="summary_out", help="Optional markdown file path for a radon summary report")
    parser.add_argument("--metric", choices=["cc", "mi"], default="cc", help="Radon metric to enforce (default: cc)")
    return parser


def run_radon(targets: list[str]) -> dict[str, list[dict[str, object]]]:
    """Run radon complexity analysis and return the parsed JSON payload."""
    command = [sys.executable, "-m", "radon", "cc", "--json", *targets]
    result = subprocess.run(command, check=False, capture_output=True, text=True)

    if result.returncode != 0:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)

    if not result.stdout.strip():
        return {}

    parsed = json.loads(result.stdout)
    _validate_cc_report_payload(parsed)

    return parsed


def _is_cc_payload_valid(blocks: object) -> bool:
    """Return whether a Radon CC JSON value is the expected block list."""
    return isinstance(blocks, list)


def _print_cc_payload_error(path: str, blocks: object):
    """Print a clear parse error message for invalid Radon CC payloads."""
    print(f"Radon complexity failed to analyze '{path}'.")
    if isinstance(blocks, dict) and "error" in blocks:
        print(f"  - error: {blocks['error']}")
        return
    print(f"  - unexpected payload: {blocks}")


def _validate_cc_report_payload(parsed: dict[str, object]):
    """Validate Radon CC JSON payload shape and fail fast on parse errors."""
    for path, blocks in parsed.items():
        if _is_cc_payload_valid(blocks):
            continue
        _print_cc_payload_error(path, blocks)
        raise SystemExit(1)


def _normalize_path(path_value: str) -> str:
    """Normalize path separators for stable target matching and reports."""
    return path_value.replace("\\", "/")


def _is_file_target(target: str) -> bool:
    """Return whether a requested target path is a file."""
    return Path(target).is_file()


def _is_target_represented(target: str, parsed_paths: set[str]) -> bool:
    """Return whether a target file/dir appears in parsed MI results."""
    normalized_target = _normalize_path(target)
    if _is_file_target(target):
        return normalized_target in parsed_paths

    prefix = normalized_target.rstrip("/") + "/"
    for parsed_path in parsed_paths:
        if parsed_path.startswith(prefix):
            return True
    return False


def _print_unrepresented_targets(targets: list[str], parsed_paths: set[str]):
    """Report targets that produced no MI entries."""
    print("Radon MI output did not include the following requested target(s):")
    for target in targets:
        if not _is_target_represented(target, parsed_paths):
            print(f"  - {target}")


def _fail_mi_parse(message: str):
    """Print one MI parse failure and terminate."""
    print(message)
    raise SystemExit(1)


def _require_mi_entry_dict(path: str, entry: object) -> dict[str, object]:
    """Return a validated MI entry mapping or terminate."""
    if isinstance(entry, dict) and "error" in entry:
        _fail_mi_parse(f"Radon MI failed to analyze '{path}'.\n  - error: {entry['error']}")
    if not isinstance(entry, dict):
        _fail_mi_parse(f"Radon MI returned malformed payload for '{path}': {entry}")
    return entry


def _parse_mi_rank(path: str, entry: dict[str, object]) -> str:
    """Return a validated Radon MI rank."""
    rank = str(entry.get("rank", ""))
    if rank not in VALID_RADON_RANKS:
        _fail_mi_parse(f"Radon MI entry has invalid rank for '{path}': {rank}")
    return rank


def _parse_mi_score(path: str, entry: dict[str, object]) -> float:
    """Return a validated Radon MI numeric score."""
    try:
        return float(entry["mi"])
    except KeyError:
        _fail_mi_parse(f"Radon MI entry missing expected keys for '{path}': {entry}")
    except (TypeError, ValueError):
        _fail_mi_parse(f"Radon MI entry has invalid score for '{path}': {entry.get('mi')}")
    return 0.0


def _parse_mi_json_entry(path: str, entry: object) -> tuple[str, str, float] | None:
    """Parse one Radon MI JSON entry or fail for malformed payloads."""
    normalized_path = _normalize_path(path)
    entry_dict = _require_mi_entry_dict(normalized_path, entry)
    rank = _parse_mi_rank(normalized_path, entry_dict)
    score = _parse_mi_score(normalized_path, entry_dict)
    return normalized_path, rank, score


def _load_mi_payload(output: str) -> dict[str, object]:
    """Parse and validate the top-level MI JSON payload."""
    if not output.strip():
        _fail_mi_parse("Radon MI produced empty output.")

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        _fail_mi_parse(f"Radon MI produced invalid JSON: {error}")

    if not isinstance(payload, dict) or not payload:
        _fail_mi_parse("Radon MI JSON payload is empty or malformed.")
    return payload


def _parse_mi_payload_entries(payload: dict[str, object]) -> tuple[list[tuple[str, str, float]], set[str]]:
    """Return parsed MI rows and the set of represented paths."""
    parsed: list[tuple[str, str, float]] = []
    parsed_paths: set[str] = set()
    for path, entry in payload.items():
        row = _parse_mi_json_entry(path, entry)
        if row is None:
            continue
        parsed.append(row)
        parsed_paths.add(row[0])
    return parsed, parsed_paths


def _ensure_mi_targets_represented(targets: list[str], parsed_paths: set[str]):
    """Terminate when any requested MI target produced no entries."""
    if all(_is_target_represented(target, parsed_paths) for target in targets):
        return
    _print_unrepresented_targets(targets, parsed_paths)
    raise SystemExit(1)


def _parse_mi_output(output: str, targets: list[str]) -> list[tuple[str, str, float]]:
    """Parse `radon mi --json` output and validate target coverage."""
    payload = _load_mi_payload(output)
    parsed, parsed_paths = _parse_mi_payload_entries(payload)

    if not parsed:
        _fail_mi_parse("Radon MI JSON payload contained no analyzable entries.")

    _ensure_mi_targets_represented(targets, parsed_paths)

    parsed.sort(key=lambda item: (item[0], item[1], item[2]))
    return parsed


def run_radon_mi(targets: list[str]) -> list[tuple[str, str, float]]:
    """Run radon maintainability analysis and parse path, grade, score rows."""
    command = [sys.executable, "-m", "radon", "mi", "--json", *targets]
    result = subprocess.run(command, check=False, capture_output=True, text=True)

    if result.returncode != 0:
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)

    return _parse_mi_output(result.stdout, targets)


def collect_violations(report: dict[str, list[dict[str, object]]]) -> list[tuple[str, str, int, float, str]]:
    """Collect analyzed blocks whose radon grade is worse than A."""
    violations: list[tuple[str, str, int, float, str]] = []
    for path, blocks in report.items():
        for block in blocks:
            rank = str(block.get("rank", ""))
            if rank == "A":
                continue

            name = str(block.get("name", "<unknown>"))
            lineno = int(block.get("lineno", 0))
            complexity = float(block.get("complexity", 0))
            violations.append((path, name, lineno, complexity, rank))

    violations.sort(key=lambda item: (-item[3], item[0], item[2], item[1]))
    return violations


def _iter_blocks(report: dict[str, list[dict[str, object]]]) -> Iterable[tuple[str, dict[str, object]]]:
    """Yield individual analyzed blocks in a stable path order."""
    for path in sorted(report):
        for block in report[path]:
            yield path, block


def _build_markdown_summary(report: dict[str, list[dict[str, object]]], violations: list[tuple[str, str, int, float, str]]) -> str:
    """Render a markdown radon report suitable for GitHub step summaries."""
    header = "## Radon Complexity Report\n\n"
    if violations:
        header += f"Status: fail, {len(violations)} block(s) below grade A.\n\n"
    else:
        header += "Status: pass, all analyzed blocks are grade A.\n\n"

    table_lines = [
        "| Path | Block | Line | Grade | Complexity |",
        "| :--- | :--- | ---: | :---: | ---: |",
    ]
    for path, block in _iter_blocks(report):
        table_lines.append(
            f"| {path.replace('\\', '/')} | {str(block.get('name', '<unknown>'))} | "
            f"{int(block.get('lineno', 0))} | {str(block.get('rank', '?'))} | "
            f"{int(float(block.get('complexity', 0)))} |"
        )
    return header + "\n".join(table_lines) + "\n"


def _build_mi_markdown_summary(report: list[tuple[str, str, float]], violations: list[tuple[str, str, float]]) -> str:
    """Render a markdown MI report suitable for GitHub step summaries."""
    header = "## Radon MI Report\n\n"
    if violations:
        header += f"Status: fail, {len(violations)} file(s) below grade A.\n\n"
    else:
        header += "Status: pass, all analyzed files are grade A.\n\n"

    table_lines = [
        "| Path | Grade | MI Score |",
        "| :--- | :---: | ---: |",
    ]
    for path, grade, score in report:
        table_lines.append(f"| {path} | {grade} | {score:.2f} |")
    return header + "\n".join(table_lines) + "\n"


def _write_summary(path_value: str | None, content: str):
    """Persist a markdown summary when a target path was provided."""
    if not path_value:
        return
    output_path = Path(path_value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def _resolve_targets(argv: list[str]) -> tuple[list[str], list[str]]:
    """Resolve requested targets and return existing and missing paths."""
    targets = argv or DEFAULT_TARGETS
    missing_targets = [target for target in targets if not Path(target).exists()]
    return targets, missing_targets


def _print_missing_targets(missing_targets: list[str]):
    """Report radon targets that are not present in the workspace."""
    print("Radon targets not found:")
    for target in missing_targets:
        print(f"  - {target}")


def _print_violations(violations: list[tuple[str, str, int, float, str]]):
    """Report blocks that exceeded the allowed radon grade."""
    print("Radon complexity gate failed. The following blocks are worse than grade A:")
    for path, name, lineno, complexity, rank in violations:
        print(f"  - {path}:{lineno} {name} -> {rank} ({complexity:.0f})")


def _collect_mi_violations(report: list[tuple[str, str, float]]) -> list[tuple[str, str, float]]:
    """Return files whose MI grade is worse than A."""
    violations = [entry for entry in report if entry[1] != "A"]
    violations.sort(key=lambda item: (item[1], item[2], item[0]))
    return violations


def _print_mi_violations(violations: list[tuple[str, str, float]]):
    """Report files that exceeded the allowed MI grade."""
    print("Radon MI gate failed. The following files are worse than grade A:")
    for path, grade, score in violations:
        print(f"  - {path} -> {grade} ({score:.2f})")


def main() -> int:
    """Run the radon gate CLI and return the process exit code."""
    args = _create_parser().parse_args()
    targets, missing_targets = _resolve_targets(args.targets)
    if missing_targets:
        _print_missing_targets(missing_targets)
        return 2

    if args.metric == "mi":
        report = run_radon_mi(targets)
        violations = _collect_mi_violations(report)
        _write_summary(args.summary_out, _build_mi_markdown_summary(report, violations))
        if violations:
            _print_mi_violations(violations)
            return 1

        print("Radon MI gate passed: all analyzed files are grade A.")
        return 0

    report = run_radon(targets)
    violations = collect_violations(report)
    _write_summary(args.summary_out, _build_markdown_summary(report, violations))
    if violations:
        _print_violations(violations)
        return 1

    print("Radon complexity gate passed: all analyzed blocks are grade A.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
