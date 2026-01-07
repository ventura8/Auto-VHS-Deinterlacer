from unittest.mock import patch

# NOTE: No top-level import of auto_deinterlancer to ensure coverage starts first.
# We use the 'ad' fixture from conftest.py instead.


def test_update_progress_eta(ad):
    """Test update_progress with ETA string."""
    with patch('sys.stderr.write') as mock_write:
        with patch('sys.stderr.flush'):
            ad.update_progress(50, "Test", "00:01:00", "1.5x", "00:05:00")
            # Verify output format
            # [███████████████---------------] 50% | 00:01:00 | 1.5x | ETA: 00:05:00 | Test
            args = mock_write.call_args[0][0]
            # Match loosely
            assert "ETA" in args
            assert "00:05:00" in args
            assert "1.5x" in args
            assert "00:01:00" in args
