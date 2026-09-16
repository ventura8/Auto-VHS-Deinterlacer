#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
#  Run Ubuntu Docker Real-Dependency E2E Test Suite
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Usage: docker/run_docker_e2e.sh [ubuntu|fedora]   (default: ubuntu)
DISTRO="${1:-ubuntu}"
case "$DISTRO" in
    ubuntu|fedora) ;;
    *) echo "Unknown distro '$DISTRO' (expected ubuntu or fedora)"; exit 2 ;;
esac
IMAGE_NAME="auto-vhs-${DISTRO}-e2e:latest"

echo "==> Building ${DISTRO} Docker image ($IMAGE_NAME)..."
docker build -f "docker/Dockerfile.${DISTRO}" -t "$IMAGE_NAME" .

echo "==> Running real-dependency E2E tests in Docker container..."
docker run --rm -t "$IMAGE_NAME"

echo "==> Docker E2E test run completed successfully!"
