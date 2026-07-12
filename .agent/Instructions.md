# AI Instructions: Auto-VHS-Deinterlacer

This directory is the project-level agent index.

## Canonical Agent Files

- [Root agent instructions](../AGENTS.md)
- [Architecture overview](architecture.md)
- [Setup guide](setup.md)
- [Validation guide](validation.md)
- [Lint workflow](workflows/fix-lints.md)

## Current Repository Layout

- auto_deinterlancer.py: thin entry point wrapper
- modules/core/: configuration, utilities, and havsfunc patching
- modules/runtime/: pipeline, vspipe, and native fallback runtime
- tests/unit/, tests/integration/, tests/native/: grouped tests by concern
- .github/scripts/: CI helper scripts

## Current Working Rules

- Prefer the modules.core.* and modules.runtime.* package paths.
- Keep lint and test fixes small and localized.
- Do not add # noqa, # pylint: disable, or other suppressions unless explicitly requested.
- Use the workspace .VENV interpreter for validation.
