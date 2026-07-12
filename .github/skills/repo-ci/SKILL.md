---
name: repo-ci
description: "Use when you need to update GitHub Actions or the local pipeline for Auto-VHS-Deinterlacer."
---

# Repo CI Skill

Use this skill for changes to CI/CD or the local validation pipeline.

## When to Use

- Editing GitHub Actions workflows.
- Updating `run_pipeline_localy.ps1`.
- Synchronizing lint, test, or coverage commands between CI and local runs.
- Adding or adjusting release-adjacent validation steps.

## Standard Workflow

1. Keep CI and local commands aligned.
2. Run the repo's lint checks before the test pipeline.
3. Validate any command change locally.
4. Confirm the workflow still reflects the repository's current package layout.

## Commands

- `.\.VENV\Scripts\python.exe -m ruff check .`
- `.\.VENV\Scripts\python.exe -m flake8 .`
- `.\.VENV\Scripts\python.exe -m pylint auto_deinterlancer.py modules .github/scripts`
- `.\.VENV\Scripts\python.exe -m pytest -o addopts=`
- `.\run_pipeline_localy.ps1`

## Constraints

- Do not let CI and local scripts drift apart.
- Keep the validation order consistent across scripts.
- Do not add suppressions to make pipeline checks pass.
