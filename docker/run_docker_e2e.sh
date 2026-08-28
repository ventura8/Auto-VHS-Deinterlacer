#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
#  Run Ubuntu Docker Real-Dependency E2E Test Suite
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_NAME="auto-vhs-ubuntu-e2e:latest"

echo "==> Building Ubuntu Docker image ($IMAGE_NAME)..."
docker build -f docker/Dockerfile.ubuntu -t "$IMAGE_NAME" .

echo "==> Running real-dependency E2E tests in Docker container..."
docker run --rm -t "$IMAGE_NAME"

echo "==> Docker E2E test run completed successfully!"
