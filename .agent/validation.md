# Validation Guide

## Preferred Order

1. Run the narrowest useful lint command.
2. Fix the reported issue in a single edit.
3. Re-run the same lint command.
4. Run a focused pytest command for the touched files.
5. Run the full validation pipeline when the change is broad.

## Commands

- `.\.VENV\Scripts\python.exe -m ruff check .`
- `.\.VENV\Scripts\python.exe -m flake8 .`
- `.\.VENV\Scripts\python.exe -m pylint auto_deinterlancer.py modules .github/scripts`
- `.\.VENV\Scripts\python.exe -m pytest -o addopts=`
- `.\run_pipeline_localy.ps1`

## Rules

- Do not add `# noqa` or `pylint: disable` markers to bypass failures.
- Do not ignore test failures that are directly caused by the code you changed.
- Keep Windows path handling explicit when a file path is part of the logic.
- Maintain coverage above 90% for every Python module and above 90% for total repository coverage.
