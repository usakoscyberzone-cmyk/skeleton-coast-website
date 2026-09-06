# Read-only YouTube OAuth setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. Enable **YouTube Data API v3** and **YouTube Analytics API** for that project.
3. Configure the OAuth consent screen. Add the Google account that administers Skeleton Coast Fishing Adventures & Tours as a test user if the app remains in testing.
4. Create OAuth 2.0 credentials. Use **Desktop** credentials, or a **Web application** credential with `http://127.0.0.1:8000/youtube/oauth/callback` as an authorized redirect URI.
5. Download the credential JSON to a private local folder. Put its path in `YOUTUBE_CLIENT_SECRET_PATH`; do not commit it. Set `YOUTUBE_TOKEN_PATH` to an absolute path **outside the repository**, for example `C:\Users\YOUR_NAME\AppData\Local\SkeletonCoastGrowthDashboard\youtube-token.json`. The application fails closed unless it can apply and verify a current-user-only Windows ACL on the parent directory, OAuth state, consumed-state, temporary, lock, and final token artifacts.
6. Set `EXPECTED_YOUTUBE_CHANNEL_ID` to the exact Skeleton Coast channel ID. This is mandatory: V1 refuses to sync any other channel.
7. Start the dashboard, open `GET /youtube/oauth/start`, complete Google authorization, then visit `GET /youtube/status`. It should progress from `authorization_required` to the configured channel state before a sync.

The application requests only `youtube.readonly` and `yt-analytics.readonly`. It has no upload, publishing, metadata-editing, playlist-management, or channel-management scope.

The targeted Analytics endpoint does not expose thumbnail impressions, thumbnail CTR, or returning-viewer counts for this channel report. Those fields remain `null` when unavailable; the dashboard does not fabricate them and V1 does not create bulk YouTube Reporting jobs.
