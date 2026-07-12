# Fixing Lints and Tests: The SMART Way

## Strategy: Fix Lints First, Then Tests (SMART Approach)

Always fix ALL lint problems before addressing test failures. This ensures fresh, clean code before running tests.

### SINGLE PASS Requirement
When fixing a file:
- **View the ENTIRE file first.**
- **Identify ALL lint AND test-related issues** in that file simultaneously.
- **Fix BOTH lint and test issues in ONE edit operation.**
- **DO NOT** make multiple small edits to the same file. Be efficient and thorough.

## Prerequisites
- Python 3.12 (current `pyproject.toml` and CI target 3.12)
- Workspace `.VENV` is available

## Steps

// turbo-all
1. **Run Ruff first**:
   ```powershell
   .\.VENV\Scripts\python.exe -m ruff check .
   ```

2. **Run Flake8 second**:
   ```powershell
   .\.VENV\Scripts\python.exe -m flake8 .
   ```

3. **Run Pylint third**:
   ```powershell
   .\.VENV\Scripts\python.exe -m pylint auto_deinterlancer.py modules .github/scripts
   ```

4. **Address ALL remaining issues in a SINGLE PASS per file.**

5. **Run tests**:
   ```powershell
   .\.VENV\Scripts\python.exe -m pytest -o addopts=
   ```

6. **Generate coverage badge and verify 90%**:
   ```powershell
   .\run_pipeline_localy.ps1
   ```
   > [!IMPORTANT]
   > **ALWAYS** generate the coverage badge after tests pass and verify that coverage is at least **90%**. If coverage is below 90%, identify and fill the gaps.

## Cross-Platform Mocking (Windows/Linux Compatible)

**ALWAYS** use mocks that work on both Windows and Linux.

| Problem | Cross-Platform Solution | Example |
|---------|-------------------------|---------|
| Windows-only modules | Mock in `conftest.py` via `sys.modules` | `sys.modules['winreg'] = MagicMock()` |
| Platform-specific attributes | Use `create=True` in `patch` | `patch('ctypes.windll', create=True)` |
| `os.add_dll_directory` | Use `create=True` | `patch('os.add_dll_directory', create=True)` |
| Subprocess calls | Patch at the module level | `patch('auto_deinterlancer.subprocess.Popen')` |

## Common Flake8 Errors

| Code | Description | Fix |
|------|-------------|-----|
| E111 | Indentation not multiple of 4 | Fix indentation |
| E117 | Over-indented | Remove extra spaces |
| E302 | Expected 2 blank lines | Add blank line before function |
| E702 | Multiple statements on one line | Split into multiple lines |
| E712 | Comparison to False | Use `is False` or `not cond` |
| W293 | Blank line has whitespace | Remove trailing whitespace |
| W291 | Trailing whitespace | Remove trailing whitespace |
| F401 | Imported but unused | Remove unused import |
| F541 | f-string without placeholders | Remove `f` prefix or add `{}` |
| F841 | Variable assigned but not used | Remove or use the variable |
| F821 | Undefined name | Define variable or fix typo |
| E261 | Need 2 spaces before comment | Add space before `#` |

## Dealing with `I/O operation on closed file`

If tests fail with `ValueError: I/O operation on closed file`:
- Add logging mocks to prevent handlers from flushing to closed streams: `patch('auto_deinterlancer.log_info')`, `patch('auto_deinterlancer.log_debug')`.
- For tests calling `process_video()`, also patch `update_progress`.


