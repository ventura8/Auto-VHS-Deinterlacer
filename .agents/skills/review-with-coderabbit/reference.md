# CodeRabbit CLI Reference for Auto-VHS-Deinterlacer

## Installation on Windows

Install CodeRabbit CLI using `winget` (recommended) or the standalone binary installer:

```powershell
# Using winget (recommended)
winget install CodeRabbit.CodeRabbitCLI

# Or download the official installer script and inspect before running
Invoke-WebRequest -Uri https://coderabbit.ai/install.ps1 -OutFile install-cr.ps1 -UseBasicParsing
# Inspect/verify install-cr.ps1 hash or signature, then execute:
.\install-cr.ps1
Remove-Item install-cr.ps1
```

Verify installation:

```powershell
coderabbit --version
coderabbit doctor
```

## Authentication

```powershell
# Interactive web login
coderabbit auth login

# Check authentication status
coderabbit auth status
```

## Common Commands

```powershell
# Review unstaged / uncommitted changes
coderabbit review --uncommitted

# Review staged changes
coderabbit review --committed

# Review full branch changes vs main
coderabbit review --base main

# Agent output format (JSON event stream)
coderabbit review --agent --uncommitted
```
