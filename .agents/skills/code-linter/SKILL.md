---
name: code-linter
description: Run PowerShell lint, Taplo TOML lint, Bandit, pip-audit, Black, isort, Ruff, Flake8, Pylint, Radon metrics, mdformat, and pymarkdown across repository files without suppressions.
---

# Code Linter Skill

Use this skill to lint all Python modules, PowerShell scripts, TOML configuration files, and Markdown documentation without using suppression comments or inline ignores (`# noqa`, `# pylint: disable`, `# type: ignore`, etc.).

## Working Principles

1. **No Suppressions Allowed**: Never add inline ignores, lint disable comments, or suppressions. Fix root causes directly.
1. **Auto-fix First, Then Re-lint**: Before manual code editing for lint failures, run safe automated formatters and linters (`mdformat`, `black`, `isort`, `ruff check --fix`), re-run linters, and then fix remaining issues manually.
1. **Single-Pass Editing**: When fixing issues in a file, view the entire file, address all lint and structural concerns in a single edit operation.
1. **Clean Exit**: Verify that all tools report 0 errors before declaring the lint gate passed.

## Linting Commands & Stages

### 1. PowerShell Script Linting

Runs `PSScriptAnalyzer` across all `.ps1` and `.psm1` files in the repository:

```powershell
.\.github\scripts\run_powershell_lint.ps1 -RepoRoot (Get-Location)
```

### 2. TOML Configuration Linting

Validates `pyproject.toml` and any other project TOML files with `taplo`:

```powershell
$tomlFiles = git ls-files "*.toml"
.\.VENV\Scripts\python.exe -m poetry run taplo lint $tomlFiles
```

### 3. Security & Dependency Audits

Runs AST-based security vulnerability scanning and dependency CVE audits:

```powershell
# Bandit security scan (high and medium severity)
.\.VENV\Scripts\python.exe -m poetry run bandit -ll -r auto_deinterlancer.py modules .github/scripts

# pip-audit vulnerability check
.\.VENV\Scripts\python.exe -m poetry run pip-audit
```

### 4. Python Auto-Formatting & Auto-Fixing (Pre-Lint)

Always run auto-formatters first:

```powershell
# Auto-sort imports
.\.VENV\Scripts\python.exe -m poetry run isort auto_deinterlancer.py modules tests .github/scripts

# Auto-format Python code with Black
.\.VENV\Scripts\python.exe -m poetry run black auto_deinterlancer.py modules tests .github/scripts

# Safe Ruff auto-fixes
.\.VENV\Scripts\python.exe -m poetry run ruff check --fix auto_deinterlancer.py modules tests .github/scripts
```

### 5. Python Strict Linting (Verification)

Check compliance against all project linters:

```powershell
# Check formatting
.\.VENV\Scripts\python.exe -m poetry run isort --check-only auto_deinterlancer.py modules tests .github/scripts
.\.VENV\Scripts\python.exe -m poetry run black --check auto_deinterlancer.py modules tests .github/scripts

# Lint checks
.\.VENV\Scripts\python.exe -m poetry run ruff check auto_deinterlancer.py modules tests .github/scripts
.\.VENV\Scripts\python.exe -m poetry run flake8 auto_deinterlancer.py modules tests .github/scripts
.\.VENV\Scripts\python.exe -m poetry run pylint auto_deinterlancer.py modules .github/scripts
```

### 6. Radon Complexity & Maintainability Metrics

Compute Cyclomatic Complexity and Maintainability Index:

```powershell
# Cyclomatic Complexity enforcement (Grade A/B)
.\.VENV\Scripts\python.exe -m poetry run python .github/scripts/enforce_radon_grade.py --summary-out assets/radon_summary.md

# Maintainability Index enforcement
.\.VENV\Scripts\python.exe -m poetry run python .github/scripts/enforce_radon_grade.py --metric mi --summary-out assets/radon_mi_summary.md

# Raw & Halstead metrics logging
.\.VENV\Scripts\python.exe -m poetry run radon raw auto_deinterlancer.py modules tests .github/scripts
.\.VENV\Scripts\python.exe -m poetry run radon hal auto_deinterlancer.py modules tests .github/scripts
```

### 7. Markdown Formatting & Linting

```powershell
$mdFiles = git ls-files "*.md"

# Auto-format Markdown
.\.VENV\Scripts\python.exe -m poetry run mdformat $mdFiles

# Scan Markdown compliance
.\.VENV\Scripts\python.exe -m poetry run pymarkdown -d MD013 scan $mdFiles
```
