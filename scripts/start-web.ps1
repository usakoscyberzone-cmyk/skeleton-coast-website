[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [string]$NodeCommand = "node"
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$webRoot = Join-Path $repoRoot "apps\web"
$vite = Join-Path $webRoot "node_modules\.bin\vite.cmd"

try { $nodeVersion = (& $NodeCommand --version 2>&1 | Out-String).Trim() } catch {
    throw "Node.js 20 or newer is required and was not found."
}
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch "v(\d+)") {
    throw "Could not verify Node.js: $NodeCommand"
}
if ([int]$Matches[1] -lt 20) { throw "Node.js 20 or newer is required; found $nodeVersion" }
if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
    throw "Frontend dependencies are missing. Run 'corepack pnpm install --frozen-lockfile' in apps\web."
}
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
if ($CheckOnly) {
    Write-Host "Web start check: PASS (127.0.0.1:5173)"
    exit 0
}

Push-Location $webRoot
try {
    & $vite --host 127.0.0.1 --port 5173
    if ($LASTEXITCODE -ne 0) { throw "Web app exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
