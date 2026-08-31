#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f ".venv/bin/python" ] && [ ! -f ".VENV/bin/python" ]; then
    echo "[INFO] Virtual environment not found. Running automatic installation..."
    "$SCRIPT_DIR/install.sh"
fi

if [ -f ".venv/bin/python" ]; then
    VENV_PY=".venv/bin/python"
elif [ -f ".VENV/bin/python" ]; then
    VENV_PY=".VENV/bin/python"
else
    echo "[ERROR] Installation failed or virtual environment could not be created."
    exit 1
fi

exec "$VENV_PY" auto_deinterlancer.py "$@"
