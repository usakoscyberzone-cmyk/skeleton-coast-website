# Skeleton Coast Growth Dashboard

A private, local-first Windows dashboard for the **Skeleton Coast Fishing Adventures & Tours** YouTube channel. It watches `I:\YouTube Projects`, inventories media, ingests read-only channel analytics, creates project-local supporting assets, and recommends evidence-based next actions.

## Safety boundaries

- V1 accepts exactly one YouTube channel, enforced by `EXPECTED_YOUTUBE_CHANNEL_ID`.
- YouTube access uses only `youtube.readonly` and `yt-analytics.readonly`; the app cannot upload, publish, or change titles, thumbnails, descriptions, playlists, or channel settings.
- The helper may read/analyze media and create assets only in a registered project's standard output folders.
- Neither the helper nor the dashboard modifies DaVinci Resolve projects or timelines.
- Services bind to `127.0.0.1`; this is not a public web service.

## Start here

Follow [Windows setup](docs/setup-windows.md) for prerequisites, installation, OAuth authorization, startup, safe smoke testing, and credential-lock recovery.

After setup, open three PowerShell windows from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-api.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-web.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-helper.ps1
```

Then open `http://127.0.0.1:5173`.

Run the live preflight after all three services are running:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1
```
