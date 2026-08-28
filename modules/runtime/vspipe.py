"""VapourSynth script generation and vspipe integration helpers."""

import os
import subprocess
import sys

from modules.core.config import CONFIG, FIELD_ORDER, HW_SETTINGS, TV_STANDARD
from modules.core.utils import (
    _get_vapoursynth_plugin_dir,
    get_fps,
    get_project_root,
    get_vspipe_env,
    is_python_vspipe_launcher,
    log_debug,
    log_error,
    log_info,
    resolve_venv_root,
)

# ==============================================================================
# VAPOURSYNTH SCRIPT GENERATOR
# ==============================================================================

VSPIPE_ERROR_TOKENS = ["Script execution failed", "Error", "Failed"]
ESSENTIAL_PLUGINS = [
    "ffms2.dll",
    "libmvtools.dll",
    "libnnedi3.dll",
    "NNEDI3CL.dll",
    "LSMASHSource.dll",
    "neo-fft3d.dll",
    "RemoveGrainVS.dll",
    "fmtconv.dll",
    "MiscFilters.dll",
    "EEDI3.dll",
    "EEDI3m.dll",
    "vsznedi3.dll",
]


def _decode_vspipe_line(line):
    """Normalize a vspipe stderr line into a stripped string."""
    if isinstance(line, bytes):
        return line.decode("utf-8", errors="replace").strip()
    return line.strip()


def _is_vspipe_error(line_str: str) -> bool:
    """Return whether a vspipe stderr line indicates an error."""
    return any(token in line_str for token in VSPIPE_ERROR_TOKENS)


def _handle_vspipe_log_line(line_str: str):
    """Write a normalized vspipe log line to debug and error channels."""
    if not line_str:
        return
    log_debug(f"[VSPIPE] {line_str}")
    if _is_vspipe_error(line_str):
        log_error(f"[VSPIPE ERROR] {line_str}")


def log_vspipe_output(pipe):
    """Monitors vspipe stderr for errors and progress."""
    try:
        # Use a sentinel that works for both bytes and strings
        for line in iter(pipe.readline, b""):
            if not line:
                break
            _handle_vspipe_log_line(_decode_vspipe_line(line))
    except (ValueError, RuntimeError, AttributeError, OSError):
        pass


def _resolve_vspipe_plugin_dir(venv_root):
    """Return the first existing vspipe plugin directory under the venv."""
    vs_root = os.path.join(venv_root, "vs")
    return _get_vapoursynth_plugin_dir(vs_root).replace("\\", "/")


def _to_python_path_literal(path_value):
    """Return a safe Python string literal for an embedded filesystem path."""
    return repr(path_value)


def _append_vpy_path(lines, path_value):
    """Append a sys.path entry only when the path exists."""
    if os.path.exists(path_value):
        lines.append(f"sys.path.append({_to_python_path_literal(path_value)})")


def _get_vpy_header(venv_root, portable_root, site_paths, current_root):
    """Generates the VPY script header with imports and paths."""
    lines = ["import sys", "import os", "import hashlib", "import tempfile", f"sys.path.insert(0, {_to_python_path_literal(current_root)})"]
    for p in site_paths:
        lines.append(f"sys.path.append({_to_python_path_literal(p)})")

    # Ensure portable VS scripts (havsfunc, mvsfunc) are findable
    lines.append(f"sys.path.append({_to_python_path_literal(portable_root)})")

    lines.append("_DLL_DIRECTORY_HANDLES = []")
    lines.append("if hasattr(os, 'add_dll_directory'):")
    lines.append(f"    try: _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory({_to_python_path_literal(portable_root)}))")
    lines.append("    except: pass")

    plugin_dir_check = _resolve_vspipe_plugin_dir(venv_root)

    if os.path.exists(plugin_dir_check):
        lines.append(f"    try: _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory({_to_python_path_literal(plugin_dir_check)}))")
        lines.append("    except: pass")

    _append_vpy_path(lines, f"{current_root}/mvsfunc")

    lines.extend(
        [
            "import vapoursynth as vs",
            "if not hasattr(vs, 'get_core'): vs.get_core = lambda: vs.core",
            "import havsfunc as haf",
            "core = vs.core",
        ]
    )
    return lines


def _append_load_plugin(plugin_lines, plugin_path):
    """Append a guarded LoadPlugin command for an existing plugin file."""
    if os.path.exists(plugin_path):
        plugin_lines.append(f"try: core.std.LoadPlugin({_to_python_path_literal(plugin_path)})\nexcept: pass")


def _first_existing_plugin(plugin_dir: str, file_names: list[str]) -> str | None:
    """Return the first plugin path that exists in a directory."""
    for file_name in file_names:
        candidate = os.path.join(plugin_dir, file_name)
        if os.path.exists(candidate):
            return candidate.replace("\\", "/")
    return None


def _resolve_plugin_stems(base_name: str) -> tuple[str, ...]:
    """Resolve normalized stem and any known aliases for a plugin base name."""
    stem = base_name.split(".")[0].lower().removeprefix("lib")
    if stem == "lsmashsource":
        return (stem, "vslsmashsource")
    if stem == "removegrainvs":
        return (stem, "removegrain")
    return (stem,)


def _generate_plugin_candidates(base_name: str) -> list[str]:
    """Generate list of possible platform filename candidates for a plugin."""
    stems = _resolve_plugin_stems(base_name)
    candidates = [base_name]
    for s in stems:
        candidates.extend(
            [
                f"{s}.dll",
                f"lib{s}.dll",
                f"{s}.so",
                f"lib{s}.so",
                f"{s}.dylib",
                f"lib{s}.dylib",
            ]
        )
    return candidates


def _generate_versioned_plugin_prefixes(base_name: str) -> tuple[str, ...]:
    """Return ordered shared-library prefixes for versioned plugin filenames."""
    stems = _resolve_plugin_stems(base_name)
    return tuple(prefix for s in stems for prefix in (f"lib{s}.so.", f"{s}.so."))


def _find_plugin_candidate(plugin_dir: str, base_name: str) -> str | None:
    """Find the full path to a plugin file matching base name across platform extensions."""
    return _first_existing_plugin(plugin_dir, _generate_plugin_candidates(base_name))


def _get_plugin_search_dirs(venv_root: str) -> list[str]:
    """Return ordered list of directories to search for VapourSynth plugins."""
    dirs = [_resolve_vspipe_plugin_dir(venv_root)]
    if sys.platform != "win32":
        dirs.extend(
            [
                "/usr/lib/vapoursynth",
                "/usr/lib/x86_64-linux-gnu/vapoursynth",
                "/usr/lib/aarch64-linux-gnu/vapoursynth",
                "/usr/local/lib/vapoursynth",
                "/opt/homebrew/lib/vapoursynth",
            ]
        )
    return [d for d in dirs if os.path.exists(d)]


def _list_normalized_dir_entries(dir_path: str) -> set[str]:
    """Return a directory's entry names in normalized case, empty when unreadable."""
    try:
        return {os.path.normcase(name) for name in os.listdir(dir_path)}
    except OSError:
        return set()


def _find_exact_plugin_entry(entries: set[str], candidates: list[str]) -> str | None:
    """Return the first exact candidate present in a normalized directory listing."""
    for candidate in candidates:
        if os.path.normcase(candidate) in entries:
            return candidate
    return None


def _find_versioned_plugin_entry(entries: set[str], prefixes: tuple[str, ...]) -> str | None:
    """Return the first versioned shared-library entry matching an ordered prefix."""
    for prefix in prefixes:
        for entry in sorted(entries):
            if entry.startswith(os.path.normcase(prefix)):
                return entry
    return None


def _find_plugin_in_dirs(search_dirs: list[str], plugin_name: str) -> str | None:
    """Find the first matching plugin path across candidate search directories.

    Each directory is listed once and matched against the generated candidates,
    which avoids one stat call per candidate per directory. ``os.path.normcase``
    keeps the Windows case-insensitive lookup that ``os.path.exists`` provided.
    """
    candidates = _generate_plugin_candidates(plugin_name)
    versioned_prefixes = _generate_versioned_plugin_prefixes(plugin_name)
    for p_dir in search_dirs:
        entries = _list_normalized_dir_entries(p_dir)
        plugin_entry = _find_exact_plugin_entry(entries, candidates)
        if plugin_entry is None:
            plugin_entry = _find_versioned_plugin_entry(entries, versioned_prefixes)
        if plugin_entry:
            return os.path.join(p_dir, plugin_entry).replace("\\", "/")
    return None


def _resolve_core_plugin_dir(venv_root: str) -> str | None:
    """Return the first available portable VapourSynth core-plugin directory."""
    core_root = os.path.join(venv_root, "vs")
    for name in ("vs-coreplugins", "coreplugins"):
        candidate = os.path.join(core_root, name)
        if os.path.exists(candidate):
            return candidate
    return None


def _get_plugin_loading_lines(venv_root):
    """Generates plugin loading commands for the VPY script."""
    search_dirs = _get_plugin_search_dirs(venv_root)
    plugin_lines = []

    core_plugin_dir = _resolve_core_plugin_dir(venv_root)
    if core_plugin_dir:
        avs_compat = _find_plugin_candidate(core_plugin_dir, "AvsCompat.dll")
        if avs_compat:
            _append_load_plugin(plugin_lines, avs_compat)

    for p_name in ESSENTIAL_PLUGINS:
        p_path = _find_plugin_in_dirs(search_dirs, p_name)
        if p_path:
            _append_load_plugin(plugin_lines, p_path)
    return plugin_lines


def _get_vpy_site_paths(venv_root):
    """Collect site-packages paths needed by the generated VPY script."""
    site_paths = [path for path in (_normalize_site_path(p) for p in sys.path) if _is_venv_site_packages_path(path)]
    portable_site_packages = _get_portable_site_packages_path(venv_root)
    if portable_site_packages not in site_paths:
        site_paths.append(portable_site_packages)
    return site_paths


def _normalize_site_path(path_value: str) -> str:
    """Normalize one path for VPY sys.path emission."""
    return path_value.replace("\\", "/").strip()


def _is_venv_site_packages_path(path_value: str) -> bool:
    """Return whether a path looks like a venv site-packages location."""
    lowered = path_value.lower()
    return "site-packages" in lowered and "venv" in lowered


def _get_portable_site_packages_path(venv_root: str) -> str:
    """Build the portable .VENV site-packages path from the active venv root."""
    venv_parent = os.path.dirname(venv_root)
    base_name = os.path.basename(venv_root).lower()
    # Check Unix layout first if not on Windows
    if sys.platform != "win32":
        py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        unix_path = os.path.join(venv_root, "lib", py_ver, "site-packages")
        if os.path.exists(unix_path):
            return unix_path.replace("\\", "/")

    portable_venv_root = os.path.join(venv_parent, ".VENV") if base_name == ".venv" else venv_root
    return os.path.join(portable_venv_root, "Lib", "site-packages").replace("\\", "/")


def _append_runtime_settings(lines, current_settings):
    """Append thread and cache settings to the generated VPY script."""
    num_threads = int(current_settings["cpu_threads"])
    max_cache_size = int(current_settings["ram_cache_mb"])
    lines.append(f"core.num_threads = {num_threads}")
    lines.append(f"core.max_cache_size = {max_cache_size}\n")


def _resolve_fps_logic(safe_input):
    """Pick PAL or NTSC timing for the source clip."""
    if TV_STANDARD != "auto":
        return TV_STANDARD
    return "pal" if abs(get_fps(safe_input) - 25.0) < 0.5 else "ntsc"


def _build_qtgmc_args(current_settings):
    """Build the QTGMC argument dictionary for the generated VPY script."""
    qtgmc_params = CONFIG.get("qtgmc_settings", {})
    qtgmc_args = {
        "Preset": qtgmc_params.get("Preset", "Very Slow"),
        "InputType": 0,
        "TFF": (FIELD_ORDER == "tff"),
        "SourceMatch": qtgmc_params.get("SourceMatch", 3),
        "Lossless": qtgmc_params.get("Lossless", 2),
        "TR2": 3,
        "EZDenoise": qtgmc_params.get("EZDenoise", 0.0),
        "NoiseProcess": qtgmc_params.get("NoiseProcess", 0),
        "Sharpness": qtgmc_params.get("Sharpness", 0.0),
        "FPSDivisor": 1,
    }
    if current_settings["use_gpu_opencl"]:
        qtgmc_args["opencl"] = True
        qtgmc_args["device"] = current_settings.get("gpu_device_index", 0)
    return qtgmc_args


def _append_qtgmc_fallback_body(lines, qtgmc_args):
    """Append QTGMC invocation and fallback behavior to the VPY script."""
    lines.append("qtgmc_args = " + str(qtgmc_args))
    lines.append("def _run_bob_fallback(src_clip, args):")
    lines.append("    tff_val = args.get('TFF', True)")
    lines.append("    try:")
    lines.append("        return haf.Bob(src_clip, 0, 0.5, tff_val)")
    lines.append("    except Exception:")
    lines.append("        return src_clip.std.SeparateFields(tff=tff_val).std.DoubleWeave(tff=tff_val)")
    lines.append("def _run_qtgmc_with_fallback(src_clip, args):")
    lines.append("    retry_args = dict(args)")
    lines.append("    for _ in range(4):")
    lines.append("        try:")
    lines.append("            return haf.QTGMC(src_clip, **retry_args)")
    lines.append("        except TypeError as qtgmc_err:")
    lines.append("            if \"unexpected keyword argument 'device'\" in str(qtgmc_err) and 'device' in retry_args:")
    lines.append("                retry_args = dict(retry_args)")
    lines.append("                retry_args.pop('device', None)")
    lines.append("                continue")
    lines.append("            raise")
    lines.append("        except Exception as qtgmc_err:")
    lines.append("            err_text = str(qtgmc_err)")
    lines.append("            missing_opencl_symbol = (")
    lines.append('                "There is no function named EEDI3CL" in err_text')
    lines.append('                or "There is no function named NNEDI3CL" in err_text')
    lines.append("            )")
    lines.append("            if retry_args.get('opencl') and missing_opencl_symbol:")
    lines.append("                retry_args = dict(retry_args)")
    lines.append("                retry_args['opencl'] = False")
    lines.append("                retry_args.pop('device', None)")
    lines.append("                continue")
    lines.append("            if 'fmtc' in err_text:")
    lines.append("                retry_args = dict(retry_args)")
    lines.append("                retry_args['SourceMatch'] = 0")
    lines.append("                retry_args['Lossless'] = 0")
    lines.append("                continue")
    lines.append("            print(")
    lines.append("                f'[QTGMC FALLBACK] QTGMC failed ({type(qtgmc_err).__name__}: {qtgmc_err}); '")
    lines.append("                f'falling back to Bob - deinterlacing quality is degraded.',")
    lines.append("                file=sys.stderr,")
    lines.append("            )")
    lines.append("            return _run_bob_fallback(src_clip, retry_args)")
    lines.append("    return _run_bob_fallback(src_clip, retry_args)")


def _get_prefetch_raw_value():
    """Return raw vspipe prefetch configuration, supporting legacy and manual blocks."""
    if "vspipe_prefetch_threads" in CONFIG:
        return CONFIG.get("vspipe_prefetch_threads")

    manual_settings = CONFIG.get("manual_settings", {})
    if isinstance(manual_settings, dict):
        return manual_settings.get("vspipe_prefetch_threads", "auto")

    return "auto"


def _read_config_value(config_map: dict, key: str, default_value):
    """Read one config value from top-level first, then manual_settings."""
    raw_value = config_map.get(key)
    if raw_value is not None:
        return raw_value

    manual_settings = config_map.get("manual_settings", {})
    if isinstance(manual_settings, dict):
        return manual_settings.get(key, default_value)
    return default_value


def _parse_int_or_auto(raw_value, auto_value: int, fallback_value: int) -> int:
    """Parse config values that allow integer or 'auto'."""
    if isinstance(raw_value, int) and not isinstance(raw_value, bool):
        return raw_value
    if not isinstance(raw_value, str):
        return fallback_value

    normalized = raw_value.strip().lower()
    if normalized == "auto":
        return auto_value
    return _parse_int_or_fallback(normalized, fallback_value)


def _parse_int_or_fallback(raw_value: str, fallback_value: int) -> int:
    """Parse integer-like strings with a numeric fallback."""
    try:
        return int(raw_value)
    except ValueError:
        return fallback_value


def _resolve_prefetch_threads(current_settings):
    """Resolve Prefetch threads from config, supporting integer values and 'auto'."""
    cpu_threads = max(1, int(current_settings.get("cpu_threads", 8)))
    parsed = _parse_int_or_auto(_get_prefetch_raw_value(), auto_value=cpu_threads, fallback_value=0)
    return min(cpu_threads, max(0, parsed))


def resolve_vspipe_requests(config_map: dict, hw_settings: dict) -> int:
    """Resolve vspipe request depth from config and hardware settings."""
    cpu_threads = max(1, int(hw_settings.get("cpu_threads", 8)))
    auto_value = min(64, max(cpu_threads, cpu_threads * 2))
    raw_value = _read_config_value(config_map, "vspipe_requests", "auto")
    parsed = _parse_int_or_auto(raw_value, auto_value=auto_value, fallback_value=auto_value)
    return min(128, max(1, parsed))


def _append_prefetch(lines, current_settings):
    """Append optional Prefetch usage to the VPY script."""
    prefetch_threads = _resolve_prefetch_threads(current_settings)
    lines.append("clip = _run_qtgmc_with_fallback(clip, qtgmc_args)")
    if prefetch_threads > 0:
        lines.append("if hasattr(core.std, 'Prefetch'):")
        lines.append(f"    clip = core.std.Prefetch(clip, threads={prefetch_threads})")
    lines.append("clip.set_output()")


def _write_vpy_script(output_script, lines):
    """Write the generated VPY script to disk."""
    output_content = "\n".join(lines)
    with open(output_script, "wb") as file_handle:
        file_handle.write(output_content.encode("utf-8"))
        file_handle.write(b"\n")


def _parse_info_value(line):
    """Return the trimmed value after the first colon in an info line."""
    return line.split(":", maxsplit=1)[1].strip()


def _parse_vspipe_fps(value):
    """Parse an FPS field that may be fractional or decimal."""
    parts = value.split("(")[0].strip()
    if "/" in parts:
        num, den = map(int, parts.split("/"))
        return num / den
    return float(parts)


def _update_info_field(line, metadata):
    """Update parsed vspipe metadata for a single output line."""
    field_parsers = {
        "Frames:": ("frames", int),
        "Width:": ("width", int),
        "Height:": ("height", int),
        "Format Name:": ("fmt", str),
        "FPS:": ("fps", _parse_vspipe_fps),
    }
    for prefix, (key, parser) in field_parsers.items():
        if not line.startswith(prefix):
            continue
        try:
            metadata[key] = parser(_parse_info_value(line))
        except (ValueError, ZeroDivisionError):
            pass
        break


def create_vpy_script(input_file, output_script, _mode, override_settings=None):
    """Generates a VapourSynth script based on the selected mode."""
    current_settings = override_settings if override_settings else HW_SETTINGS
    safe_input = os.path.abspath(input_file).replace("\\", "/").strip()
    current_root = os.getcwd().replace("\\", "/").strip()
    base_dir = get_project_root()
    venv_root = resolve_venv_root(base_dir).replace("\\", "/")

    site_paths = _get_vpy_site_paths(venv_root)
    portable_root = f"{venv_root}/vs"

    lines = _get_vpy_header(venv_root, portable_root, site_paths, current_root)
    _append_runtime_settings(lines, current_settings)
    lines.extend(_get_plugin_loading_lines(venv_root))

    lines.append("if hasattr(core, 'eedi3') and not hasattr(core, 'eedi3m'):")
    lines.append("    core.eedi3m = core.eedi3\n")

    fps_logic = _resolve_fps_logic(safe_input)
    fps_num, fps_den = (25, 1) if fps_logic == "pal" else (30000, 1001)
    source_literal = _to_python_path_literal(safe_input)

    lines.append("ffms_cache_dir = os.path.join(tempfile.gettempdir(), 'auto-vhs-deinterlancer', 'ffms2')")
    lines.append("os.makedirs(ffms_cache_dir, exist_ok=True)")
    lines.append(f"_src_size = os.path.getsize({source_literal}) if os.path.exists({source_literal}) else 0")
    lines.append(f"_src_mtime = os.path.getmtime({source_literal}) if os.path.exists({source_literal}) else 0")
    lines.append(f'_cache_key = f"{{{source_literal}}}:{{_src_size}}:{{_src_mtime}}".encode("utf-8")')
    lines.append("ffms_cache_file = os.path.join(ffms_cache_dir, hashlib.sha256(_cache_key).hexdigest() + '.ffindex')")
    lines.append("if hasattr(core, 'ffms2'):")
    lines.append(f"    clip = core.ffms2.Source({source_literal}, cachefile=ffms_cache_file, " f"fpsnum={fps_num}, fpsden={fps_den})")
    lines.append("elif hasattr(core, 'lsmas'):")
    lines.append(f"    clip = core.lsmas.LWLibavSource({_to_python_path_literal(safe_input)}, fpsnum={fps_num}, fpsden={fps_den})")
    lines.append("elif hasattr(core, 'bs'):")
    lines.append(f"    clip = core.bs.VideoSource({_to_python_path_literal(safe_input)}, fpsnum={fps_num}, fpsden={fps_den})")
    lines.append("else:")
    lines.append("    raise RuntimeError('No source filter available in VapourSynth (checked ffms2, lsmas, bs).')")
    lines.append("clip = core.resize.Point(clip, format=vs.YUV420P16)\n")

    qtgmc_args = _build_qtgmc_args(current_settings)
    _append_qtgmc_fallback_body(lines, qtgmc_args)
    _append_prefetch(lines, current_settings)

    resolved_prefetch = _resolve_prefetch_threads(current_settings)
    log_info("[VSPIPE CONFIG] " f"core.num_threads={current_settings['cpu_threads']}, " f"prefetch_threads={resolved_prefetch}")

    log_debug(f"[DEBUG] Generating VPY for: {safe_input}")
    _write_vpy_script(output_script, lines)

    log_debug(f"[DEBUG] VPY saved to: {output_script} (Size: {os.path.getsize(output_script)})")


def _parse_vspipe_info_output(output):
    """Parses the output of vspipe --info for frames, FPS, width, height, and format."""
    metadata = {
        "frames": None,
        "fps": None,
        "width": None,
        "height": None,
        "fmt": None,
    }

    for line in output.splitlines():
        _update_info_field(line.strip(), metadata)
    return metadata["frames"], metadata["fps"], metadata["width"], metadata["height"], metadata["fmt"]


def get_vpy_info(vspipe_exe, script_path):
    """
    Runs vspipe --info to get frame count, FPS, and format.
    Returns: (frames, fps, width, height, fmt) or (None, None, None, None, None) on error.
    """
    try:
        env = get_vspipe_env()
        if is_python_vspipe_launcher(vspipe_exe):
            env.pop("PYTHONHOME", None)
            env.pop("PYTHONPATH", None)
        # Use info mode
        cmd = [vspipe_exe, "--info", script_path]
        output = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=30).decode()
        return _parse_vspipe_info_output(output)

    except subprocess.CalledProcessError as e:
        output = e.output.decode(errors="replace") if isinstance(e.output, bytes) else str(e.output)
        log_error(f"[VSPIPE ERROR] Info check failed: {output}")
        return None, None, None, None, None
    except (subprocess.TimeoutExpired, OSError, ValueError) as error:
        log_error(f"[VSPIPE ERROR] Info check failed: {error}")
        return None, None, None, None, None


__all__ = [
    "log_vspipe_output",
    "create_vpy_script",
    "get_vpy_info",
]
