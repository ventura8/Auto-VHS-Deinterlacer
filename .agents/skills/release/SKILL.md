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
   - Run the complete local pipeline `.\\run_pipeline_localy.ps1`.
   - Ensure per-file and total coverage are ≥90%.
   - Ensure all linters and tests pass cleanly.

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
- [ ] Sync Poetry lock file: `.\.VENV\Scripts\python.exe -m poetry lock`
- [ ] Run full local pipeline: `.\run_pipeline_localy.ps1`
- [ ] Create/Update full release notes in docs/releases/vX.Y.Z.md
- [ ] Create GitHub Release body in docs/releases/vX.Y.Z_github_description.md
- [ ] Verify coverage badge is up to date: assets/coverage.svg
- [ ] Review diff with `git diff`
- [ ] **Request explicit user confirmation before creating and pushing the release tag**
- [ ] Commit all changes and tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
      (pushing the tag triggers .github/workflows/release.yml automatically)
```
