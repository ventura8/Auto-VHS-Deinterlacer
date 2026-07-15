"""Unit tests for user-facing progress output formatting."""

from unittest.mock import patch

# NOTE: No top-level import of auto_deinterlancer to ensure coverage starts first.
# We use the 'ad' fixture from conftest.py instead.


def _render_progress_output(ad) -> str:
    """Return captured progress output for one ETA-bearing progress update."""
    with patch("sys.stderr.write") as mock_write, patch("sys.stderr.flush"):
        ad.update_progress(50, "Test", "00:01:00", "1.5x", "00:05:00")
    return "".join(call.args[0] for call in mock_write.call_args_list)


def test_update_progress_eta(ad):
    """Test update_progress with ETA string."""
    args = _render_progress_output(ad)
    assert "ETA" in args
    assert "00:05:00" in args
    assert "1.5x" in args
    assert "00:01:00" in args
