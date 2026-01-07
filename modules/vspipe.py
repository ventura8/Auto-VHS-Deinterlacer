import os
import sys
import subprocess
from modules.utils import log_debug, log_error, get_fps, get_vspipe_env, get_project_root
from modules.config import CONFIG, HW_SETTINGS, FIELD_ORDER, TV_STANDARD

# ==============================================================================
# VAPOURSYNTH SCRIPT GENERATOR
# ==============================================================================


def log_vspipe_output(pipe):
    """Monitors vspipe stderr for errors and progress."""
    try:
        # Use a sentinel that works for both bytes and strings
        for line in iter(pipe.readline, b''):
            if not line:
                break
            if isinstance(line, bytes):
                line_str = line.decode('utf-8', errors='replace').strip()
            else:
                line_str = line.strip()

            if line_str:
                # Log ALL vspipe output to file for debugging
                log_debug(f"[VSPIPE] {line_str}")
                # Also log errors explicitly
                if any(x in line_str for x in ["Script execution failed", "Error", "Failed"]):
                    log_error(f"[VSPIPE ERROR] {line_str}")
    except (ValueError, RuntimeError, AttributeError):
        # Handle cases where logging fails during interpreter shutdown
        pass
    except Exception:
        pass


def _get_vpy_header(venv_root, portable_root, site_paths, current_root):
    """Generates the VPY script header with imports and paths."""
    lines = [
        "import sys", "import os",
        f"sys.path.insert(0, r'{current_root}')"
    ]
    for p in site_paths:
        lines.append(f"sys.path.append(r'{p}')")
    
    # Ensure portable VS scripts (havsfunc, mvsfunc) are findable
    lines.append(f"sys.path.append(r'{portable_root}')")

    lines.append("if hasattr(os, 'add_dll_directory'):")
    lines.append(f"    try: os.add_dll_directory(r'{portable_root}')")
    lines.append("    except: pass")

    plugin_dir_check = os.path.join(venv_root, "vs", "plugins").replace("\\", "/")
    if not os.path.exists(plugin_dir_check):
        plugin_dir_check = os.path.join(venv_root, "vs", "vs-plugins").replace("\\", "/")

    if os.path.exists(plugin_dir_check):
        lines.append(f"    try: os.add_dll_directory(r'{plugin_dir_check}')")
        lines.append("    except: pass")

    mvs_path = f"{current_root}/mvsfunc"
    if os.path.exists(mvs_path):
        lines.append(f"sys.path.append(r'{mvs_path}')")

    lines.extend(["import vapoursynth as vs", "import havsfunc as haf", "core = vs.core"])
    return lines


def _get_plugin_loading_lines(venv_root):
    """Generates plugin loading commands for the VPY script."""
    plugin_dir = os.path.join(venv_root, "vs", "plugins")
    if not os.path.exists(plugin_dir):
        plugin_dir = os.path.join(venv_root, "vs", "vs-plugins")

    essential = [
        "ffms2.dll", "libmvtools.dll", "libnnedi3.dll", "NNEDI3CL.dll", "LSMASHSource.dll",
        "neo-fft3d.dll", "RemoveGrainVS.dll", "fmtconv.dll", "MiscFilters.dll",
        "EEDI3.dll", "EEDI3m.dll", "vsznedi3.dll"
    ]
    plugin_lines = []

    core_plugin_dir = os.path.join(venv_root, "vs", "coreplugins")
    if os.path.exists(core_plugin_dir):
        avs_compat = os.path.join(core_plugin_dir, "AvsCompat.dll")
        if os.path.exists(avs_compat):
            avs_compat_path = avs_compat.replace('\\', '/')
            plugin_lines.append(f"try: core.std.LoadPlugin(r'{avs_compat_path}')\nexcept: pass")

    for p_name in essential:
        p_path = os.path.join(plugin_dir, p_name).replace("\\", "/")
        if os.path.exists(p_path):
            plugin_lines.append(f"try: core.std.LoadPlugin(r'{p_path}')\nexcept: pass")
    return plugin_lines


def create_vpy_script(input_file, output_script, mode, override_settings=None):
    """Generates a VapourSynth script based on the selected mode."""
    current_settings = override_settings if override_settings else HW_SETTINGS
    safe_input = os.path.abspath(input_file).replace("\\", "/").strip()
    current_root = os.getcwd().replace("\\", "/").strip()
    base_dir = get_project_root()
    venv_root = os.path.join(base_dir, ".venv").replace("\\", "/")

    site_paths = [p.replace("\\", "/").strip() for p in sys.path if "site-packages" in p and "venv" in p]
    portable_root = f"{venv_root}/vs"
    if f"{portable_root}/Lib/site-packages" not in site_paths:
        site_paths.append(f"{portable_root}/Lib/site-packages")

    lines = _get_vpy_header(venv_root, portable_root, site_paths, current_root)
    lines.append(f"core.num_threads = {current_settings['cpu_threads']}")
    lines.append(f"core.max_cache_size = {current_settings['ram_cache_mb']}\n")
    lines.extend(_get_plugin_loading_lines(venv_root))

    lines.append("if hasattr(core, 'eedi3') and not hasattr(core, 'eedi3m'):")
    lines.append("    core.eedi3m = core.eedi3\n")

    fps_logic = TV_STANDARD if TV_STANDARD != "auto" else ("pal" if abs(get_fps(safe_input) - 25.0) < 0.5 else "ntsc")
    fps_num, fps_den = (25, 1) if fps_logic == "pal" else (30000, 1001)

    lines.append(f"clip = core.ffms2.Source(r'{safe_input}', fpsnum={fps_num}, fpsden={fps_den})")
    lines.append("clip = core.resize.Point(clip, format=vs.YUV420P16)\n")

    qtgmc_params = CONFIG.get("qtgmc_settings", {})
    qtgmc_args = {
        "Preset": qtgmc_params.get("Preset", "Very Slow"), "InputType": 0,
        "TFF": (FIELD_ORDER == "tff"), "SourceMatch": qtgmc_params.get("SourceMatch", 3),
        "Lossless": qtgmc_params.get("Lossless", 2), "TR2": 3,
        "EZDenoise": qtgmc_params.get("EZDenoise", 0.0), "NoiseProcess": qtgmc_params.get("NoiseProcess", 0),
        "Sharpness": qtgmc_params.get("Sharpness", 0.0), "FPSDivisor": 1,
    }
    if current_settings["use_gpu_opencl"]:
        qtgmc_args["EdiMode"] = "NNEDI3CL"

    lines.append("clip = haf.QTGMC(clip, **" + str(qtgmc_args) + ")")
    lines.append("clip.set_output()")

    with open(output_script, "wb") as f:
        f.write("\n".join(lines).encode("utf-8") + b"\n")

    # 4. Binary Write
    log_debug(f"[DEBUG] Generating VPY for: {safe_input}")
    output_content = "\n".join(lines)
    with open(output_script, "wb") as f:
        f.write(output_content.encode("utf-8"))
        f.write(b"\n")

    log_debug(f"[DEBUG] VPY saved to: {output_script} (Size: {os.path.getsize(output_script)})")


def _parse_vspipe_info_output(output):
    """Parses the output of vspipe --info for frames, FPS, width, height, and format."""
    frames = None
    fps = None
    width = None
    height = None
    fmt = None

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Frames:"):
            try:
                frames = int(line.split(":")[1].strip())
            except ValueError:
                pass
        elif line.startswith("Width:"):
            try:
                width = int(line.split(":")[1].strip())
            except ValueError:
                pass
        elif line.startswith("Height:"):
            try:
                height = int(line.split(":")[1].strip())
            except ValueError:
                pass
        elif line.startswith("Format Name:"):
            try:
                fmt = line.split(":")[1].strip()
            except ValueError:
                pass
        elif line.startswith("FPS:"):
            # Format: FPS: 30000/1001 (29.970 fps)
            try:
                parts = line.split(":")[1].split("(")[0].strip()
                if "/" in parts:
                    num, den = map(int, parts.split("/"))
                    fps = num / den
                else:
                    fps = float(parts)
            except Exception:
                pass
    return frames, fps, width, height, fmt


def get_vpy_info(vspipe_exe, script_path, venv_root):
    """
    Runs vspipe --info to get frame count, FPS, and format.
    Returns: (frames, fps, width, height, fmt) or (None, None, None, None, None) on error.
    """
    try:
        env = get_vspipe_env()
        # Use info mode
        cmd = [vspipe_exe, "--info", script_path]
        output = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=30).decode()
        return _parse_vspipe_info_output(output)

    except subprocess.CalledProcessError as e:
        log_error(f"[VSPIPE ERROR] Info check failed: {e.output.decode()}")
        return None, None, None, None, None
    except Exception as e:
        log_error(f"[VSPIPE ERROR] Info check failed: {e}")
        return None, None, None, None, None
