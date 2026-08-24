---
name: pipeline-runner
description: Execute local pipeline checks, full lint suite, pytest execution, per-file coverage enforcement (>=90%), and coverage badge generation.
---

# Local Pipeline Runner Skill

Use this skill to validate project code quality, formatting, unit/integration/native tests, and coverage gates locally using `run_pipeline_localy.ps1` before pushing or creating pull requests.

## Workflow & Guidelines

1. **Pipeline Script Authority**: The canonical local orchestrator is `run_pipeline_localy.ps1`.
1. **CI Parity**: The steps in `run_pipeline_localy.ps1` mirror `.github/workflows/ci.yml`.
1. **Coverage Gates**:
   - Total repository coverage must remain ≥ 90%.
   - Per-file coverage must remain ≥ 90% enforced by `.github/scripts/enforce_per_file_coverage.py`.
   - Coverage badge `assets/coverage.svg` must be regenerated on test completion.
1. **Environment Isolation**: The pipeline automatically sets `$env:AUTO_VHS_SKIP_HW_DETECT = "1"` during unit tests to avoid hardware dependency discrepancies on different CI/dev machines.

## Running the Pipeline

### 1. Full Pipeline Run

Run the entire suite from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_pipeline_localy.ps1
```

Or from an active PowerShell session:

```powershell
.\run_pipeline_localy.ps1
```

### 2. Targeted Step Execution

If debugging a specific phase of the pipeline:

```powershell
# Step A: Lint & Security
$tomlFiles = git ls-files "*.toml"
.\.VENV\Scripts\python.exe -m poetry run taplo lint $tomlFiles
.\.VENV\Scripts\python.exe -m poetry run bandit -ll -r auto_deinterlancer.py modules .github/scripts
.\.VENV\Scripts\python.exe -m poetry run pip-audit
.\.VENV\Scripts\python.exe -m poetry run ruff check auto_deinterlancer.py modules tests .github/scripts
.\.VENV\Scripts\python.exe -m poetry run flake8 auto_deinterlancer.py modules tests .github/scripts
.\.VENV\Scripts\python.exe -m poetry run pylint auto_deinterlancer.py modules .github/scripts

# Step B: Tests with Coverage
$prevSkipHw = $env:AUTO_VHS_SKIP_HW_DETECT
$env:AUTO_VHS_SKIP_HW_DETECT = "1"
try {
    .\.VENV\Scripts\python.exe -m poetry run pytest --cov=modules --cov=auto_deinterlancer --cov-branch --cov-report=xml:assets/coverage.xml --cov-report=term --cov-fail-under=90 tests/
    if ($LASTEXITCODE -ne 0) {
        throw "Pytest failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($null -ne $prevSkipHw) { $env:AUTO_VHS_SKIP_HW_DETECT = $prevSkipHw } else { Remove-Item Env:AUTO_VHS_SKIP_HW_DETECT -ErrorAction SilentlyContinue }
}

# Step C: Per-File Coverage Enforcement
.\.VENV\Scripts\python.exe -m poetry run python .github/scripts/enforce_per_file_coverage.py assets/coverage.xml 90

# Step D: Badge Generation
.\.VENV\Scripts\python.exe -m poetry run genbadge coverage -i assets/coverage.xml -o assets/coverage.svg
```
