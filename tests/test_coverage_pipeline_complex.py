import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import modules.pipeline as pipeline
from modules.config import CONFIG, ENCODER

def test_get_output_path_variations():
    """Test _get_output_path with different encoders."""
    input_p = Path("test.mp4")
    
    # helper to reset config
    
    # 1. ProRes
    with patch('modules.pipeline.ENCODER', 'prores'):
        with patch.dict(CONFIG, {"output_suffix": "_prores"}):
            out = pipeline._get_output_path(input_p)
            assert out.name == "test_prores.mov"
            
    # 2. AV1
    with patch('modules.pipeline.ENCODER', 'av1'):
        with patch.dict(CONFIG, {"output_suffix_av1": "_av1"}):
            out = pipeline._get_output_path(input_p)
            assert out.name == "test_av1.mkv"

def test_run_encoding_pipeline_progress_parsing():
    """Test _run_encoding_pipeline parsing of ffmpeg output."""
    vspipe_cmd = ["vspipe", "-", "-"]
    ffmpeg_cmd = ["ffmpeg", "-i", "-"]
    temp_script = Path("temp.vpy")
    duration_sec = 100.0
    
    # Mock subprocess objects
    p_vspipe = MagicMock()
    p_vspipe.stdout = MagicMock() # has close()
    p_vspipe.stderr = MagicMock() # for log thread
    p_vspipe.wait.return_value = None
    
    p_ffmpeg = MagicMock()
    p_ffmpeg.returncode = 0
    p_ffmpeg.wait.return_value = None
    
    # Simulate stderr lines from ffmpeg
    # We need to mock iteration over p_ffmpeg.stderr
    # pipeline.py uses: stderr_reader = io.TextIOWrapper(p_ffmpeg.stderr, ...)
    # But checking the code: 
    #   if p_ffmpeg.stderr:
    #       stderr_reader = io.TextIOWrapper(p_ffmpeg.stderr...)
    # We can mock TextIOWrapper or just make p_ffmpeg.stderr iterable if we mock io.TextIOWrapper?
    # Easier: Mock io.TextIOWrapper
    
    lines = [
        "frame=  100 fps= 25 q=-1.0 size= 1024kB time=00:00:04.00 bitrate=2000.0kbits/s speed= 1.0x",
        "frame=  200 fps= 30 q=-1.0 size= 2048kB time=00:00:08.00 bitrate=2000.0kbits/s speed= 2.0x",
        "some other line",
        "frame=  300 fps= 30 q=-1.0 size= 3072kB time=00:00:12.00 bitrate=2000.0kbits/s speed=N/A" # coverage for speed exceptions
    ]
    
    with patch('subprocess.Popen', side_effect=[p_vspipe, p_ffmpeg]):
        with patch('modules.pipeline.get_vspipe_env', return_value={}):
            with patch('threading.Thread'):
                with patch('io.TextIOWrapper', return_value=lines): # Make it iterable
                    with patch('modules.pipeline.update_progress') as mock_update:
                        with patch('os.remove'):
                             with patch('pathlib.Path.exists', return_value=True):
                                ret = pipeline._run_encoding_pipeline(vspipe_cmd, ffmpeg_cmd, temp_script, duration_sec)
                                assert ret is True
                                assert mock_update.call_count >= 2
