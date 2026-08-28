# CodeRabbit Review Examples

## Example: Triaging CodeRabbit Findings

### Finding 1: Resource Leak in Subprocess Execution

- **Path**: `modules/runtime/vspipe.py`
- **Issue**: Process stdout stream is not closed on unexpected pipe termination.
- **Classification**: **Valid**
- **Action**: Use context managers / `try...finally` to ensure stdout and stderr handles are closed cleanly.
- **Verification**: Run pytest unit tests on `test_runtime_helpers.py`.

### Finding 2: Add In-line Ignore for Pylint Warning

- **Path**: `modules/core/config.py`
- **Issue**: Suggestion to add `# pylint: disable=too-many-arguments`.
- **Classification**: **Invalid**
- **Action**: Refactor method parameters into a dataclass or structured dictionary to satisfy radon/pylint without suppressions.
- **Verification**: Run `.\.VENV\Scripts\python.exe -m pylint modules/core/config.py`.
