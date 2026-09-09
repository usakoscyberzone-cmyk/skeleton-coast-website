[CmdletBinding()]
param(
    [switch]$Reload,
    [switch]$CheckOnly,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$apiRoot = Join-Path $repoRoot "apps\api"
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

Import-LocalEnvironment $envFile
if (-not $PythonPath) { $PythonPath = Join-Path $apiRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "API Python environment is missing. Create it as documented: $PythonPath"
}
$versionOutput = (& $PythonPath --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "Python\s+(\d+)\.(\d+)") {
    throw "Could not verify Python: $PythonPath"
}
if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 12)) {
    throw "Python 3.12 or newer is required; found $versionOutput"
}
& $PythonPath -c "import uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) { throw "API dependencies are missing. Install apps/api with the dev extra." }
if ($CheckOnly) {
    Write-Host "API start check: PASS (127.0.0.1:8000)"
    exit 0
}

$arguments = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
if ($Reload) { $arguments += "--reload" }
Push-Location $apiRoot
try {
    & $PythonPath @arguments
    if ($LASTEXITCODE -ne 0) { throw "API exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
