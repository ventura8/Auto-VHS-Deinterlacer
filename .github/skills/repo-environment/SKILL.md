______________________________________________________________________

## name: repo-environment description: "Use when you need to install, repair, or understand the Auto-VHS-Deinterlacer Python environment."

# Repo Environment Skill

Use this skill when the task is about local setup, dependency installation, or workspace repair.

## When to Use

- Setting up the repository for the first time.
- Recreating or repairing the `.VENV` environment.
- Installing Poetry-managed dependencies.
- Checking how the project should be launched locally.

## Standard Workflow

1. Confirm the workspace root and active interpreter.
1. Install or repair dependencies in the repository venv.
1. Validate the environment with the repo's quality commands.
1. Use the local pipeline if the change affects setup or execution.

## Commands

- `.\install.ps1`
- `.\.VENV\Scripts\python.exe -m poetry install --only dev --no-root`
- `python -m pip install poetry` (bootstrap exception before `.VENV` exists)
- `.\run_pipeline_localy.ps1`

## Constraints

- Use the repository `.VENV` interpreter for validation.
- Keep Windows path handling explicit.
- Do not hardcode alternate environment locations.
