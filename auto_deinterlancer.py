#!/usr/bin/env python3
"""
AUTO-VHS-DEINTERLACER (Refactored)
Entry point wrapper.
"""

import subprocess
import sys

import modules.core.config as config_module
import modules.core.utils as utils_module
import modules.runtime.pipeline as pipeline_module
import modules.runtime.vspipe as vspipe_module


def _get_export_names(module):
    """Return the validated explicit export list for a module."""
    names = getattr(module, "__all__", None)
    if names is None:
        raise RuntimeError(f"{module.__name__} must define __all__ for explicit symbol export")
    if not isinstance(names, (list, tuple, set)):
        raise TypeError(f"{module.__name__}.__all__ must be a list, tuple, or set")
    return names


def _register_export(module_name, name, value):
    """Register a single public symbol while rejecting duplicate exports."""
    previous = _EXPORTED_BY.get(name)
    if previous is not None:
        raise RuntimeError(f"Duplicate exported symbol '{name}' from {module_name}; already exported by {previous}")

    globals()[name] = value
    _EXPORTED_BY[name] = module_name


def _export_public_symbols(module):
    names = _get_export_names(module)

    for name in names:
        if not hasattr(module, name):
            raise RuntimeError(f"{module.__name__}.__all__ contains missing symbol: {name}")
        _register_export(module.__name__, name, getattr(module, name))


_EXPORTED_BY = {}
for source_module in (config_module, utils_module, vspipe_module, pipeline_module):
    _export_public_symbols(source_module)

if __name__ == "__main__":
    try:
        pipeline_module.main()
    except KeyboardInterrupt:
        sys.exit(0)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"CRITICAL ERROR: {error}", file=sys.stderr)
        sys.exit(1)
