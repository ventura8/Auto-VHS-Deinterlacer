# Auto-VHS-Deinterlacer Agent Guide

Use this repository as a Windows-first Python project with a
strict validation workflow.

## Project Overview

`Auto-VHS-Deinterlacer` is an automated, studio-grade video
restoration pipeline for digitizing and restoring VHS captures.
It orchestrates VapourSynth (QTGMC), FFmpeg, and optional ML
models for audio separation, hardware-adaptive threading, and
audio-video synchronization.

- **Version single source of truth**: Pinned in `pyproject.toml`
  (`[project].version`, currently `1.1.0`).
- **Runtime Environment**: Windows-first on Python 3.12 (CPython
  64-bit) with virtualenv located at `.VENV`.

## Working Rules

- **Strict package boundaries**:
  - `modules.core`: Shared configuration, hardware detection,
    logging, environment helpers, and `patch_havsfunc`
    (documented setup-time patch exception).
  - `modules.runtime`: Pipeline execution, process orchestration
    (`vspipe`, `ffmpeg`), and fallback native frame streaming
    (`vspipe_native`).
  - `auto_deinterlancer.py`: CLI entrypoint and parameter
    validation wrapper.
- **No Suppressions Allowed**: Never add `# noqa`, `# pylint: disable`,
  `# type: ignore`, or inline suppression comments. Fix issues
  at the root.
- **Coverage Invariant**: Maintain ≥90% line coverage
  per-file and repository-wide across product code (`auto_deinterlancer.py`
  and `modules/`) with branch coverage measurement enabled; CI/automation
  scripts under `.github/scripts/` are validated via strict linters and metrics.
- **Mocking Boundaries**: Mock only external boundaries (FFmpeg,
  external VSPipe binary, hardware probing). Never mock owned code.
- **Prefer Installed Dependencies Over Source Builds**: When a native
  dependency (VapourSynth plugins such as `ffms2`, FFmpeg, build tools) is
  already available from the OS package manager, Homebrew, a wheel, or a
  prebuilt binary, use that. Compiling from source is a last-resort fallback
  only, guarded so its failure never aborts `install.sh`. This applies to
  `install.sh`, the Dockerfiles, and the CI/release workflows.
- **Documentation Synchronization Invariant**: Every time work is performed
  on the project, update all relevant Markdown files (`AGENTS.md`, `.agent/*`,
  `docs/*`, `README.md`, etc.) to keep architectural, procedural, and requirement
  documentation in sync with the codebase.
- **Validation Interpreter**: The step-by-step commands in the next section
  are Windows PowerShell and use `.\.VENV\Scripts\python.exe`. On Linux &
  macOS run the full automated pipeline instead (`./run_pipeline_localy.sh`,
  interpreter `./.venv/bin/python`), which performs the same checks in the
  same order.

## Validation Order & Commands

1. **PowerShell Linting**:

   ```powershell
   .\.github\scripts\run_powershell_lint.ps1 -RepoRoot (Get-Location)
   ```

1. **TOML Linting**:

   ```powershell
   $toml = git ls-files "*.toml"
   .\.VENV\Scripts\python.exe -m poetry run taplo lint $toml
   ```

1. **Security & Dependency Scans**:

   ```powershell
   .\.VENV\Scripts\python.exe -m poetry run bandit -ll -r auto_deinterlancer.py modules .github/scripts
   .\.VENV\Scripts\python.exe -m poetry run pip-audit
   ```

1. **Code Formatting Checks**:

   ```powershell
   .\.VENV\Scripts\python.exe -m poetry run black --check auto_deinterlancer.py modules tests .github/scripts
   .\.VENV\Scripts\python.exe -m poetry run isort --check-only auto_deinterlancer.py modules tests .github/scripts
   ```

1. **Static Code Analysis**:

   ```powershell
   .\.VENV\Scripts\python.exe -m ruff check .
   .\.VENV\Scripts\python.exe -m flake8 .
   .\.VENV\Scripts\python.exe -m pylint auto_deinterlancer.py modules .github/scripts
   ```

1. **Code Metrics**:

   ```powershell
   .\.VENV\Scripts\python.exe -m poetry run python .github/scripts/enforce_radon_grade.py --summary-out assets/radon_summary.md
   .\.VENV\Scripts\python.exe -m poetry run python .github/scripts/enforce_radon_grade.py --metric mi --summary-out assets/radon_mi_summary.md
   ```

1. **Markdown Validation**:

   ```powershell
   $mdFiles = git ls-files "*.md"
   .\.VENV\Scripts\python.exe -m poetry run mdformat --check $mdFiles
   .\.VENV\Scripts\python.exe -m poetry run pymarkdown -d MD013 scan .
   ```

1. **Tests & Coverage Gates**:

   ```powershell
   $prevSkipHw = $env:AUTO_VHS_SKIP_HW_DETECT
   $env:AUTO_VHS_SKIP_HW_DETECT = "1"
   try {
       .\.VENV\Scripts\python.exe -m pytest --cov=modules --cov=auto_deinterlancer --cov-branch --cov-report=xml:assets/coverage.xml --cov-report=term --cov-fail-under=90 tests/
       if ($LASTEXITCODE -ne 0) {
           throw "Pytest failed with exit code $LASTEXITCODE"
       }
   }
   finally {
       if ($null -ne $prevSkipHw) { $env:AUTO_VHS_SKIP_HW_DETECT = $prevSkipHw } else { Remove-Item Env:AUTO_VHS_SKIP_HW_DETECT -ErrorAction SilentlyContinue }
   }
   .\.VENV\Scripts\python.exe -m poetry run python .github/scripts/enforce_per_file_coverage.py assets/coverage.xml 90
   .\.VENV\Scripts\python.exe -m poetry run genbadge coverage -i assets/coverage.xml -o assets/coverage.svg
   ```

1. **Full Automated Local Pipeline**:

   - Windows (PowerShell): `.\run_pipeline_localy.ps1` (virtual environment at `.VENV`, interpreter at `.\.VENV\Scripts\python.exe`)
   - Linux & macOS (Bash): `./run_pipeline_localy.sh` (virtual environment at `.venv`, interpreter at `./.venv/bin/python`)

## Skills Index

The workspace provides on-demand agent skills in `.agents/skills/`:

| Skill | Description | Location |
| :---------------------------------- | :------------------------------------------------------------------------------ | :--------------------------------------------------------------------------------------------------------------- |
| **`code-linter`** | Strict linting, formatting, metrics, and zero-suppression checks | [`.agents/skills/code-linter/SKILL.md`](.agents/skills/code-linter/SKILL.md) |
| **`pipeline-runner`** | Local CI-parity validation pipeline runner and coverage badge sync | [`.agents/skills/pipeline-runner/SKILL.md`](.agents/skills/pipeline-runner/SKILL.md) |
| **`test-runner`** | Pytest unit, integration, and native test runner with ≥90% coverage enforcement | [`.agents/skills/test-runner/SKILL.md`](.agents/skills/test-runner/SKILL.md) |
| **`installer-tester`** | PowerShell setup and environment installation validation | [`.agents/skills/installer-tester/SKILL.md`](.agents/skills/installer-tester/SKILL.md) |
| **`release`** | Version bump, release notes generation, and release checklist | [`.agents/skills/release/SKILL.md`](.agents/skills/release/SKILL.md) |
| **`resolve-pr-comments`** | Resolving GitHub PR review comments with reply-before-resolve discipline | [`.agents/skills/resolve-pr-comments/SKILL.md`](.agents/skills/resolve-pr-comments/SKILL.md) |
| **`review-with-coderabbit`** | CodeRabbit review and findings triage on local changes | [`.agents/skills/review-with-coderabbit/SKILL.md`](.agents/skills/review-with-coderabbit/SKILL.md) |
| **`vapoursynth-pipeline-verifier`** | Verification of VapourSynth scripts, QTGMC presets, and havsfunc patches | [`.agents/skills/vapoursynth-pipeline-verifier/SKILL.md`](.agents/skills/vapoursynth-pipeline-verifier/SKILL.md) |

## Repository Map

- [Architecture Overview](.agent/architecture.md)
- [Setup Guide](.agent/setup.md)
- [Validation Guide](.agent/validation.md)
- [Lint Workflow](.agent/workflows/fix-lints.md)
- [Agent Instructions](.agent/Instructions.md)
