#!/usr/bin/env python3
"""
AUTO-VHS-DEINTERLACER (Refactored)
Entry point wrapper.
"""
import sys
import os

# Ensure the current directory is in sys.path so modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.config import *  # noqa: F401, F403
from modules.utils import *   # noqa: F401, F403
from modules.vspipe import *  # noqa: F401, F403
from modules.pipeline import * # noqa: F401, F403


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        sys.exit(1)
