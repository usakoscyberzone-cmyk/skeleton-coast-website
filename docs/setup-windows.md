# Windows setup and operation

These instructions keep every service on this PC, use `I:\YouTube Projects` as the only V1 master folder, and do not install or delete anything automatically.

## 1. Prerequisites

Install these yourself if they are not already available:

- Git for Windows.
- 64-bit Python 3.12 or newer, including the `py` launcher.
- Node.js 20 or newer.
- FFmpeg with `ffprobe` on `PATH`.

Verify them in PowerShell:

```powershell
git --version
py -3.12 --version
node --version
ffprobe -version
```

If FFmpeg is missing and you choose to use Windows Package Manager, run:

```powershell
winget install --id Gyan.FFmpeg --exact
```

Close and reopen PowerShell, then rerun `ffprobe -version`.

## 2. Clone or open the repository

If the project has been published to a Git remote, enter its URL when prompted:

```powershell
$RepositoryUrl = Read-Host "Git repository URL"
Set-Location "$env:USERPROFILE\Documents"
git clone $RepositoryUrl skeleton-coast-growth-dashboard
Set-Location .\skeleton-coast-growth-dashboard
```

If you already have this project folder, open PowerShell in it and verify the root:

```powershell
git rev-parse --show-toplevel
```

All remaining commands assume that PowerShell is at that repository root.

## 3. Create the master folder explicitly

Check first:

```powershell
Test-Path -LiteralPath 'I:\YouTube Projects'
```

If it returns `False`, confirm that drive `I:` is the intended media drive, then create the folder yourself:

```powershell
New-Item -ItemType Directory -Path 'I:\YouTube Projects'
```

The scripts never create this master folder implicitly. Each direct child is treated as a project. During a scan, only these standard output folders may be created inside it: `Thumbnails`, `Shorts`, `Captions`, `Metadata`, `Analytics`, and `Exports`.

## 4. Install local dependencies

Create separate Python environments for the API and helper:

```powershell
py -3.12 -m venv .\apps\api\.venv
.\apps\api\.venv\Scripts\python.exe -m pip install --upgrade pip
.\apps\api\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"

py -3.12 -m venv .\helper\.venv
.\helper\.venv\Scripts\python.exe -m pip install --upgrade pip
.\helper\.venv\Scripts\python.exe -m pip install -e ".\helper[dev]"

Set-Location .\apps\web
corepack pnpm install --frozen-lockfile
Set-Location ..\..
```

No start or smoke script installs dependencies.

## 5. Configure the environment

Copy the example once and edit the copy locally:

```powershell
Copy-Item -LiteralPath .\.env.example -Destination .\.env
notepad .\.env
```

Keep these exact local values:

```dotenv
MASTER_PROJECT_FOLDER=I:\YouTube Projects
API_BASE_URL=http://127.0.0.1:8000
VITE_API_BASE_URL=http://127.0.0.1:8000
YOUTUBE_REDIRECT_URI=http://127.0.0.1:8000/youtube/oauth/callback
```

Set `EXPECTED_YOUTUBE_CHANNEL_ID` to the exact channel ID for **Skeleton Coast Fishing Adventures & Tours**. V1 refuses a different channel. Store the downloaded OAuth client JSON and `YOUTUBE_TOKEN_PATH` outside this repository. Do not paste secrets into terminal commands, logs, screenshots, or Git.

See [YouTube OAuth](youtube-oauth.md) for the Google Cloud configuration. `.env` and token artifacts are ignored by Git.

## 6. Verify and start each service

Dependency-only checks do not launch services:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-api.ps1 -CheckOnly
powershell -ExecutionPolicy Bypass -File .\scripts\start-web.ps1 -CheckOnly
```

Open three PowerShell windows at the repository root and run one command in each:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-api.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-web.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-helper.ps1
```

The API binds only to `127.0.0.1:8000`; the web app binds only to `127.0.0.1:5173`. The helper watches only direct children of `I:\YouTube Projects`, starts the observer before its initial sync, and stops the observer cleanly on exit. Press `Ctrl+C` in each window to stop it.

For a single manual helper sync without starting the watcher:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-helper.ps1 -SyncOnce
```

## 7. Authorize the one YouTube channel

Start the API first. Authorization begins only when you explicitly run these commands:

```powershell
$OAuth = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/youtube/oauth/start'
Start-Process $OAuth.authorization_url
```

Sign in to the Google account that owns or administers **Skeleton Coast Fishing Adventures & Tours**, approve only the displayed read-only access, and complete the local callback. Verify the result:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/youtube/status'
```

The response must identify the configured channel. `authorization_required` means authorization still needs to be completed; `configuration_required` means `.env` is incomplete. `channel_mismatch` must not be bypassed—authorize the correct channel or correct the expected ID.

The app never changes YouTube content or settings. OAuth grants no upload or metadata-write scope.

## 8. Run tests and smoke checks

Automated suites:

```powershell
.\apps\api\.venv\Scripts\python.exe -m pytest .\apps\api\tests -v
.\helper\.venv\Scripts\python.exe -m pytest .\helper\tests -v
Set-Location .\apps\web
.\node_modules\.bin\vitest.cmd run
.\node_modules\.bin\tsc.cmd -b
.\node_modules\.bin\vite.cmd build
Set-Location ..\..
```

With API, web app, and helper prerequisites ready, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
```

It checks Python 3.12+, Node 20+, `ffprobe`, the exact master folder, API health, the web page, one real manual helper sync, and YouTube status. It accepts a connected channel or the clear setup states `authorization_required` and `configuration_required`. It does not start OAuth, create a project, alter media, or touch Resolve.

`-TestMode` exists only for automated tests with an explicitly supplied disposable master and localhost fixture services. Do not use it as the normal operating configuration.

## 9. Recover a replaced YouTube lock sidecar

Normally no repair is needed. If `/youtube/status` reports that credential storage is not securely configured after an external program deleted or recreated `youtube-token.json.lock`:

1. Stop both the API and helper with `Ctrl+C`.
2. Confirm in Task Manager that their Python processes have exited.
3. From the repository root, run the explicit repair:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\repair-youtube-lock.ps1 -ConfirmServiceStopped
```

The repair reads only the configured absolute `YOUTUBE_TOKEN_PATH`, computes that exact `.lock` sidecar, and attempts a zero-wait acquisition of the same named Windows mutex used by the app. It fails closed if the mutex is held or the sidecar is a reparse point. When safe, it clears only that lock sidecar and applies a current-user-only ACL. It does not delete or rewrite the OAuth token, SQLite database, `.env`, media, assets, or Resolve files.

Restart the API and rerun the smoke test. Never delete the token or database as a lock-recovery shortcut.
