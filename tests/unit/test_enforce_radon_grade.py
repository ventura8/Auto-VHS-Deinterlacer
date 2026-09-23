"""Tests for the radon gate's handling of untrusted command-line arguments.

SonarCloud's first analysis of main flagged enforce_radon_grade.py: targets
flowed straight into the radon command, where one starting with "-" would be
read as an option, and --summary-out was written wherever it pointed.
"""

import runpy
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "enforce_radon_grade.py"


def _load_radon_gate() -> dict:
    """Return the CI script's namespace; a non-"__main__" run name leaves main() uncalled."""
    return runpy.run_path(str(_SCRIPT), run_name="enforce_radon_grade")


@pytest.mark.parametrize("path_value", ["assets/radon_summary.md", "radon.md", "assets/../assets/radon.md"])
def test_summary_path_inside_the_working_tree_is_accepted(tmp_path, monkeypatch, path_value):
    """Paths that resolve inside the working tree are written where asked."""
    monkeypatch.chdir(tmp_path)
    resolve = _load_radon_gate()["_resolve_summary_path"]

    assert resolve(path_value) == (tmp_path / path_value).resolve()


@pytest.mark.parametrize("path_value", ["../escape.md", "assets/../../escape.md"])
def test_summary_path_escaping_the_working_tree_is_rejected(tmp_path, monkeypatch, path_value):
    """A path that climbs out of the working tree is refused before anything is written."""
    work = tmp_path / "repo"
    work.mkdir()
    monkeypatch.chdir(work)
    resolve = _load_radon_gate()["_resolve_summary_path"]

    with pytest.raises(ValueError, match="must stay inside"):
        resolve(path_value)


def test_absolute_summary_path_outside_the_working_tree_is_rejected(tmp_path, monkeypatch):
    """An absolute path elsewhere on disk is refused too."""
    work = tmp_path / "repo"
    work.mkdir()
    monkeypatch.chdir(work)
    resolve = _load_radon_gate()["_resolve_summary_path"]

    with pytest.raises(ValueError, match="must stay inside"):
        resolve(str(tmp_path / "escape.md"))


def test_no_summary_path_means_no_summary():
    """Omitting --summary-out writes nothing."""
    assert _load_radon_gate()["_resolve_summary_path"](None) is None


def test_option_like_targets_are_rejected():
    """A target that radon would parse as an option is refused, not analysed."""
    reject = _load_radon_gate()["_reject_option_like_targets"]

    reject(["modules", "auto_deinterlancer.py"])
    with pytest.raises(ValueError, match="--output-file=x"):
        reject(["modules", "--output-file=x"])


@pytest.mark.parametrize(
    ("runner", "metric", "stdout"), [("run_radon", "cc", "{}"), ("run_radon_mi", "mi", '{"modules/x.py": {"mi": 90.0, "rank": "A"}}')]
)
def test_radon_commands_end_option_parsing_before_targets(monkeypatch, runner, metric, stdout):
    """Both radon invocations pass "--" so every target is taken as a path."""
    gate = _load_radon_gate()
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(gate["subprocess"], "run", fake_run)
    monkeypatch.setitem(gate, "_ensure_mi_targets_represented", lambda *_args: None)
    gate[runner](["modules"])

    first_argument = commands[0].index(metric) + 1
    assert commands[0][first_argument:] == ["--json", "--", "modules"]


def test_prepare_run_stops_with_status_two_on_bad_arguments(tmp_path, monkeypatch, capsys):
    """Bad arguments exit with status 2 and name the problem on stderr."""
    monkeypatch.chdir(tmp_path)
    prepare = _load_radon_gate()["_prepare_run"]

    assert prepare(["-x"], None)[0] == 2
    assert prepare(["."], "../escape.md")[0] == 2
    assert "must stay inside" in capsys.readouterr().err
