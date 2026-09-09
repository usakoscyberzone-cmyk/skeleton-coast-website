[CmdletBinding()]
param(
    [switch]$SyncOnce,
    [string]$PythonPath = "",
    [string]$MasterProjectFolder = "I:\YouTube Projects",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [switch]$AllowTestMaster
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$helperRoot = Join-Path $repoRoot "helper"
$envFile = Join-Path $repoRoot ".env"

function Import-LocalEnvironment([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $parts = $trimmed.Split("=", 2)
        if (-not [Environment]::GetEnvironmentVariable($parts[0], "Process")) {
            [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
        }
    }
}

function Assert-LoopbackUrl([string]$Value, [string]$Name) {
    $uri = [Uri]$Value
    if ($uri.Scheme -ne "http" -or $uri.Host -notin @("127.0.0.1", "localhost", "::1")) {
        throw "$Name must use HTTP on this computer only (127.0.0.1 or localhost)."
    }
}

Import-LocalEnvironment $envFile
if ($env:MASTER_PROJECT_FOLDER -and $MasterProjectFolder -eq "I:\YouTube Projects") {
    $MasterProjectFolder = $env:MASTER_PROJECT_FOLDER
}
if ($env:API_BASE_URL -and $ApiBaseUrl -eq "http://127.0.0.1:8000") {
    $ApiBaseUrl = $env:API_BASE_URL
}
if (-not $AllowTestMaster -and $MasterProjectFolder -ne "I:\YouTube Projects") {
    throw "V1 requires the exact master folder I:\YouTube Projects."
}
Assert-LoopbackUrl $ApiBaseUrl "API_BASE_URL"
if (-not (Test-Path -LiteralPath $MasterProjectFolder -PathType Container)) {
    throw "Master folder does not exist: $MasterProjectFolder"
}

if (-not $PythonPath) {
    $PythonPath = Join-Path $helperRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Helper Python environment is missing. Create it as documented: $PythonPath"
}
$versionOutput = (& $PythonPath --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "Python\s+(\d+)\.(\d+)") {
    throw "Could not verify Python: $PythonPath"
}
if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 12)) {
    throw "Python 3.12 or newer is required; found $versionOutput"
}

$env:MASTER_PROJECT_FOLDER = $MasterProjectFolder
$env:API_BASE_URL = $ApiBaseUrl.TrimEnd("/")
Push-Location $helperRoot
try {
    if ($SyncOnce) {
        & $PythonPath -m skeleton_helper --sync-once
    } else {
        & $PythonPath -m skeleton_helper
    }
    if ($LASTEXITCODE -ne 0) { throw "Windows helper exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
