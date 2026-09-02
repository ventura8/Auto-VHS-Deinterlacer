#!/usr/bin/env bash
set -euo pipefail

# Keep dependency installation deterministic on headless Linux/macOS hosts.
export POETRY_KEYRING_ENABLED=false

# ==============================================================================
#  Local CI-Parity Quality & Validation Pipeline (Linux & macOS)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

list_repository_files() {
    local pattern="$1"
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git ls-files -z -- "$pattern"
        return
    fi
    find . \( -path ./.git -o -path ./.venv -o -path ./.VENV \) -prune -o -type f -name "$pattern" -print0
}

# If script is being sourced rather than executed, do not run the pipeline
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    return 0 2>/dev/null || true
fi

cd "$SCRIPT_DIR"

VENV_PY="$SCRIPT_DIR/.venv/bin/python"
if [ ! -f "$VENV_PY" ]; then
    echo "[ERROR] Virtual environment not found at .venv. Run ./install.sh first."
    exit 1
fi

step() {
    echo "==> $1"
}

step "Install Poetry"
"$VENV_PY" -m pip install poetry==2.4.2

step "Sync Poetry lock file"
"$VENV_PY" -m poetry check --lock || "$VENV_PY" -m poetry lock

step "Install dev dependencies"
"$VENV_PY" -m poetry install -v --only main,dev --no-root

step "Run PowerShell Lint"
if command -v pwsh &>/dev/null; then
    pwsh -NoLogo -NonInteractive -File .github/scripts/run_powershell_lint.ps1 -RepoRoot "$(pwd)"
else
    echo "[WARNING] pwsh not found — skipping PowerShell lint (runs on GHA via pwsh)"
fi

step "Run Taplo TOML Lint"
TOML_FILES=()
while IFS= read -r -d '' toml_file; do
    TOML_FILES+=("$toml_file")
done < <(list_repository_files '*.toml')
if [ "${#TOML_FILES[@]}" -eq 0 ]; then
    echo "No TOML files found to lint"
    exit 1
fi
"$VENV_PY" -m poetry run taplo lint "${TOML_FILES[@]}"

step "Run Bandit Security Scan"
"$VENV_PY" -m poetry run bandit -ll -r auto_deinterlancer.py modules .github/scripts

step "Run pip-audit Dependency Scan"
"$VENV_PY" -m poetry run pip-audit

step "Run Black"
"$VENV_PY" -m poetry run black --check auto_deinterlancer.py modules tests .github/scripts

step "Run isort"
"$VENV_PY" -m poetry run isort --check-only auto_deinterlancer.py modules tests .github/scripts

step "Run Ruff"
"$VENV_PY" -m poetry run ruff check auto_deinterlancer.py modules tests .github/scripts

step "Run Flake8"
"$VENV_PY" -m poetry run flake8 auto_deinterlancer.py modules tests .github/scripts

step "Run Pylint"
"$VENV_PY" -m poetry run pylint auto_deinterlancer.py modules tests .github/scripts

RADON_FAILURES=()

step "Run Radon Complexity"
mkdir -p assets
"$VENV_PY" -m poetry run python .github/scripts/enforce_radon_grade.py --summary-out assets/radon_summary.md \
    || RADON_FAILURES+=("Radon Complexity")

step "Run Radon Maintainability"
"$VENV_PY" -m poetry run python .github/scripts/enforce_radon_grade.py --metric mi --summary-out assets/radon_mi_summary.md \
    || RADON_FAILURES+=("Radon Maintainability")

step "Run Radon Raw Metrics"
"$VENV_PY" -m poetry run radon raw auto_deinterlancer.py modules tests .github/scripts | tee assets/radon_raw.txt \
    || RADON_FAILURES+=("Radon Raw Metrics")

step "Run Radon Halstead Metrics"
"$VENV_PY" -m poetry run radon hal auto_deinterlancer.py modules tests .github/scripts | tee assets/radon_hal.txt \
    || RADON_FAILURES+=("Radon Halstead Metrics")

step "Check Radon Status"
if [ "${#RADON_FAILURES[@]}" -gt 0 ]; then
    echo "Radon checks failed: ${RADON_FAILURES[*]}"
    exit 1
fi

step "Run Markdown Auto-Delint"
MD_FILES=()
while IFS= read -r -d '' md_file; do
    MD_FILES+=("$md_file")
done < <(list_repository_files '*.md')
if [ "${#MD_FILES[@]}" -gt 0 ]; then
    "$VENV_PY" -m poetry run mdformat "${MD_FILES[@]}"
fi

step "Run Markdown Lint"
"$VENV_PY" -m poetry run pymarkdown -d MD013 scan .

step "Create Mock Environment"
mkdir -p input
CLEANUP_MOCK_VIDEO=0
if [ ! -e input/test_video.mp4 ]; then
    touch input/test_video.mp4
    CLEANUP_MOCK_VIDEO=1
fi
cleanup_mock_video() {
    if [ "$CLEANUP_MOCK_VIDEO" -eq 1 ] && [ -e input/test_video.mp4 ]; then
        rm -f input/test_video.mp4
    fi
}
trap cleanup_mock_video EXIT

step "Run tests with coverage"
mkdir -p assets
AUTO_VHS_SKIP_HW_DETECT=1 "$VENV_PY" -m poetry run pytest \
    --cov=modules --cov=auto_deinterlancer \
    --cov-branch \
    --cov-report=xml:assets/coverage.xml \
    --cov-report=term \
    --cov-fail-under=90 \
    tests/

step "Enforce Per-File Coverage >= 90%"
"$VENV_PY" -m poetry run python .github/scripts/enforce_per_file_coverage.py assets/coverage.xml 90

step "Generate Coverage Summary"
"$VENV_PY" -m poetry run python .github/scripts/generate_coverage_summary.py assets/coverage.xml > assets/coverage_summary.md

step "Generate coverage badge"
"$VENV_PY" -m poetry run genbadge coverage -i assets/coverage.xml -o assets/coverage.svg
echo "Badge updated: assets/coverage.svg"

echo "Local pipeline completed successfully."
