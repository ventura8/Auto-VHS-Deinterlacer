#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PY=""
if [ -f ".venv/bin/python" ]; then
    VENV_PY=".venv/bin/python"
elif [ -f ".VENV/bin/python" ]; then
    VENV_PY=".VENV/bin/python"
else
    echo "[ERROR] Virtual environment not found."
    echo "Please run './install.sh' first."
    exit 1
fi

exec "$VENV_PY" auto_deinterlancer.py "$@"
