"""Patch the bundled havsfunc script for project compatibility."""

import os
import re
import sys

from modules.core.utils import get_project_root


def _get_havsfunc_path() -> str:
    """Return the expected havsfunc.py path inside the local venv across platforms."""
    root = get_project_root()
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        os.path.join(root, ".venv", "lib", py_ver, "site-packages", "havsfunc.py"),
        os.path.join(root, ".VENV", "lib", py_ver, "site-packages", "havsfunc.py"),
        os.path.join(root, ".venv", "Lib", "site-packages", "havsfunc.py"),
        os.path.join(root, ".VENV", "Lib", "site-packages", "havsfunc.py"),
    ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    # If neither exists yet, return preferred platform path
    if sys.platform != "win32":
        return candidates[0]
    return os.path.join(root, ".venv", "Lib", "site-packages", "havsfunc.py")


def _read_text(path_value: str) -> str:
    """Read UTF-8 text content from a file path."""
    with open(path_value, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def _write_text(path_value: str, content: str):
    """Write UTF-8 text content to a file path."""
    with open(path_value, "w", encoding="utf-8") as file_handle:
        file_handle.write(content)


def _apply_base_patches(content: str) -> str:
    """Apply compatibility patches that are always safe to run."""
    content, _ = _replace_text(content, "get_core", "vs.get_core()", "vs.core")
    content, _ = _replace_regex(content, "remove__global", r",\s*_global\s*=\s*[a-zA-Z0-9_]+", "")
    content, _ = _replace_regex(content, "remove__lambda", r",\s*_lambda\s*=\s*[a-zA-Z0-9_]+", "")
    content, _ = _replace_regex(
        content,
        "guard_adjust_import",
        r"^import\s+adjust\b.*$",
        "try:\n    import adjust\nexcept ImportError:\n    adjust = None",
        flags=re.MULTILINE,
    )
    bob_fmtc_pattern = (
        r"^(?P<indent>[ \t]*)clip\s*=\s*clip\.std\.SeparateFields\(tff=tff\)\.fmtc\.resample\("
        r"scalev=2,\s*kernel='bicubic',\s*a1=b,\s*a2=c,\s*interlaced=1,\s*interlacedd=0\)"
    )

    def _replace_bob_fmtc(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}try:\n"
            f"{indent}    clip = clip.std.SeparateFields(tff=tff).fmtc.resample(\n"
            f"{indent}        scalev=2, kernel='bicubic', a1=b, a2=c, interlaced=1, interlacedd=0\n"
            f"{indent}    )\n"
            f"{indent}except Exception:\n"
            f"{indent}    clip = clip.std.SeparateFields(tff=tff).resize.Bicubic(\n"
            f"{indent}        height=clip.height, filter_param_a=b, filter_param_b=c\n"
            f"{indent}    )"
        )

    content, _ = _replace_regex(
        content,
        "bob_fmtc_fallback",
        bob_fmtc_pattern,
        _replace_bob_fmtc,
        flags=re.MULTILINE,
    )
    return content


def _has_qtgmc_device_parameter(content: str) -> bool:
    """Return whether the target havsfunc variant already exposes device=."""
    qtgmc_signature = re.search(r"def\s+QTGMC\s*\((.*?)\)\s*:", content, flags=re.DOTALL)
    return bool(qtgmc_signature and re.search(r"\bdevice\s*=", qtgmc_signature.group(1)))


def _find_import_insert_index(lines: list[str]) -> int:
    """Locate the safest insertion point for a new top-level import."""
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1

    insert_at = _skip_module_docstring(lines, insert_at)
    return _skip_future_imports(lines, insert_at)


def _skip_module_docstring(lines: list[str], insert_at: int) -> int:
    """Advance past a module docstring when present."""
    if insert_at >= len(lines) or not lines[insert_at].startswith(('"""', "'''")):
        return insert_at

    quote = lines[insert_at][:3]
    if _is_single_line_docstring(lines[insert_at], quote):
        return insert_at + 1

    insert_at = _advance_to_docstring_end(lines, insert_at + 1, quote)
    if insert_at < len(lines):
        insert_at += 1
    return insert_at


def _is_single_line_docstring(line: str, quote: str) -> bool:
    """Return whether the docstring opens and closes on the same line."""
    return line.count(quote) >= 2 and len(line) > 3


def _advance_to_docstring_end(lines: list[str], insert_at: int, quote: str) -> int:
    """Advance to the closing line of a multi-line module docstring."""
    while insert_at < len(lines) and quote not in lines[insert_at]:
        insert_at += 1
    return insert_at


def _is_blank_or_comment(line: str) -> bool:
    """Return whether a source line is blank or a comment."""
    return not line.strip() or line.lstrip().startswith("#")


def _skip_blank_and_comment_lines(lines: list[str], cursor: int) -> int:
    """Advance past blank and comment-only lines."""
    while cursor < len(lines) and _is_blank_or_comment(lines[cursor]):
        cursor += 1
    return cursor


def _skip_future_import_block(lines: list[str], cursor: int) -> int:
    """Advance past a contiguous top-level future-import block."""
    while cursor < len(lines):
        if lines[cursor].startswith("from __future__ import"):
            cursor += 1
            continue
        next_cursor = _skip_blank_and_comment_lines(lines, cursor)
        if next_cursor == cursor:
            break
        cursor = next_cursor
    return cursor


def _skip_future_imports(lines: list[str], insert_at: int) -> int:
    """Advance past any __future__ imports at the top of the file."""
    cursor = _skip_blank_and_comment_lines(lines, insert_at)

    if cursor >= len(lines) or not lines[cursor].startswith("from __future__ import"):
        return insert_at

    return _skip_future_import_block(lines, cursor + 1)


def _iter_import_specs(line: str):
    """Yield stripped import specs from one top-level import line."""
    for spec in line.removeprefix("import ").split(","):
        yield spec.strip()


def _has_direct_functools_import(content: str) -> bool:
    """Return whether the module directly imports functools."""
    return any(spec == "functools" for line in content.splitlines() if line.startswith("import ") for spec in _iter_import_specs(line))


def _ensure_functools_import(content: str) -> str:
    """Insert import functools when the legacy patch path needs it."""
    if _has_direct_functools_import(content):
        return content

    lines = content.splitlines()
    lines.insert(_find_import_insert_index(lines), "import functools")
    return "\n".join(lines)


def _find_top_level_function_block(lines: list[str], function_name: str) -> tuple[int, int] | None:
    """Return the [start, end) line range for a top-level function body."""
    signature_prefix = f"def {function_name}("

    start_index = _find_first_line_starting_with(lines, signature_prefix)

    if start_index is None:
        return None

    return start_index, _find_function_block_end(lines, start_index)


def _find_first_line_starting_with(lines: list[str], prefix: str) -> int | None:
    """Return the index of the first line that starts with a prefix."""
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            return index
    return None


def _find_function_block_end(lines: list[str], start_index: int) -> int:
    """Return the end index for a top-level function block."""
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith(("def ", "class ")):
            return index
    return len(lines)


def _replace_text_in_function_block(
    content: str,
    function_name: str,
    patch_name: str,
    old_text: str,
    new_text: str,
    required: bool = False,
) -> tuple[str, int]:
    """Apply a literal replacement only inside one top-level function body."""
    lines = content.splitlines(keepends=True)
    block_bounds = _find_top_level_function_block(lines, function_name)
    if block_bounds is None:
        return _replace_text("", patch_name, old_text, new_text, required=required)

    start_index, end_index = block_bounds
    block_content = "".join(lines[start_index:end_index])
    updated_block, match_count = _replace_text(block_content, patch_name, old_text, new_text, required=required)
    if match_count == 0:
        return content, 0

    lines[start_index:end_index] = updated_block.splitlines(keepends=True)
    return "".join(lines), match_count


def _replace_regex_in_function_block(
    content: str,
    function_name: str,
    patch_name: str,
    pattern: str,
    repl: str,
    flags: int = 0,
    required: bool = False,
) -> tuple[str, int]:
    """Apply a regex replacement only inside one top-level function body."""
    lines = content.splitlines(keepends=True)
    block_bounds = _find_top_level_function_block(lines, function_name)
    if block_bounds is None:
        _, match_count = _replace_regex("", patch_name, pattern, repl, flags=flags, required=required)
        return content, match_count

    start_index, end_index = block_bounds
    block_content = "".join(lines[start_index:end_index])
    updated_block, match_count = _replace_regex(block_content, patch_name, pattern, repl, flags=flags, required=required)
    if match_count == 0:
        return content, 0

    lines[start_index:end_index] = updated_block.splitlines(keepends=True)
    return "".join(lines), match_count


def _apply_replacements_for_function(
    content: str,
    function_name: str,
    replacements: list[tuple[str, str, str]],
) -> tuple[str, int]:
    """Apply a set of literal replacements to one named function block."""
    total_matches = 0
    for patch_name, old_text, new_text in replacements:
        content, matches = _replace_text_in_function_block(content, function_name, patch_name, old_text, new_text, required=False)
        total_matches += matches
    return content, total_matches


def _apply_stage_for_required_functions(
    content: str,
    function_names: tuple[str, ...],
    replacements: list[tuple[str, str, str]],
    stage_name: str,
) -> tuple[str, bool]:
    """Apply one replacement stage and require a match in each target function."""
    staged_content = content
    for function_name in function_names:
        staged_content, match_count = _apply_replacements_for_function(staged_content, function_name, replacements)
        if match_count == 0:
            print(f"WARNING: Incomplete {stage_name} patch for {function_name}; skipping legacy device patch block")
            return content, False
    return staged_content, True


def _apply_device_signature_patches(content: str) -> str:
    """Add device= to legacy QTGMC function signatures and call sites."""
    signature_replacements = [
        ("qtgmc_signature_opencl_false", "opencl=False):", "opencl=False, device=0):"),
        ("qtgmc_signature_opencl_param", ", opencl):", ", opencl, device=0):"),
    ]
    propagation_replacements = [
        ("device_propagation_matchenhance", "MatchEnhance, TFF, opencl)", "MatchEnhance, TFF, opencl, device)"),
        ("device_propagation_positional", "TFF, opencl)", "TFF, opencl, device)"),
        ("device_propagation_keyword", "TFF=TFF, opencl=opencl)", "TFF=TFF, opencl=opencl, device=device)"),
    ]

    original_content = content
    function_names = ("QTGMC", "QTGMC_Interpolate")

    content, signatures_complete = _apply_stage_for_required_functions(
        content,
        function_names,
        signature_replacements,
        "QTGMC signature",
    )
    if not signatures_complete:
        return original_content

    content, propagation_complete = _apply_stage_for_required_functions(
        content,
        function_names,
        propagation_replacements,
        "QTGMC device propagation",
    )
    if not propagation_complete:
        return original_content

    return content


def _build_opencl_partial(core_path: str) -> str:
    """Return a device-aware functools.partial wrapper string for an OpenCL plugin."""
    plugin_name = core_path.split(".")[-2]
    method_name = core_path.split(".")[-1]
    return (
        f"functools.partial({core_path}, device=device) "
        f"if hasattr(core, '{plugin_name}') and hasattr(core.{plugin_name}, '{method_name}') else None"
    )


def _apply_qinterp_device_patch(content: str) -> tuple[str, bool]:
    """Wrap QTGMC_Interpolate OpenCL plugin handles with device-aware partials."""
    q_interp_pattern = (
        r"(def QTGMC_Interpolate\(.*?\):.*?)(myNNEDI3\s*=\s*)core\.nnedi3cl\.NNEDI3CL" + r"(.*?\n\s+)(myEEDI3\s*=\s*)core\.eedi3m\.EEDI3CL"
    )

    def repl_plugins(match):
        """Replace QTGMC OpenCL plugin handles with device-aware partials."""
        nnedi3_partial = _build_opencl_partial("core.nnedi3cl.NNEDI3CL")
        eedi3_partial = _build_opencl_partial("core.eedi3m.EEDI3CL")
        return match.group(1) + match.group(2) + nnedi3_partial + match.group(3) + match.group(4) + eedi3_partial

    updated_content, match_count = _replace_regex_in_function_block(
        content,
        "QTGMC_Interpolate",
        "qinterp_device_patch",
        q_interp_pattern,
        repl_plugins,
        flags=re.DOTALL,
    )
    return updated_content, match_count > 0


def _apply_opencl_partial_patches(content: str, qinterp_patched: bool) -> str:
    """Apply device-aware OpenCL wrapper replacements to known plugin handle patterns."""
    replacements = [
        ("nnedi3_opencl_partial", "myNNEDI3 = core.nnedi3cl.NNEDI3CL", "myNNEDI3 = " + _build_opencl_partial("core.nnedi3cl.NNEDI3CL")),
        ("eedi3_opencl_partial", "myEEDI3 = core.eedi3m.EEDI3CL", "myEEDI3 = " + _build_opencl_partial("core.eedi3m.EEDI3CL")),
    ]
    total_matches = 0
    for patch_name, old_text, new_text in replacements:
        content, match_count = _replace_text_in_function_block(content, "QTGMC_Interpolate", patch_name, old_text, new_text, required=False)
        if match_count > 0:
            total_matches += match_count
            continue
        if not qinterp_patched:
            print(f"WARNING: [{patch_name}] target not found")
    return content


def _apply_legacy_device_patch(content: str) -> str:
    """Apply the optional legacy QTGMC device support patch block."""
    if _has_qtgmc_device_parameter(content):
        print("INFO: QTGMC device parameter already present; skipping legacy device patch block")
        return content

    original_content = content
    content = _apply_device_signature_patches(content)
    if content == original_content:
        return original_content

    content = _ensure_functools_import(content)
    content, qinterp_patched = _apply_qinterp_device_patch(content)
    return _apply_opencl_partial_patches(content, qinterp_patched)


def _apply_nnedi3cl_only_patch(content: str) -> str:
    """Avoid resolving EEDI3CL when QTGMC is using its default NNEDI3 mode."""
    if "if EdiMode in ('eedi3', 'eedi3+nnedi3'):" in content:
        return content

    pattern = (
        r"(?P<indent>^[ \t]*)eedi3 = partial\(core\.eedi3m\.EEDI3CL, "
        r"alpha=alpha, beta=beta, gamma=gamma, nrad=nrad, mdis=EdiMaxD, "
        r"vcheck=vcheck, device=device\)"
    )

    def replacement(match: re.Match[str]) -> str:
        """Build EEDI3CL only for QTGMC modes that actually use it."""
        indent = match.group("indent")
        return (
            f"{indent}eedi3 = None\n"
            f"{indent}if EdiMode in ('eedi3', 'eedi3+nnedi3'):\n"
            f"{indent}    eedi3 = partial(core.eedi3m.EEDI3CL, alpha=alpha, beta=beta, "
            f"gamma=gamma, nrad=nrad, mdis=EdiMaxD, vcheck=vcheck, device=device)"
        )

    updated_content, _ = _replace_regex_in_function_block(
        content,
        "QTGMC_Interpolate",
        "lazy_eedi3cl",
        pattern,
        replacement,
        flags=re.MULTILINE,
    )
    return updated_content


def _replace_text(content, patch_name, old, new, required=False):
    """Apply a literal text replacement and track whether it matched."""
    match_count = content.count(old)
    if match_count == 0:
        message = f"[{patch_name}] target not found"
        if required:
            raise RuntimeError(message)
        print(f"WARNING: {message}")
        return content, 0
    return content.replace(old, new), match_count


def _replace_regex(content, patch_name, pattern, repl, flags=0, required=False):
    """Apply a regex replacement and track whether it matched."""
    updated, match_count = re.subn(pattern, repl, content, flags=flags)
    if match_count == 0:
        message = f"[{patch_name}] target not found"
        if required:
            raise RuntimeError(message)
        print(f"WARNING: {message}")
        return content, 0
    return updated, match_count


def main():
    """Apply compatibility and OpenCL-device patches to havsfunc.py in the local venv."""
    file_path = _get_havsfunc_path()

    if not os.path.exists(file_path):
        print(f"File {file_path} not found. Skipping patch.")
        sys.exit(0)

    content = _read_text(file_path)
    content = _apply_base_patches(content)
    content = _apply_legacy_device_patch(content)
    content = _apply_nnedi3cl_only_patch(content)
    _write_text(file_path, content)

    print("Patched havsfunc.py with robust device support")


if __name__ == "__main__":
    main()
