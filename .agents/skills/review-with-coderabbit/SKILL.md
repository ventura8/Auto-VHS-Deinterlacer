---
name: review-with-coderabbit
description: Run a CodeRabbit review on local changes or triage and fix findings found by CodeRabbit, verifying each issue before applying zero-suppression fixes.
disable-model-invocation: true
---

# Review with CodeRabbit Skill

Use this skill to run a CodeRabbit review on local Git changes or to review and fix findings reported by the CodeRabbit CLI / IDE plugin.

## Modes

| Mode | Trigger | Action |
| --- | --- | --- |
| **Review** | User requests a CodeRabbit review on diff/changes | Runs `coderabbit review --agent` on local changes |
| **Findings** | User requests fixing existing CodeRabbit findings | Runs `coderabbit review findings --agent` |

## Hard Rules

1. **User Gated**: Invoke only when the user explicitly requests a CodeRabbit review or findings fix.
1. **Verify Invariants First**:
   - Check findings against repository rules (strict no `# noqa` / `# pylint: disable` suppressions).
   - Verify package boundaries (`modules.core` vs `modules.runtime`).
   - Ensure proposed fixes maintain ≥90% per-file line coverage with branch tracking enabled.
1. **Act on Valid Findings Only**: Fix genuine bugs, race conditions, edge cases, and clarity issues. Reject hallucinations or suggestions that violate repo invariants with clear explanations.
1. **Summary Report**: Always summarize findings reviewed, fixes applied, items skipped, and commands run.

## Workflow

### 1. Verify CodeRabbit CLI Availability

```powershell
if (Get-Command coderabbit -ErrorAction SilentlyContinue) {
    $CR = "coderabbit"
} elseif (Get-Command cr -ErrorAction SilentlyContinue) {
    $CR = "cr"
} else {
    throw "CodeRabbit CLI is not found on PATH. Install via winget or official installer (https://docs.coderabbit.ai/cli)."
}
& $CR --version
```

### 2. Review Mode (New Changes)

```powershell
# Review uncommitted changes
& $CR review --agent --uncommitted

# Review uncommitted including untracked
& $CR review --agent --uncommitted --include-untracked
```

### 3. Findings Mode (Stored Findings)

```powershell
& $CR review findings --agent
```

### 4. Verification & Validation

After addressing valid findings:

```powershell
# Run linters
.\.VENV\Scripts\python.exe -m ruff check .
.\.VENV\Scripts\python.exe -m flake8 .
.\.VENV\Scripts\python.exe -m pylint auto_deinterlancer.py modules .github/scripts

# Run local CI-parity pipeline (test suites, per-file coverage >= 90% with branch tracking, badge sync)
.\run_pipeline_localy.ps1
```
