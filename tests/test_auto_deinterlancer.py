import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

# NOTE: No top-level import of auto_deinterlancer to ensure coverage starts first.
# We use the 'ad' fixture from conftest.py instead.


def test_parse_ffmpeg_time(ad):
    """Test FFmpeg time EXTRACTION."""
    # (seconds, time_str, speed_str)
    assert ad.parse_ffmpeg_time("time=00:00:10.50 speed=1.5x") == (10.50, "00:00:10.50", "1.5x")
    assert ad.parse_ffmpeg_time(None) == (None, None, None)


def test_load_config(ad):
    """Test config loading logic."""
    with patch('auto_deinterlancer.yaml.safe_load') as mock_load:
        with patch('builtins.open', new_callable=mock_open, read_data="encoder: prores"):
            with patch('os.path.exists', return_value=True):
                mock_load.return_value = {"encoder": "prores"}
                config = ad.load_config()
                assert config["encoder"] == "prores"


def test_get_fps_duration_start(ad):
    """Test video property detection."""
    with patch('subprocess.check_output') as mock_cmd:
        mock_cmd.side_effect = [b"30000/1001", b"120.5", b"1.5"]
        assert pytest.approx(ad.get_fps("v.mp4"), 0.01) == 29.97
        assert ad.get_duration("v.mp4") == 120.5
        assert ad.get_start_time("v.mp4") == 1.5

        # Test exceptions in detection
        mock_cmd.side_effect = Exception("failed")
        assert ad.get_fps("v.mp4") == 29.97


def test_get_vpy_info(ad):
    """Test vspipe --info parsing."""
    mock_output = b"Output Index: 0\nType: Video\nFrames: 1000\nFPS: 30000/1001 (29.970 fps)\nFormat Name: RGB24"
    venv = "c:/venv"
    with patch('subprocess.check_output', return_value=mock_output):
        frames, fps = ad.get_vpy_info("vspipe", "script.vpy", venv)
        assert frames == 1000
        assert pytest.approx(fps, 0.001) == 29.970


def test_detect_hardware_logic(ad):
    """Test hardware detection profiles."""
    with patch('os.cpu_count', return_value=12):
        with patch('shutil.which', return_value="/bin/nvidia-smi"):
            with patch('subprocess.check_output', return_value=b"NVIDIA"):
                settings = ad.detect_hardware_settings()
                assert settings["cpu_threads"] == 12

    # Robust Mock for ctypes Memory Status
    mock_ctypes = MagicMock()
    mock_kernel32 = MagicMock()
    mock_ctypes.windll.kernel32 = mock_kernel32
    mock_ctypes.sizeof.return_value = 128
    mock_ctypes.c_ulong = MagicMock()
    mock_ctypes.c_ulonglong = MagicMock()
    mock_ctypes.Structure = type('Structure', (), {'_fields_': []})

    def mock_GlobalMemoryStatusEx_64(ref):
        ref.ullTotalPhys = 64 * (1024**3)
        return True

    mock_kernel32.GlobalMemoryStatusEx.side_effect = mock_GlobalMemoryStatusEx_64

    # Patch ctypes and byref
    with patch.dict('sys.modules', {'ctypes': mock_ctypes}):
        with patch('ctypes.byref', side_effect=lambda x: x):
            with patch('os.cpu_count', return_value=32):
                with patch('shutil.which', return_value="/bin/nvidia-smi"):
                    with patch('subprocess.check_output', return_value=b"NVIDIA RTX 5090"):
                        settings = ad.detect_hardware_settings()
                        # 64GB * 0.5 * 1024 = 32768
                        assert settings["ram_cache_mb"] == 32768
                        assert settings["use_gpu_opencl"] is True

            # Test Mid-Range RAM (32GB -> 35% Cache)
            def mock_GlobalMemoryStatusEx_32(ref):
                ref.ullTotalPhys = 32 * (1024**3)
                return True
            mock_kernel32.GlobalMemoryStatusEx.side_effect = mock_GlobalMemoryStatusEx_32

            with patch('os.cpu_count', return_value=16):
                with patch('shutil.which', return_value="/bin/rocm-smi"):
                    with patch('subprocess.check_output', return_value=b"AMD Radeon"):
                        settings = ad.detect_hardware_settings()
                        # 32GB * 0.35 * 1024 = 11468.8 -> 11468
                        assert settings["ram_cache_mb"] == 11468

            # Test fallback/exception path
            mock_kernel32.GlobalMemoryStatusEx.side_effect = Exception("Ctypes Error")
            settings = ad.detect_hardware_settings()
            assert settings["ram_cache_mb"] == 4000


def test_get_input_files_cli(ad):
    """Test CLI arguments."""
    with patch('auto_deinterlancer.Path.is_file', return_value=True):
        with patch('auto_deinterlancer.Path.is_dir', return_value=False):
            with patch('sys.argv', ['script.py', 'test.mkv']):
                files = ad._get_input_files()
                assert len(files) == 1


def test_get_input_files_interactive(ad):
    """Test interactive inputs and quoted cleaning."""
    with patch('builtins.input') as mock_input:
        with patch('auto_deinterlancer.Path') as mock_path_class:
            mock_input.return_value = '"tape.mp4"'
            mock_p = mock_path_class.return_value
            mock_p.is_file.return_value = True
            mock_p.suffix = ".mp4"
            mock_p.name = "tape.mp4"
            with patch('sys.argv', ['script.py']):
                files = ad._get_input_files()
                assert len(files) == 1


def test_create_vpy_script(ad):
    """Test VPY script generation."""
    with patch('builtins.open', new_callable=mock_open) as mock_f:
        with patch('os.path.getsize', return_value=100):
            with patch('os.path.abspath', side_effect=lambda x: str(x)):
                with patch('auto_deinterlancer.get_fps', return_value=25.0):
                    ad.create_vpy_script("in.mp4", "out.vpy", "QTGMC")
                    content = mock_f().write.call_args_list[0][0][0].decode('utf-8')
                    assert "core.ffms2.Source" in content


def test_process_video_resume_final(ad):
    """Test skipping if final output exists."""
    with patch('auto_deinterlancer.get_duration', return_value=10.0):
        with patch('auto_deinterlancer.get_start_time', return_value=0.0):
            with patch('os.path.getsize', return_value=5000):
                input_p = Path("test.mp4")
                # path.exists side_effect: [Output Exists]
                with patch('auto_deinterlancer.Path.exists', side_effect=[True]):
                    with patch('auto_deinterlancer.Path.stat') as mock_stat:
                        mock_stat.return_value.st_size = 5000
                        with patch('builtins.print'):
                            with patch('auto_deinterlancer.log_info'):
                                ad.process_video(input_p)


def test_process_video_pipeline(ad):
    """Test Single-Pass Pipeline (Mocked)."""
    # Mocks needed:
    # 1. get_duration (src video, src audio)
    # 2. get_start_time
    # 3. get_vpy_info (frames, fps)
    # 4. create_vpy_script
    # 5. shutil.which (vspipe, ffmpeg)
    # 6. Popen (vspipe, ffmpeg)
    # 7. cleanup_temp_files

    with patch('auto_deinterlancer.get_duration', return_value=100.0):
        with patch('auto_deinterlancer.get_start_time', return_value=0.0):
            with patch('auto_deinterlancer.get_vpy_info', return_value=(3000, 30.0)):  # 100s
                with patch('auto_deinterlancer.create_vpy_script'):
                    with patch('auto_deinterlancer.shutil.which', return_value="/bin/tool"):
                        with patch('auto_deinterlancer.cleanup_temp_files'):
                            with patch('os.path.exists', return_value=True):  # vspipe exists
                                with patch('subprocess.Popen') as mock_popen:
                                    with patch('auto_deinterlancer.log_info'), \
                                            patch('auto_deinterlancer.log_debug'):
                                        # Mock Popen instances
                                        p1 = MagicMock()
                                        p1.stderr.readline.return_value = b""
                                        p2 = MagicMock()
                                        p2.stderr.readline.side_effect = ["frame= 100 fps=30 time=00:00:10.00 speed=1.0x", "", ""]
                                        p2.poll.side_effect = [None, 0, 0]
                                        p2.returncode = 0

                                        mock_popen.side_effect = [p1, p2]

                                        input_p = Path("test.mp4")
                                        # Force output not exist so it runs
                                        with patch('auto_deinterlancer.Path.exists', side_effect=[False, False]):  # output check
                                            ad.process_video(input_p)

                                            # Verify TWO Popen calls (VSPipe, FFmpeg)
                                            assert mock_popen.call_count == 2

                                            # Verify FFmpeg command structure
                                            args, _ = mock_popen.call_args_list[1]
                                            cmd = args[0]
                                            assert "pipe:" in cmd
                                            assert "-filter_complex" in cmd


def test_update_progress_visual(ad):
    """Test progress bar logic (visual check via capture)."""
    with patch('sys.stderr') as mock_stderr:
        ad.update_progress(50.0, "Testing", "00:00:10", "1.0x")
        # Check call args
        args = mock_stderr.write.call_args[0][0]
        assert "50.00%" in args
        assert "Testing" in args
        assert "00:00:10" in args
        assert "1.0x" in args


def test_main_startup(ad):
    """Test main entry point."""
    with patch('auto_deinterlancer.check_requirements'):
        with patch('auto_deinterlancer._get_input_files', return_value=[Path("vhs.mp4")]):
            with patch('auto_deinterlancer.process_video') as mock_process:
                with patch('builtins.input'):
                    with patch('auto_deinterlancer.sys.argv', ["script.py"]):
                        ad.main()
                        assert mock_process.called


def test_get_input_files_comprehensive(ad):
    """Test folder scanning, defaults, and interactive logic."""
    with patch('auto_deinterlancer.sys.argv', ["script.py"]):
        # 1. Default to "input" folder
        with patch('builtins.input', return_value=""):
            with patch('auto_deinterlancer.Path.exists', return_value=True):
                with patch('auto_deinterlancer.Path.is_dir', return_value=True):
                    with patch('auto_deinterlancer.Path.iterdir') as mock_iter:
                        f1 = MagicMock()
                        f1.is_file.return_value = True
                        f1.suffix = ".mp4"
                        f1.name = "vid.mp4"
                        mock_iter.return_value = [f1]

                        files = ad._get_input_files()
                        assert len(files) == 1
                        assert files[0].name == "vid.mp4"

        # 2. Interactive Folder Scan
        with patch('builtins.input', return_value="my_folder"):
            with patch('auto_deinterlancer.Path.is_file', return_value=False):
                with patch('auto_deinterlancer.Path.is_dir', return_value=True):
                    with patch('auto_deinterlancer.Path.iterdir') as mock_iter:
                        f1 = MagicMock()
                        f1.is_file.return_value = True
                        f1.suffix = ".mkv"
                        f1.name = "movie.mkv"

                        f2 = MagicMock()
                        f2.is_file.return_value = True
                        f2.suffix = ".mov"
                        f2.name = "movie_deinterlaced.mov"

                        mock_iter.return_value = [f1, f2]

                        files = ad._get_input_files()
                        # Test that it filters out 'deinterlaced' files
                        assert len(files) == 1
                        assert files[0].name == "movie.mkv"

        # 3. Quoted String handling
        with patch('builtins.input', return_value='"quoted_file.mp4"'):
            with patch('auto_deinterlancer.Path.is_file', return_value=True):
                files = ad._get_input_files()
                assert len(files) == 1


def test_get_start_time_exception(ad):
    with patch('subprocess.check_output', side_effect=Exception("Fail")):
        assert ad.get_start_time("f.mp4") == 0.0


def test_update_progress_logic(ad):
    # Test valid stats
    with patch('sys.stderr') as mock_stderr:
        ad.update_progress(10.0, "Test", "00:00:01")
        assert "10.00%" in mock_stderr.write.call_args[0][0]
    # Test None stats
    with patch('sys.stderr') as mock_stderr:
        ad.update_progress(20.0, "Test")
        assert "20.00%" in mock_stderr.write.call_args[0][0]


def test_setup_environment(ad):
    """Test environment setup logic explicitly."""
    # Mock os.path.exists to trigger branches
    with patch('auto_deinterlancer.os.path.exists', side_effect=lambda x: True):
        with patch('auto_deinterlancer.os.environ', {}):
            ad.setup_environment()
