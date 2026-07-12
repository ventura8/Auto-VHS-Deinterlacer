---
applyTo: "**/*.py"
---

# Python Project Guidance

- Import shared runtime helpers from `modules.core` and pipeline code from `modules.runtime`.
- Keep functions and tests focused; avoid adding new cross-cutting layers unless they solve a real boundary problem.
- Preserve the repository lint rules: Ruff, Flake8, and Pylint must stay green.
- Do not add lint suppressions, `# noqa`, or `# pylint: disable` markers.
- Prefer explicit test fixtures and module-level patch targets over ad hoc path manipulation.
