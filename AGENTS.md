# Auto-VHS-Deinterlacer Agent Guide

Use this repository as a Windows-first Python project with a strict validation workflow.

## Working Rules

- Prefer minimal edits that keep behavior stable.
- Keep imports aligned with the current package split: `modules.core` and `modules.runtime`.
- Do not add lint suppressions, ignore comments, or compatibility shims unless the user explicitly asks for them.
- Use the workspace venv at `.VENV` for validation.
- Treat lint as a gate before tests when making code changes.

## Validation Order

1. Run `.\.VENV\Scripts\python.exe -m ruff check .`.
2. Run `.\.VENV\Scripts\python.exe -m flake8 .`.
3. Run `.\.VENV\Scripts\python.exe -m pylint auto_deinterlancer.py modules .github/scripts`.
4. Run `.\.VENV\Scripts\python.exe -m pytest -o addopts=` for focused checks, or the full suite when the change is broad.

## Repo Map

- [Architecture overview](.agent/architecture.md)
- [Setup guide](.agent/setup.md)
- [Validation guide](.agent/validation.md)
- [Lint workflow](.agent/workflows/fix-lints.md)
