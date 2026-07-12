---
applyTo: "**/*.ps1"
---

# PowerShell Project Guidance

- Keep scripts strict and deterministic.
- Use the repository `.VENV` interpreter when invoking Python tooling.
- Prefer helper functions such as `Invoke-PoetryCommand` and `Invoke-CheckedCommand` for repeated command execution.
- Surface failures immediately; do not hide errors behind silent fallbacks.
- Keep lint, test, and coverage steps in the same order as the local pipeline unless a change explicitly requires a different sequence.
