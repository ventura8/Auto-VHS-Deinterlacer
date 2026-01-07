
import pytest
import sys
import os
import io
import logging
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path

# Use deferred imports to avoid top-level execution of modules.config hardware detection

def test_pipeline_interactive_input_interrupt():
    """Test KeyboardInterrupt in _get_interactive_input."""
    # Patch input before importing pipeline to be safe, though import happens inside
    with patch('builtins.input', side_effect=KeyboardInterrupt):
        from modules import pipeline
        files = pipeline._get_interactive_input(set(['.mp4']))
        assert files == []

def test_pipeline_audio_sync_logic():
    """Test _calculate_audio_sync logic branches."""
    from modules import pipeline
    
    # 1. drift too large
    with patch('modules.pipeline.get_duration') as mock_dur:
        mock_dur.side_effect = lambda f, s=None: 100.0 if 'a' in str(s) else 60.0
        val = pipeline._calculate_audio_sync(Path('test.mp4'), 60.0)
        assert val == 1.0

    # 2. negative drift (audio shorter)
    with patch('modules.pipeline.get_duration') as mock_dur:
        mock_dur.side_effect = lambda f, s=None: 50.0 
        with patch('modules.pipeline.log_info') as mock_log:
            val = pipeline._calculate_audio_sync(Path('test.mp4'), 60.0)
            assert val == 1.0
            # Check log message content if possible, or just that it didn't crash
            assert mock_log.called

def test_utils_project_root_frozen():
    """Test get_project_root when frozen."""
    # We need to unimport modules.utils if it's already imported?
    # No, get_project_root checks sys.frozen at runtime.
    from modules import utils
    
    with patch.object(sys, 'frozen', True, create=True):
        with patch.object(sys, 'executable', '/bin/exe'):
            assert utils.get_project_root() == '/bin'

def test_utils_parse_time_edge_cases():
    """Test parse_ffmpeg_time edge cases."""
    from modules import utils
    assert utils.parse_ffmpeg_time(None) == (None, None, None)
    assert utils.parse_ffmpeg_time("invalid") == (None, None, None)

def test_utils_cleanup_error():
    """Test cleanup_temp_files unlink error."""
    from modules import utils
    
    with patch('pathlib.Path.glob') as mock_glob:
        f = MagicMock()
        f.name = "test_intermediate.mkv"
        f.is_file.return_value = True
        f.unlink.side_effect = OSError("Access Denied")
        mock_glob.return_value = [f]
        
        # Should not raise
        utils.cleanup_temp_files(Path('.'), "test")

def test_vspipe_log_errors():
    """Test vspipe logging errors."""
    from modules import vspipe
    
    pipe = MagicMock()
    pipe.readline.side_effect = Exception("Read Error")
    vspipe.log_vspipe_output(pipe)

def test_entry_point_safety():
    """Try to import auto_deinterlancer without main execution."""
    # This is tricky because importing it might run it if it doesn't have if __name__ == "__main__"
    # But it does.
    # However, it imports modules.* at top level, which triggers hardware detect.
    # We just want to ensure it doesn't crash on import.
    import auto_deinterlancer
    assert hasattr(auto_deinterlancer, 'main')

def test_pipeline_run_encoding_read_error():
    from modules import pipeline
    
    vspipe_cmd = ["ls"]
    ffmpeg_cmd = ["ls"]
    
    with patch('subprocess.Popen') as mock_popen:
        p_vs = MagicMock()
        p_vs.stdout = MagicMock()
        
        p_ff = MagicMock()
        p_ff.stderr = io.BytesIO(b"bad") 
        p_ff.wait.return_value = 1
        p_ff.returncode = 1
        
        mock_popen.side_effect = [p_vs, p_ff]
        
        with patch('modules.pipeline.get_vspipe_env', return_value={}):
            with patch('threading.Thread'):
                 pipeline._run_encoding_pipeline(vspipe_cmd, ffmpeg_cmd, Path('t.vpy'), 100)

def test_vspipe_log_errors_specific():
    """Test vspipe logging specific exceptions."""
    from modules import vspipe
    pipe = MagicMock()
    pipe.readline.side_effect = ValueError("Shutdown error")
    vspipe.log_vspipe_output(pipe)

def test_vspipe_parse_info_malformed():
    """Test _parse_vspipe_info_output with malformed data."""
    from modules import vspipe
    
    # Frames: invalid
    t, f, w, h, fmt = vspipe._parse_vspipe_info_output("Frames: garbage")
    assert t is None
    
    # Width: invalid
    t, f, w, h, fmt = vspipe._parse_vspipe_info_output("Width: garbage")
    assert w is None

    # Height: invalid
    t, f, w, h, fmt = vspipe._parse_vspipe_info_output("Height: garbage")
    assert h is None

    # Format Name: (usually string, but maybe fails somehow if empty?)
    # The code does try/except ValueError for split probably
    t, f, w, h, fmt = vspipe._parse_vspipe_info_output("Format Name:") # split index error -> check if caught? 
    # Current code: line.split(":")[1] might index error if no colon, but startswith ensures colon existence?
    # No, startswith("Format Name:") ensures it starts with it. 
    # If line is "Format Name:", split(":") gives ["Format Name", ""].
    # So we need "Format Name: " with nothing?
    # Actually line 177: fmt = line.split(":")[1].strip()
    # It catches ValueError. split returns list, accessing [1] raises IndexError if not enough parts.
    # The code expects ValueError.
    pass

def test_vspipe_parse_info_fps_edge():
    """Test FPS parsing edge cases."""
    from modules import vspipe
    
    # FPS: garbage
    t, f, w, h, fmt = vspipe._parse_vspipe_info_output("FPS: garbage")
    assert f is None


