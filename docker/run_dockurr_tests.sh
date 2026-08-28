#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
#  Unified Test Runner for Docker and Dockurr Virtualized Containers
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

check_kvm() {
    if [ ! -e /dev/kvm ]; then
        echo "Error: /dev/kvm device not found. KVM hardware acceleration is required for dockurr containers."
        exit 1
    fi
}

check_apple_hardware() {
    # Apple's macOS EULA restricts macOS virtualization to genuine Apple hardware.
    # The presence of /dev/kvm is not sufficient: require an explicit opt-in that
    # asserts the host is Apple hardware (set automatically on macOS/arm64 Apple
    # Silicon and Apple-made Intel Macs, or manually via AUTO_VHS_APPLE_HARDWARE=1).
    if [ "${AUTO_VHS_APPLE_HARDWARE:-}" = "1" ]; then
        return 0
    fi
    if [ "$(uname -s)" = "Darwin" ]; then
        local brand
        brand="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)"
        if [ "$(uname -m)" = "arm64" ] || printf '%s' "$brand" | grep -qi 'apple'; then
            return 0
        fi
    fi
    echo "Error: dockurr/macos may only run on genuine Apple hardware (Apple's macOS EULA)."
    echo "       Set AUTO_VHS_APPLE_HARDWARE=1 to confirm the host is Apple hardware."
    exit 1
}

run_ubuntu() {
    echo "==> Running Ubuntu 26.04 Docker E2E test..."
    ./docker/run_docker_e2e.sh
}

# Run a command under a wall-clock deadline when a timeout utility is available
# (`timeout` on GNU/Linux, `gtimeout` from Homebrew coreutils on macOS). Hosts
# without either run the command unbounded so the runner stays portable.
run_with_deadline() {
    local seconds="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$seconds" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$seconds" "$@"
    else
        echo "[WARN] No timeout/gtimeout utility found; running without a deadline."
        "$@"
    fi
}

run_windows() {
    check_kvm
    local compose_file="docker/docker-compose.windows.yml"
    local status_file="$REPO_ROOT/windows_test_status.txt"
    docker compose -f "$compose_file" down --remove-orphans >/dev/null 2>&1 || true
    rm -f "$status_file"
    echo "==> Starting dockurr/windows test container via Docker Compose..."
    local deadline="${AUTO_VHS_WINDOWS_TIMEOUT:-3600}"
    if ! run_with_deadline "$deadline" docker compose -f "$compose_file" up --abort-on-container-exit --exit-code-from windows-test; then
        echo "[WARN] Windows test container exited nonzero or timed out after ${deadline}s; checking guest status marker."
    fi

    local status=""
    if [ -f "$status_file" ]; then
        status="$(tr -d '\r\n' < "$status_file")"
    fi
    docker compose -f "$compose_file" down --remove-orphans >/dev/null 2>&1 || true

    if [ -z "$status" ]; then
        echo "[ERROR] Windows guest did not write $status_file."
        return 1
    fi

    case "$status" in
        passed)
            echo "==> Windows guest test status: passed"
            return 0
            ;;
        failed:*)
            echo "[ERROR] Windows guest test status: $status"
            return 1
            ;;
        *)
            echo "[ERROR] Unexpected Windows guest test status: $status"
            return 1
            ;;
    esac
}

run_macos() {
    check_apple_hardware
    check_kvm
    echo "==> Starting dockurr/macos test container via Docker Compose..."
    docker compose -f docker/docker-compose.macos.yml up --abort-on-container-exit --exit-code-from macos-test
}

usage() {
    echo "Usage: $0 [--ubuntu | --windows | --macos | --all]"
    exit 1
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    TARGET="${1:---all}"

    case "$TARGET" in
        --ubuntu)
            run_ubuntu
            ;;
        --windows)
            run_windows
            ;;
        --macos)
            run_macos
            ;;
        --all)
            run_ubuntu
            run_windows
            echo "==> macOS virtualized tests require a manual run: ./docker/run_dockurr_tests.sh --macos"
            ;;
        *)
            usage
            ;;
    esac
fi
