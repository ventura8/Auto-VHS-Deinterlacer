______________________________________________________________________

## name: repo-markdown-quality description: "Use when you need to format and lint Markdown documentation for Auto-VHS-Deinterlacer."

# Repo Markdown Quality Skill

Use this skill for Markdown linting and automatic delinting/formatting work.

## When to Use

- Formatting repository Markdown files consistently.
- Running Markdown lint checks in local or CI workflows.
- Repairing Markdown quality failures before tests.
- Updating docs while preserving style consistency.

## Standard Workflow

1. Run Markdown auto-delint/format first.
1. Run Markdown lint scan second.
1. Re-run lint after fixing reported findings.
1. Keep CI and local pipeline commands aligned.

## Commands

- `.\.VENV\Scripts\python.exe -m poetry run mdformat .`
- `.\.VENV\Scripts\python.exe -m poetry run pymarkdown -d MD013,MD033,MD036 scan .`

## Constraints

- Do not suppress Markdown lint findings globally without explicit request.
- Keep documentation edits minimal and focused on formatting/compliance.
- Keep Markdown stages before test execution in quality pipelines.
