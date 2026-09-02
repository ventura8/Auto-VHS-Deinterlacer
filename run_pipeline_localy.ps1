param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot
$venvPy = "$repoRoot\.VENV\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    throw "Virtual environment interpreter not found at $venvPy. Run install.ps1 first."
}

function Invoke-CheckedCommand {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Executable $($Arguments -join ' ')"
    }
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Output "==> $Name"
    & $Action
}

function Invoke-PoetryCommand {
    param([string[]]$Arguments)

    Invoke-CheckedCommand $venvPy (@("-m", "poetry") + $Arguments)
}

Invoke-Step "Install Poetry" {
    Invoke-CheckedCommand $venvPy @("-m", "pip", "install", "poetry==2.4.2")
}

Invoke-Step "Sync Poetry lock file" {
    $isLockFresh = $true

    try {
        Invoke-PoetryCommand @("check", "--lock")
    }
    catch {
        $isLockFresh = $false
        Write-Output "poetry.lock is out of date. Regenerating lock file..."
    }

    if (-not $isLockFresh) {
        Invoke-PoetryCommand @("lock")
    }
}

Invoke-Step "Install dev dependencies" {
    Invoke-PoetryCommand @("-v", "install", "--only", "main,dev", "--no-root")
}

Invoke-Step "Install PR review tooling" {
    $prToolsInstaller = Join-Path $repoRoot ".github\scripts\install_pr_review_tools.ps1"
    if (-not (Test-Path $prToolsInstaller)) {
        throw "PR tooling installer script not found: $prToolsInstaller"
    }

    try {
        & $prToolsInstaller
    }
    catch {
        Write-Output "[WARNING] PR review tooling auto-install failed: $_"
        Write-Output "[WARNING] Continue, then run .github/scripts/install_pr_review_tools.ps1 manually if needed."
    }
}

Invoke-Step "Run PowerShell Lint" {
    $lintScript = Join-Path $repoRoot ".github\scripts\run_powershell_lint.ps1"
    if (-not (Test-Path $lintScript)) {
        throw "PowerShell lint runner script not found: $lintScript"
    }

    & $lintScript -RepoRoot $repoRoot
}

Invoke-Step "Run Taplo TOML Lint" {
    $tomlFiles = git ls-files "*.toml"
    if (-not $tomlFiles) {
        throw "No TOML files found to lint"
    }

    $taploArgs = @("run", "taplo", "lint") + $tomlFiles
    Invoke-PoetryCommand $taploArgs
}

Invoke-Step "Run Bandit Security Scan" {
    Invoke-PoetryCommand @("run", "bandit", "-ll", "-r", "auto_deinterlancer.py", "modules", ".github/scripts")
}

Invoke-Step "Run pip-audit Dependency Scan" {
    Invoke-PoetryCommand @("run", "pip-audit")
}

Invoke-Step "Run Black" {
    Invoke-PoetryCommand @("run", "black", "--check", "auto_deinterlancer.py", "modules", "tests", ".github/scripts")
}

Invoke-Step "Run isort" {
    Invoke-PoetryCommand @("run", "isort", "--check-only", "auto_deinterlancer.py", "modules", "tests", ".github/scripts")
}

Invoke-Step "Run Ruff" {
    Invoke-PoetryCommand @("run", "ruff", "check", "auto_deinterlancer.py", "modules", "tests", ".github/scripts")
}

Invoke-Step "Run Flake8" {
    Invoke-PoetryCommand @("run", "flake8", "auto_deinterlancer.py", "modules", "tests", ".github/scripts")
}

Invoke-Step "Run Pylint" {
    Invoke-PoetryCommand @("run", "pylint", "auto_deinterlancer.py", "modules", "tests", ".github/scripts")
}

Invoke-Step "Run Radon Complexity" {
    if (-not (Test-Path "assets")) {
        New-Item -ItemType Directory -Path "assets" | Out-Null
    }

    Invoke-PoetryCommand @("run", "python", ".github/scripts/enforce_radon_grade.py", "--summary-out", "assets/radon_summary.md")
    Get-Content "assets/radon_summary.md"
}

Invoke-Step "Run Radon Maintainability" {
    if (-not (Test-Path "assets")) {
        New-Item -ItemType Directory -Path "assets" | Out-Null
    }

    Invoke-PoetryCommand @("run", "python", ".github/scripts/enforce_radon_grade.py", "--metric", "mi", "--summary-out", "assets/radon_mi_summary.md")
    Get-Content "assets/radon_mi_summary.md"
}

Invoke-Step "Run Radon Raw Metrics" {
    if (-not (Test-Path "assets")) {
        New-Item -ItemType Directory -Path "assets" | Out-Null
    }

    Invoke-PoetryCommand @("run", "radon", "raw", "auto_deinterlancer.py", "modules", "tests", ".github/scripts") |
        Tee-Object -FilePath "assets/radon_raw.txt"
    Get-Content "assets/radon_raw.txt"
}

Invoke-Step "Run Radon Halstead Metrics" {
    if (-not (Test-Path "assets")) {
        New-Item -ItemType Directory -Path "assets" | Out-Null
    }

    Invoke-PoetryCommand @("run", "radon", "hal", "auto_deinterlancer.py", "modules", "tests", ".github/scripts") |
        Tee-Object -FilePath "assets/radon_hal.txt"
    Get-Content "assets/radon_hal.txt"
}

Invoke-Step "Run Markdown Auto-Delint" {
    $mdFiles = git ls-files "*.md"
    if ($mdFiles) {
        Invoke-PoetryCommand (@("run", "mdformat") + $mdFiles)
    }
}

$createdMockVideo = $false
try {
    Invoke-Step "Run Markdown Lint" {
        Invoke-PoetryCommand @("run", "pymarkdown", "-d", "MD013", "scan", ".")
    }

    Invoke-Step "Create Mock Environment" {
        if (-not (Test-Path "input")) {
            New-Item -ItemType Directory -Path "input" | Out-Null
        }
        if (-not (Test-Path "input\test_video.mp4")) {
            New-Item -ItemType File -Path "input\test_video.mp4" | Out-Null
            $script:createdMockVideo = $true
        }
    }

    Invoke-Step "Run tests with coverage" {
        if (-not (Test-Path "assets")) {
            New-Item -ItemType Directory -Path "assets" | Out-Null
        }

        $previousSkipFlag = $env:AUTO_VHS_SKIP_HW_DETECT
        $env:AUTO_VHS_SKIP_HW_DETECT = "1"
        try {
            Invoke-PoetryCommand @(
                "run",
                "pytest",
                "--cov=modules",
                "--cov=auto_deinterlancer",
                "--cov-branch",
                "--cov-report=xml:assets/coverage.xml",
                "--cov-report=term",
                "--cov-fail-under=90",
                "tests/"
            )
        }
        finally {
            if ($null -eq $previousSkipFlag) {
                Remove-Item Env:AUTO_VHS_SKIP_HW_DETECT -ErrorAction SilentlyContinue
            }
            else {
                $env:AUTO_VHS_SKIP_HW_DETECT = $previousSkipFlag
            }
        }
    }

    Invoke-Step "Enforce Per-File Coverage >= 90%" {
        if (-not (Test-Path "assets/coverage.xml")) {
            throw "assets/coverage.xml was not generated by pytest"
        }

        Invoke-PoetryCommand @(
            "run",
            "python",
            ".github/scripts/enforce_per_file_coverage.py",
            "assets/coverage.xml",
            "90"
        )
    }

    Invoke-Step "Generate Coverage Summary" {
        if (-not (Test-Path "assets/coverage.xml")) {
            throw "assets/coverage.xml was not generated by pytest"
        }

        $summary = Invoke-PoetryCommand @(
            "run",
            "python",
            ".github/scripts/generate_coverage_summary.py",
            "assets/coverage.xml"
        )
        $summaryFilePath = Join-Path $repoRoot "assets/coverage_summary.md"
        [System.IO.File]::WriteAllLines(
            $summaryFilePath,
            [string[]]$summary,
            (New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false)
        )
        Write-Output "Coverage summary written: assets/coverage_summary.md"
    }

    Invoke-Step "Generate coverage badge" {
        if (-not (Test-Path "assets")) {
            New-Item -ItemType Directory -Path "assets" | Out-Null
        }

        if (-not (Test-Path "assets/coverage.xml")) {
            throw "assets/coverage.xml was not generated by pytest"
        }

        Invoke-PoetryCommand @("run", "genbadge", "coverage", "-i", "assets/coverage.xml", "-o", "assets/coverage.svg")
        Write-Output "Badge updated: assets/coverage.svg"
    }

    Write-Output "Local pipeline completed successfully."
}
finally {
    if ($createdMockVideo -and (Test-Path "input\test_video.mp4")) {
        Remove-Item "input\test_video.mp4" -Force -ErrorAction SilentlyContinue
    }
}
