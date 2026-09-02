"""Tests validating Dockurr Docker and container configurations for Windows and macOS."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_compose_file(file_name: str) -> dict:
    """Load and parse docker compose yaml file."""
    compose_path = REPO_ROOT / "docker" / file_name
    assert compose_path.exists(), f"{file_name} must exist"
    with open(compose_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _assert_win_service(win_service: dict):
    """Assert Windows container service attributes."""
    assert win_service["image"] == ("dockurr/windows@sha256:0cff9eb0e7aee9953e55bc682852ca4fdca233145a58ae1ec94f0b0c01a2ed30")
    assert "/dev/kvm" in win_service["devices"]
    assert "/dev/net/tun" in win_service["devices"]
    assert "NET_ADMIN" in win_service["cap_add"]


def _assert_win_credentials(win_service: dict):
    """Assert that Dockurr receives its password from the caller environment."""
    expected_password = "${AUTO_VHS_WINDOWS_PASSWORD:?Set AUTO_VHS_WINDOWS_PASSWORD before starting the Windows test container}"
    assert win_service["environment"]["PASSWORD"] == expected_password


def _assert_docker_ignore():
    """Docker build context must exclude local repository artifacts."""
    ignored = set((REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    assert {".git", ".venv", ".VENV", "__pycache__/", "assets/", "input/", "output/"} <= ignored


def _assert_windows_status_flow(content: str):
    """Dockurr guest and host scripts agree on the status marker protocol."""
    required_text = {"windows_test_status.txt", "passed", "failed:*", "return 1"}
    assert all(text in content for text in required_text)


@pytest.mark.docker
@pytest.mark.dockurr
def test_docker_compose_windows_config():
    """Verify dockurr/windows docker-compose configuration structure."""
    config = _load_compose_file("docker-compose.windows.yml")
    assert "services" in config
    assert "windows-test" in config["services"]
    win_service = config["services"]["windows-test"]
    _assert_win_service(win_service)
    _assert_win_credentials(win_service)


def _assert_mac_service(mac_service: dict):
    """Assert macOS container service attributes."""
    assert mac_service["image"] == ("dockurr/macos@sha256:08d1bcaac74ad44d548b7ce683b3dded083512d2a0d26416f9a620b763f8ea3d")
    assert "/dev/kvm" in mac_service["devices"]
    assert "/dev/net/tun" in mac_service["devices"]


@pytest.mark.docker
@pytest.mark.dockurr
def test_docker_compose_macos_config():
    """Verify dockurr/macos docker-compose configuration structure."""
    config = _load_compose_file("docker-compose.macos.yml")
    assert "services" in config
    assert "macos-test" in config["services"]
    _assert_mac_service(config["services"]["macos-test"])


@pytest.mark.docker
@pytest.mark.dockurr
def test_dockurr_oem_script():
    """Verify OEM unattended batch script existence and contents."""
    oem_script = REPO_ROOT / "docker" / "oem" / "windows" / "install.bat"
    assert oem_script.exists(), "OEM install.bat must exist"
    content = oem_script.read_text(encoding="utf-8")
    required_text = {
        "install.ps1",
        "windows_test_status.txt",
        "call :fail installer",
        "call :fail dependencies",
        "call :fail tests",
        "call :fail missing-mount",
        "> Z:\\windows_test_status.txt echo passed",
    }
    assert all(text in content for text in required_text)


@pytest.mark.docker
def test_ubuntu_dockerfile_version():
    """Verify Ubuntu Dockerfile uses ubuntu:26.04 base image."""
    dockerfile = REPO_ROOT / "docker" / "Dockerfile.ubuntu"
    assert dockerfile.exists(), "docker/Dockerfile.ubuntu must exist"
    content = dockerfile.read_text(encoding="utf-8")
    assert "FROM ubuntu:26.04" in content
    assert ".venv/bin/pip install vapoursynth==79" in content
    assert 'ENV PATH="/workspace/.venv/bin:${PATH}"' in content
    _assert_docker_ignore()


@pytest.mark.docker
def test_batch_files_are_checked_out_with_crlf():
    """Windows batch files retain CRLF line endings when checked out on CI."""
    attributes = REPO_ROOT / ".gitattributes"
    assert attributes.exists()
    assert "*.bat text eol=crlf" in attributes.read_text(encoding="utf-8")


@pytest.mark.docker
def test_dockurr_all_requires_explicit_macos_run():
    """The aggregate runner must not block on the manual macOS VM workflow."""
    runner = (REPO_ROOT / "docker" / "run_dockurr_tests.sh").read_text(encoding="utf-8")
    all_branch = runner.split("    --all)", maxsplit=1)[1].split("    *)", maxsplit=1)[0]
    assert "run_ubuntu" in all_branch
    assert "run_windows" in all_branch
    assert "run_macos" not in all_branch
    _assert_windows_status_flow(runner)


def _filter_cmd_indices(commands: list[list[str]], keyword: str) -> list[int]:
    """Return indices of commands containing a keyword."""
    return [i for i, cmd in enumerate(commands) if keyword in cmd]


def _assert_down_up_down_command_order(invocations_text: str):
    """Verify that down --remove-orphans surrounds up in execution order."""
    commands_executed = [line.split() for line in invocations_text.splitlines()]
    down_indices = _filter_cmd_indices(commands_executed, "down")
    up_indices = _filter_cmd_indices(commands_executed, "up")

    assert len(down_indices) == 2
    assert len(up_indices) == 1
    assert down_indices[0] < up_indices[0] < down_indices[1]


@pytest.mark.docker
@pytest.mark.dockurr
def test_dockurr_windows_runner_cleans_up_containers_consecutively(monkeypatch, tmp_path):
    """Verify that run_windows tears down containers before and after every execution."""
    script_path = REPO_ROOT / "docker" / "run_dockurr_tests.sh"
    content = script_path.read_text(encoding="utf-8")
    assert 'docker compose -f "$compose_file" down --remove-orphans' in content

    shim_dir = tmp_path / "docker-shim"
    shim_dir.mkdir()
    shim = shim_dir / "docker"
    invocations = shim_dir / "invocations"
    shim.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{invocations}'\n"
        "case \"$*\" in *' compose -f '*) ;; esac\n"
        "case \"$*\" in *' up '*) echo passed > windows_test_status.txt;; esac\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    # The shell runner is executed through a Docker shim so its real commands are observed.
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to execute the POSIX Dockurr runner")
    result = subprocess.run(
        [bash, "-c", f"source '{script_path}'; check_kvm() {{ :; }}; run_windows"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and "/bin/bash" in result.stderr:
        pytest.skip("WSL bash is installed but no usable Linux distribution is available")
    result.check_returncode()

    _assert_down_up_down_command_order(invocations.read_text(encoding="utf-8"))
