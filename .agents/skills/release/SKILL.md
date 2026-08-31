---
name: release
description: Release documentation and version bumping workflow for Auto-VHS-Deinterlacer.
---

# Release Skill

Use this skill to document, prepare, and verify releases for Auto-VHS-Deinterlacer.

## Release Mandate & Workflow

1. **Version Single Source of Truth**:
   - The canonical version is stored in `pyproject.toml` under `[project].version`.
   - Ensure versions follow semantic versioning (`MAJOR.MINOR.PATCH`, e.g., `1.0.2`).
1. **Review All Changes**:
   - Inspect all commits, PRs, and staged changes since the previous release.
   - Categorize changes into: Features, Performance/Hardware, Bug Fixes, Documentation, and Quality/CI.
1. **Release Notes Documentation**:
   - Document the full release notes in `docs/releases/vX.Y.Z.md`.
   - Create a concise GitHub Release body in `docs/releases/vX.Y.Z_github_description.md`
     (see format below). The release workflow uses this file as the GitHub Release body
     automatically when the tag is pushed; if the file is absent, it falls back to
     GitHub's auto-generated notes.
1. **Validation Gate Before Release**:
   - Run the complete local pipeline `.\run_pipeline_localy.ps1` (or `./run_pipeline_localy.sh`).
   - Ensure line coverage is ≥90% for every product file and ≥90% overall;
     branch coverage is measured and reported but has no separate threshold.
   - Ensure all linters and tests pass cleanly.
1. **Commit Formatting & Message Discipline**:
   - Always format the release commit title as `release: vX.Y.Z - <Short Title>`.
   - Provide a comprehensive, structured description categorizing all changes (Cross-Platform, Automation & Tooling, E2E & Container Infrastructure, CI/CD, Dependencies, Validation).
   - Use `git commit --amend` to update the commit title and detailed description so the release commit message is complete and accurate before tagging.

## `_github_description.md` Format

Follow the Ubuntu-Hello pattern used in `docs/releases/`:

```markdown
# Auto-VHS-Deinterlacer vX.Y.Z — <Short Title>

One-paragraph summary of what this release accomplishes.

---

## 🔍 What's in this release

- **Bullet per meaningful change** — brief, user-facing description.

## 🧪 Validation

- Pass/fail summary sentence.

---

**Full Changelog**: [vA.B.C...vX.Y.Z](https://github.com/ventura8/Auto-VHS-Deinterlacer/compare/vA.B.C...vX.Y.Z)
```

## Release Checklist

```text
Release Progress:
- [ ] Determine new version number (e.g. 1.0.3)
- [ ] Update version in pyproject.toml
- [ ] Sync Poetry lock file: `.\.VENV\Scripts\python.exe -m poetry lock` (POSIX: `./.venv/bin/python -m poetry lock` or `poetry lock`)
- [ ] Run full local pipeline: `.\run_pipeline_localy.ps1` (or `./run_pipeline_localy.sh`)
- [ ] Create/Update full release notes in docs/releases/vX.Y.Z.md
- [ ] Create GitHub Release body in docs/releases/vX.Y.Z_github_description.md
- [ ] Verify coverage badge is up to date: assets/coverage.svg
- [ ] Review diff with `git diff`
- [ ] Update commit title and detailed description using `git commit --amend`
- [ ] **Request explicit user confirmation before creating and pushing the release tag**
- [ ] Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`
      (pushing the tag triggers .github/workflows/release.yml automatically)
```
