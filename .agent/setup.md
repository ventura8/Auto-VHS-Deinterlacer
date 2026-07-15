# Setup Guide

## Prerequisites

- Windows 10 or Windows 11.
- Python 3.12.

## Local Setup

1. Run `.\install.ps1` to provision the local environment and pip-backed
   VapourSynth runtime folder.
1. Use the interpreter at `.\.VENV\Scripts\python.exe` for project commands.
1. Install dependencies with Poetry from the repository root.
1. Keep `config.yaml` in the project root unless the config loader is changed
   intentionally.

## Useful Commands

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

## Notes

- The repo uses a package split under `modules/core` and `modules/runtime`.
- Tests are grouped by concern, so validate the changed slice first when possible.
