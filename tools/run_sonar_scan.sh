#!/usr/bin/env bash
# Run a SonarQube analysis of this repository.
#
# Default target is SonarQube Cloud (sonarcloud.io), matching the CI job.
# Set SONAR_HOST_URL to point at a self-hosted / local SonarQube instead.
#
# Required: SONAR_TOKEN  (SonarQube Cloud: My Account > Security > Generate Token)
#
#   export SONAR_TOKEN=...
#   ./tools/run_sonar_scan.sh
#
# The scanner runs from the official Docker image, so no local Java or
# sonar-scanner installation is needed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SONAR_HOST_URL="${SONAR_HOST_URL:-https://sonarcloud.io}"

if [ -z "${SONAR_TOKEN:-}" ]; then
  echo "SONAR_TOKEN is not set. Generate one in SonarQube and export it first." >&2
  exit 1
fi

# Sonar reads coverage from assets/coverage.xml; regenerate it unless told not to.
if [ "${AVD_SONAR_SKIP_TESTS:-0}" != "1" ]; then
  mkdir -p "$REPO_ROOT/assets" "$REPO_ROOT/input"
  touch "$REPO_ROOT/input/test_video.mp4"
  ( cd "$REPO_ROOT" && AUTO_VHS_SKIP_HW_DETECT=1 poetry run pytest \
      --cov=modules --cov=auto_deinterlancer --cov-branch \
      --cov-report=xml:assets/coverage.xml \
      --junitxml=assets/pytest-report.xml \
      -q tests/ )
fi

# --network host lets the container reach a SonarQube on localhost.
docker run --rm --network host \
  -e SONAR_HOST_URL="$SONAR_HOST_URL" \
  -e SONAR_TOKEN="$SONAR_TOKEN" \
  -v "$REPO_ROOT:/usr/src" \
  sonarsource/sonar-scanner-cli:latest "$@"
