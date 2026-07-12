$ErrorActionPreference = "Stop"

function Get-WingetPackageInstalled {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id
    )

    $listOutput = winget list --id $Id --exact --accept-source-agreements 2>&1
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    return ($listOutput | Out-String) -match [regex]::Escape($Id)
}

function Install-WingetPackageIfMissing {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id,
        [Parameter(Mandatory = $true)]
        [string]$DisplayName
    )

    if (Get-WingetPackageInstalled -Id $Id) {
        Write-Output "[INFO] $DisplayName already installed ($Id)."
        return
    }

    Write-Output "[INFO] Installing $DisplayName ($Id) via winget..."
    winget install --id $Id --exact --silent --accept-source-agreements --accept-package-agreements

    if ($LASTEXITCODE -ne 0) {
        throw "winget install failed for $Id with exit code $LASTEXITCODE"
    }

    if (Get-WingetPackageInstalled -Id $Id) {
        Write-Output "[INFO] Installed $DisplayName ($Id)."
        return
    }

    throw "$DisplayName install command completed but package was not detected in winget list."
}

Write-Output "=================================================="
Write-Output "[INFO] Installing PR review tooling (GitHub CLI + GitKraken CLI)..."

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget is not available on this system. Install App Installer from Microsoft Store and rerun."
}

Install-WingetPackageIfMissing -Id "GitHub.cli" -DisplayName "GitHub CLI"
Install-WingetPackageIfMissing -Id "GitKraken.cli" -DisplayName "GitKraken CLI"

Write-Output "[INFO] PR review tooling installation completed."
