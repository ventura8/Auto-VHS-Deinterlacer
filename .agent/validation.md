# Validation Guide

## Preferred Order

1. Run the narrowest useful lint command.
1. Fix the reported issue in a single edit.
1. Re-run the same lint command.
1. Run a focused pytest command for the touched files.
1. Run the full validation pipeline when the change is broad.

## Commands

- `$tomlFiles = git ls-files "*.toml";`
  `.\.VENV\Scripts\python.exe -m poetry run taplo lint $tomlFiles`
- `.\.VENV\Scripts\python.exe -m poetry run bandit -ll -r`
  `auto_deinterlancer.py modules .github/scripts`
- `.\.VENV\Scripts\python.exe -m poetry run pip-audit`
- `.\.VENV\Scripts\python.exe -m poetry run black --check`
  `auto_deinterlancer.py modules tests .github/scripts`
- `.\.VENV\Scripts\python.exe -m isort --check-only`
  `auto_deinterlancer.py modules tests .github/scripts`
- `.\.VENV\Scripts\python.exe -m ruff check .`
- `.\.VENV\Scripts\python.exe -m flake8 .`
- `.\.VENV\Scripts\python.exe -m pylint auto_deinterlancer.py`
  `modules .github/scripts`
- `.\.VENV\Scripts\python.exe -m pytest -o addopts=`
- `.\run_pipeline_localy.ps1`

## Rules

- Do not add `# noqa` or `pylint: disable` markers to bypass failures.
- Do not ignore test failures that are directly caused by the code you changed.
- Keep Windows path handling explicit when a file path is part of the logic.
- Maintain coverage above 90% for every Python module and above 90% for
  total repository coverage.
- Always update all relevant Markdown documentation files when making changes
  to features, installer logic, architecture, or workflows.
- Release verification must make packaged POSIX application resources writable
  before bootstrapping their virtual environment, because package installation
  places them in root-owned system locations.
