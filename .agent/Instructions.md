# AI Instructions: Auto-VHS-Deinterlacer

This directory is the project-level agent index.

## Canonical Agent Files

- [Root Agent Instructions](../AGENTS.md)
- [Architecture Overview](architecture.md)
- [Setup Guide](setup.md)
- [Validation Guide](validation.md)
- [Lint Workflow](workflows/fix-lints.md)

## Workspace Skills

The workspace provides on-demand agent skills in [`.agents/skills/`](../.agents/skills/):

- [`code-linter`](../.agents/skills/code-linter/SKILL.md)
- [`pipeline-runner`](../.agents/skills/pipeline-runner/SKILL.md)
- [`test-runner`](../.agents/skills/test-runner/SKILL.md)
- [`installer-tester`](../.agents/skills/installer-tester/SKILL.md)
- [`release`](../.agents/skills/release/SKILL.md)
- [`resolve-pr-comments`](../.agents/skills/resolve-pr-comments/SKILL.md)
- [`review-with-coderabbit`](../.agents/skills/review-with-coderabbit/SKILL.md)
- [`vapoursynth-pipeline-verifier`](../.agents/skills/vapoursynth-pipeline-verifier/SKILL.md)

## Current Repository Layout

- `auto_deinterlancer.py`: thin entry point wrapper
- `modules/core/`: configuration, hardware detection, utilities, and havsfunc patching
- `modules/runtime/`: pipeline orchestration, vspipe execution, and native fallback runtime
- `tests/unit/`, `tests/integration/`, `tests/native/`: grouped tests by concern
- `.github/scripts/`: CI & validation helper scripts

## Current Working Rules

- Prefer the `modules.core.*` and `modules.runtime.*` package paths.
- Keep lint and test fixes small and localized.
- Do not add `# noqa`, `# pylint: disable`, or other suppressions.
- Maintain ≥90% test coverage per-file and repository-wide.
- Use the workspace `.VENV` interpreter for validation.
