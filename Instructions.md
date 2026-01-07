# AI Instructions: Auto-VHS-Deinterlacer

This document provides technical guidance for AI agents and developers working on this project.

The detailed documentation has been split into multiple files for easier navigation and modularity.

## Documentation Index

- [Project Overview & Directory Structure](docs/project_overview.md)
  - General project goals, modular structure (`modules/`), and file organization.
- [Key Logic & Pipeline](docs/pipeline_logic.md)
  - Detailed explanation of the 4-step hardware-aware pipeline orchestrated via `modules/pipeline.py`.
- [Hardware Optimization](docs/hardware_optimization.md)
  - Auto-detection logic (in `modules/config.py`), profiles (ULTRA/HIGH/LOW), RAM scaling (>32GB), and CPU scaling.
- [Configuration](docs/configuration.md)
  - `config.yaml` settings and hardware auto-tuning logic.
- [UI Standards](docs/ui_standards.md)
  - Specifications for the "Studio Reference" CLI aesthetic (implemented in `modules/utils.py`).

## Development Standards

### Fixing Lint and Test Errors (The SMART Way)

**Strategy: Fix Lints FIRST, Then Tests**

Always fix ALL lint problems before addressing test failures. This ensures clean, stable code before running tests.

#### The SINGLE PASS Rule
When working on a file, identify **ALL** problems (lint, type errors, test failures) at once. Apply **ALL** fixes in a single edit operation. Do not make multiple sequential edits to the same file.

#### Workflow
1. **MANDATORY: Run autopep8 FIRST**: `autopep8 --in-place --aggressive --aggressive <file.py>`
   *Always run this before attempting any manual lint fixes.*
2. **Identify remaining issues**: Run `flake8` and `mypy`.
3. **Single Pass Fix**: Edit the file once to fix everything identified.
4. **Run Tests**: `pytest --tb=short -q`
5. **Coverage & Badge**: Run `.\run_tests.ps1` to generate the coverage badge and verify coverage is at least **90%**.

See [.agent/workflows/fix-lints.md](.agent/workflows/fix-lints.md) for the detailed step-by-step workflow.

### Cross-Platform Mocking Rules

When writing mocks, **ALWAYS** use patterns that are compatible with both Windows and Linux CI environments:

| Pattern | Platform Specific | Cross-Platform Solution |
|---------|-------------------|--------------------------|
| Moduels | `winreg`, `msvcrt` | Mock in `conftest.py` via `sys.modules` |
| Win DLLs | `ctypes.windll` | Use `create=True`: `patch('ctypes.windll', create=True)` |
| DLL Paths | `os.add_dll_directory` | Use `create=True`: `patch('os.add_dll_directory', create=True)` |
| Subprocess | `subprocess.Popen` | Always patch at the module level: `patch('module.subprocess.Popen')` |

### Other Standards

- **Test Coverage**: Maintain at least **90%** code coverage. Always run `run_tests.ps1` to verify and update the badge.
- **ISO Logging**: All logging must use the `ISOFormatter` for millisecond-precision timestamps.
