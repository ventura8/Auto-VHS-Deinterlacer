"""Patch the bundled havsfunc script for project compatibility."""

import os
import re
import sys

from modules.core.utils import get_project_root


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
    file_path = os.path.join(get_project_root(), ".venv", "Lib", "site-packages", "havsfunc.py")

    if not os.path.exists(file_path):
        print(f"File {file_path} not found. Skipping patch.")
        sys.exit(0)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Fix get_core
    content, _ = _replace_text(content, "get_core", "vs.get_core()", "vs.core")

    # 2. Fix _global arguments in Analyse calls
    content, _ = _replace_regex(content, "remove__global", r",\s*_global\s*=\s*[a-zA-Z0-9_]+", "")

    # 3. Fix _lambda arguments
    content, _ = _replace_regex(content, "remove__lambda", r",\s*_lambda\s*=\s*[a-zA-Z0-9_]+", "")

    # 4. Add device support to QTGMC for legacy havsfunc variants.
    # Newer variants (e.g. r33) already expose `device` in QTGMC signatures.
    qtgmc_signature = re.search(r"def\s+QTGMC\s*\((.*?)\)\s*:", content, flags=re.DOTALL)
    has_qtgmc_device = bool(qtgmc_signature and re.search(r"\bdevice\s*=", qtgmc_signature.group(1)))

    if not has_qtgmc_device:
        if not re.search(r"^\s*(import\s+functools|from\s+functools\s+import\b)", content, flags=re.MULTILINE):
            lines = content.splitlines()
            insert_at = 0

            if lines and lines[0].startswith("#!"):
                insert_at = 1

            if insert_at < len(lines) and lines[insert_at].startswith(('"""', "'''")):
                quote = lines[insert_at][:3]
                if lines[insert_at].count(quote) >= 2 and len(lines[insert_at]) > 3:
                    insert_at += 1
                else:
                    insert_at += 1
                    while insert_at < len(lines) and quote not in lines[insert_at]:
                        insert_at += 1
                    if insert_at < len(lines):
                        insert_at += 1

            while insert_at < len(lines) and lines[insert_at].startswith("from __future__ import"):
                insert_at += 1

            lines.insert(insert_at, "import functools")
            content = "\n".join(lines)

        # Add device parameter to QTGMC, QTGMC_Interpolate, and QTGMC_ApplySourceMatch signatures
        content, _ = _replace_text(
            content,
            "qtgmc_signature_opencl_false",
            "opencl=False):",
            "opencl=False, device=0):",
            required=False,
        )
        content, _ = _replace_text(
            content,
            "qtgmc_signature_opencl_param",
            ", opencl):",
            ", opencl, device=0):",
            required=False,
        )

        # Pass device parameter to internal calls
        content, _ = _replace_text(
            content,
            "device_propagation_matchenhance",
            "MatchEnhance, TFF, opencl)",
            "MatchEnhance, TFF, opencl, device)",
            required=False,
        )
        content, _ = _replace_text(
            content,
            "device_propagation_positional",
            "TFF, opencl)",
            "TFF, opencl, device)",
            required=False,
        )
        content, _ = _replace_text(
            content,
            "device_propagation_keyword",
            "TFF=TFF, opencl=opencl)",
            "TFF=TFF, opencl=opencl, device=device)",
            required=False,
        )

        # Robust Plugin Wrapping for OpenCL
        q_interp_pattern = (
            r"(def QTGMC_Interpolate\(.*?\):.*?)(myNNEDI3 = core\.nnedi3cl\.NNEDI3CL)"
            r"(.*?\n\s+)(myEEDI3 = core\.eedi3m\.EEDI3CL)"
        )

        def repl_plugins(match):
            """Replace QTGMC OpenCL plugin handles with device-aware partials."""
            header = match.group(1)
            new_nn = (
                "myNNEDI3 = functools.partial(core.nnedi3cl.NNEDI3CL, device=device) "
                "if hasattr(core, 'nnedi3cl') and hasattr(core.nnedi3cl, 'NNEDI3CL') else None"
            )
            spacing = match.group(3)
            new_ee = (
                "myEEDI3 = functools.partial(core.eedi3m.EEDI3CL, device=device) "
                "if hasattr(core, 'eedi3m') and hasattr(core.eedi3m, 'EEDI3CL') else None"
            )
            return header + new_nn + spacing + new_ee

        content, _ = _replace_regex(
            content,
            "q_interp_pattern",
            q_interp_pattern,
            repl_plugins,
            flags=re.DOTALL,
            required=False,
        )

        # Also fix santiag which uses similar opencl logic if present
        nnedi3_replace = (
            "myNNEDI3 = functools.partial(core.nnedi3cl.NNEDI3CL, device=device) "
            "if hasattr(core, 'nnedi3cl') and hasattr(core.nnedi3cl, 'NNEDI3CL') else None"
        )
        eedi3_replace = (
            "myEEDI3 = functools.partial(core.eedi3m.EEDI3CL, device=device) "
            "if hasattr(core, 'eedi3m') and hasattr(core.eedi3m, 'EEDI3CL') else None"
        )
        content, _ = _replace_text(content, "nnedi3_opencl_partial", "myNNEDI3 = core.nnedi3cl.NNEDI3CL", nnedi3_replace)
        content, _ = _replace_text(content, "eedi3_opencl_partial", "myEEDI3 = core.eedi3m.EEDI3CL", eedi3_replace)
    else:
        print("INFO: QTGMC device parameter already present; skipping legacy device patch block")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("Patched havsfunc.py with robust device support")


if __name__ == "__main__":
    main()
