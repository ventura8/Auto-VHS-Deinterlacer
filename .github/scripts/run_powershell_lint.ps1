param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$SettingsPath,
    [Version]$MinimumVersion = [Version]"1.24.0"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $SettingsPath) {
    $SettingsPath = Join-Path $RepoRoot "tools\psscriptanalyzer.settings.psd1"
}

if (-not (Test-Path $SettingsPath)) {
    throw "PSScriptAnalyzer settings file not found: $SettingsPath"
}

function Get-HighestInstalledAnalyzerVersion {
    $available = Get-Module -ListAvailable -Name PSScriptAnalyzer | Sort-Object Version -Descending
    if (-not $available) {
        return $null
    }

    return $available[0].Version
}

function Install-AnalyzerModule {
    try {
        Set-PSRepository -Name PSGallery -InstallationPolicy Trusted -ErrorAction Stop
    }
    catch {
        Write-Output "[INFO] Could not set PSGallery policy to Trusted automatically: $($_.Exception.Message)"
    }

    if (-not (Get-PackageProvider -ListAvailable -Name NuGet -ErrorAction SilentlyContinue)) {
        Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null
    }

    Install-Module -Name PSScriptAnalyzer -Repository PSGallery -Scope CurrentUser -Force -AllowClobber -MinimumVersion $MinimumVersion
}

$installedVersion = Get-HighestInstalledAnalyzerVersion
if ($null -eq $installedVersion -or $installedVersion -lt $MinimumVersion) {
    Write-Output "[INFO] Installing PSScriptAnalyzer >= $MinimumVersion ..."
    Install-AnalyzerModule
}

Import-Module PSScriptAnalyzer -MinimumVersion $MinimumVersion -ErrorAction Stop

$scriptPaths = @(
    (Join-Path $RepoRoot "install.ps1"),
    (Join-Path $RepoRoot "run_pipeline_localy.ps1")
)
$scriptPaths += Get-ChildItem -Path (Join-Path $RepoRoot ".github\scripts") -Filter "*.ps1" -File | Select-Object -ExpandProperty FullName
$scriptPaths = $scriptPaths | Where-Object { Test-Path $_ } | Sort-Object -Unique

if ($scriptPaths.Count -eq 0) {
    throw "No PowerShell scripts found to lint."
}

$issues = @()
foreach ($scriptPath in $scriptPaths) {
    $issues += Invoke-ScriptAnalyzer -Path $scriptPath -Settings $SettingsPath
}

if ($issues.Count -gt 0) {
    $issues | Select-Object RuleName, Severity, ScriptName, Line, Message | Format-Table -AutoSize
    throw "PowerShell lint failed with $($issues.Count) issue(s)."
}

Write-Output "PowerShell lint passed: no issues found."