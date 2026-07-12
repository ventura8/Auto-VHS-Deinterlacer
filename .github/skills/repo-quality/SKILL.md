______________________________________________________________________

## name: repo-quality description: "Use when you need to validate, repair, or extend Auto-VHS-Deinterlacer with lint, test, and coverage workflows."

# Repo Quality Skill

Use this skill when the task is to make the repository pass its quality gates or to update the tooling that enforces them.

## When to Use

- Fixing Ruff, Flake8, or Pylint failures.
- Updating CI or local pipeline validation steps.
- Repairing test failures that are caused by recent code changes.
- Adding or adjusting validation scripts for this repository.

## Standard Workflow

1. Inspect the failing files or commands.
1. Fix the code or configuration without adding suppressions.
1. Re-run the narrowest relevant check.
1. Expand to the repo-wide quality commands when the targeted check passes.

## Commands

- `.\.VENV\Scripts\python.exe -m ruff check .`
- `.\.VENV\Scripts\python.exe -m flake8 .`
- `.\.VENV\Scripts\python.exe -m pylint auto_deinterlancer.py modules .github/scripts`
- `.\.VENV\Scripts\python.exe -m pytest -o addopts=`
- `.\run_pipeline_localy.ps1`

## Constraints

- Do not use `# noqa`, `# pylint: disable`, or equivalent suppressions.
- Keep changes minimal and aligned with the current `modules/core` and `modules/runtime` split.
- Prefer repo-local documentation and scripts over ad hoc instructions in chat.
