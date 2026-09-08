[CmdletBinding()]
param(
    [switch]$TestMode,
    [string]$MasterProjectFolder = "I:\YouTube Projects",
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [string]$WebUrl = "http://127.0.0.1:5173",
    [string]$PythonPath = "",
    [string]$NodeCommand = "node",
    [string]$FfprobeCommand = "ffprobe"
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$failed = $false

function Pass([string]$Message) { Write-Host "$Message`: PASS" }
function Fail([string]$Message) { Write-Host "$Message`: FAIL"; $script:failed = $true }

function Assert-LoopbackUrl([string]$Value, [string]$Name) {
    try { $uri = [Uri]$Value } catch { Fail "$Name is not a valid URL"; return $false }
    if ($uri.Scheme -ne "http" -or $uri.Host -notin @("127.0.0.1", "localhost", "::1")) {
        Fail "$Name must use local HTTP only"
        return $false
    }
    return $true
}

if (-not $TestMode -and $MasterProjectFolder -ne "I:\YouTube Projects") {
    Fail "V1 master folder must be I:\YouTube Projects"
}
if (-not $PythonPath) {
    $PythonPath = Join-Path $repoRoot "helper\.venv\Scripts\python.exe"
}

try {
    $pythonVersion = (& $PythonPath --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $pythonVersion -notmatch "Python\s+(\d+)\.(\d+)") { throw "unrecognized version" }
    if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 12)) { throw $pythonVersion }
    Pass "Python 3.12+"
} catch { Fail "Python 3.12+" }

try {
    $nodeVersion = (& $NodeCommand --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch "v(\d+)") { throw "unrecognized version" }
    if ([int]$Matches[1] -lt 20) { throw $nodeVersion }
    Pass "Node 20+"
} catch { Fail "Node 20+" }

try {
    $ffprobeVersion = (& $FfprobeCommand -version 2>&1 | Select-Object -First 1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $ffprobeVersion) { throw "unavailable" }
    Pass "ffprobe"
} catch { Fail "ffprobe" }

if (Test-Path -LiteralPath $MasterProjectFolder -PathType Container) {
    Pass "Master folder ($MasterProjectFolder)"
} else {
    Fail "Master folder ($MasterProjectFolder)"
    Write-Host "Create it explicitly, then rerun: New-Item -ItemType Directory -Path '$MasterProjectFolder'"
}

$apiIsLocal = Assert-LoopbackUrl $ApiBaseUrl "API_BASE_URL"
$webIsLocal = Assert-LoopbackUrl $WebUrl "Web URL"

if ($apiIsLocal) {
    try {
        $healthResponse = Invoke-WebRequest -UseBasicParsing -Uri ($ApiBaseUrl.TrimEnd("/") + "/health") -TimeoutSec 10
        $health = $healthResponse.Content | ConvertFrom-Json
        if ($healthResponse.StatusCode -ne 200 -or $health.status -ne "ok") { throw "unexpected health response" }
        Pass "API /health"
    } catch { Fail "API /health" }
}

if ($webIsLocal) {
    try {
        $webResponse = Invoke-WebRequest -UseBasicParsing -Uri $WebUrl -TimeoutSec 10
        if ($webResponse.StatusCode -ne 200 -or -not $webResponse.Content) { throw "unexpected web response" }
        Pass "Web app"
    } catch { Fail "Web app" }
}

if (-not $failed -and $apiIsLocal) {
    try {
        $helperArgs = @{
            SyncOnce = $true
            PythonPath = $PythonPath
            MasterProjectFolder = $MasterProjectFolder
            ApiBaseUrl = $ApiBaseUrl
            AllowTestMaster = $TestMode
        }
        & (Join-Path $PSScriptRoot "start-helper.ps1") @helperArgs | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "helper failed" }
        Pass "Helper manual sync"
    } catch {
        Write-Host "Helper manual sync detail: $($_.Exception.Message)"
        Fail "Helper manual sync"
    }
}

if ($apiIsLocal) {
    $youtubeStatus = $null
    try {
        $youtube = Invoke-RestMethod -Uri ($ApiBaseUrl.TrimEnd("/") + "/youtube/status") -TimeoutSec 10
        $youtubeStatus = [string]$youtube.status
    } catch {
        $errorBody = $_.ErrorDetails.Message
        if ($errorBody) {
            try {
                $errorPayload = $errorBody | ConvertFrom-Json
                if ($errorPayload.detail -match "authorization.*required") { $youtubeStatus = "authorization_required" }
                elseif ($errorPayload.detail -match "configur") { $youtubeStatus = "configuration_required" }
            } catch { }
        }
    }
    if ($youtubeStatus -eq "authorized") { $youtubeStatus = "connected" }
    if ($youtubeStatus -in @("connected", "authorization_required", "configuration_required")) {
        Write-Host "YouTube status: PASS ($youtubeStatus)"
    } else {
        Fail "YouTube status"
    }
}

if ($failed) {
    Write-Host "SMOKE TEST: FAIL"
    exit 1
}
Write-Host "SMOKE TEST: PASS"
exit 0
