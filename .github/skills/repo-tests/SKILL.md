______________________________________________________________________

## name: repo-tests description: "Use when you need to add, fix, or validate tests for Auto-VHS-Deinterlacer."

# Repo Tests Skill

Use this skill for test-focused work in this repository.

## When to Use

- Fixing or expanding pytest coverage.
- Debugging failing unit, integration, or native tests.
- Adding regression tests for a code change.
- Running narrow test slices before the full suite.

## Standard Workflow

1. Identify the smallest failing test slice.
1. Fix the test or implementation in the same area.
1. Re-run the same focused pytest command.
1. Expand to the full suite when the targeted check passes.

## Commands

- `.\.VENV\Scripts\python.exe -m pytest -o addopts=`
- `.\.VENV\Scripts\python.exe -m pytest -o addopts= tests/unit`
- `.\.VENV\Scripts\python.exe -m pytest -o addopts= tests/integration`
- `.\.VENV\Scripts\python.exe -m pytest -o addopts= tests/native`

## Constraints

- Keep mocks Windows/Linux compatible.
- Patch the module under test, not unrelated imports.
- Do not add lint suppressions to make a test pass.
