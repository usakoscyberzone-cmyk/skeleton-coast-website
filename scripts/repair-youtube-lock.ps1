[CmdletBinding()]
param(
    [switch]$ConfirmServiceStopped,
    [string]$TokenPath = "",
    [switch]$TestMode
)

$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$envFile = Join-Path $repoRoot ".env"

if (-not $ConfirmServiceStopped) {
    throw "Stop the API and helper, then rerun with -ConfirmServiceStopped."
}

if (Test-Path -LiteralPath $envFile -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) { continue }
        $parts = $trimmed.Split("=", 2)
        if (-not [Environment]::GetEnvironmentVariable($parts[0], "Process")) {
            [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
        }
    }
}

$configuredToken = $env:YOUTUBE_TOKEN_PATH
if (-not $TokenPath) { $TokenPath = $configuredToken }
if (-not $TokenPath) { throw "YOUTUBE_TOKEN_PATH is not configured." }
if (-not [IO.Path]::IsPathRooted($TokenPath)) { throw "YOUTUBE_TOKEN_PATH must be absolute." }
$TokenPath = [IO.Path]::GetFullPath($TokenPath)
if (-not $TestMode -and -not $configuredToken) {
    throw "YOUTUBE_TOKEN_PATH must be configured in .env before repair."
}
if (-not $TestMode -and ([IO.Path]::GetFullPath($configuredToken) -ne $TokenPath)) {
    throw "Repair is limited to the YOUTUBE_TOKEN_PATH configured in .env."
}
$repoPrefix = $repoRoot.TrimEnd("\") + "\"
if ($TokenPath.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "YOUTUBE_TOKEN_PATH must remain outside this repository."
}

$tokenParent = Split-Path -Parent $TokenPath
if (-not (Test-Path -LiteralPath $tokenParent -PathType Container)) {
    throw "The configured token directory does not exist: $tokenParent"
}
$lockPath = $TokenPath + ".lock"
if (Test-Path -LiteralPath $lockPath) {
    $item = Get-Item -LiteralPath $lockPath -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to repair a reparse-point lock sidecar."
    }
}

$normalized = $TokenPath.ToLowerInvariant()
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $hashBytes = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized))
} finally {
    $sha.Dispose()
}
$hash = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
$mutex = New-Object Threading.Mutex($false, ("Local\SkeletonCoastYouTubeToken-" + $hash))
$acquired = $false
try {
    try { $acquired = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { throw "The YouTube credential mutex is held. Stop the API/helper and retry." }

    [IO.File]::WriteAllText($lockPath, "", (New-Object Text.UTF8Encoding($false)))
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $acl = New-Object Security.AccessControl.FileSecurity
    $acl.SetOwner($identity.User)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object Security.AccessControl.FileSystemAccessRule(
        $identity.User,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.AccessControlType]::Allow
    )
    [void]$acl.AddAccessRule($rule)
    [IO.File]::SetAccessControl($lockPath, $acl)

    $verified = [IO.File]::GetAccessControl($lockPath)
    $rules = @($verified.Access)
    if ($rules.Count -ne 1 -or $rules[0].IsInherited -or $rules[0].AccessControlType -ne "Allow") {
        throw "Lock sidecar ACL verification failed."
    }
    $ruleSid = $rules[0].IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($ruleSid -ne $identity.User.Value -or (($rules[0].FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -ne [Security.AccessControl.FileSystemRights]::FullControl)) {
        throw "Lock sidecar ACL verification failed."
    }
    Write-Host "YouTube lock sidecar repair: PASS"
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
