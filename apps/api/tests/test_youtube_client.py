from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.youtube_client import (
    ChannelIdentity,
    YouTubeOAuthStateError,
    YouTubeAuthorizationRequired,
    YouTubeClient,
    YOUTUBE_SCOPES,
)


def test_youtube_scopes_are_exactly_the_two_read_only_scopes():
    """A scope regression could turn a read-only dashboard into a publisher."""
    assert YOUTUBE_SCOPES == [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]


class _Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _ChannelsResource:
    def list(self, **kwargs):
        assert kwargs == {"part": "snippet,contentDetails", "mine": True}
        return _Request(
            {
                "items": [
                    {
                        "id": "UC-skeleton",
                        "snippet": {"title": "Skeleton Coast Fishing Adventures & Tours"},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UU-skeleton"}},
                    }
                ]
            }
        )


class _DataApi:
    def channels(self):
        return _ChannelsResource()


def test_get_authenticated_channel_returns_the_authorized_channel_identity(tmp_path: Path):
    """Removing the channel lookup or returning an arbitrary id must fail this test."""
    client = YouTubeClient(token_path=tmp_path / "token.json", data_api=_DataApi())

    channel = client.get_authenticated_channel()

    assert channel == ChannelIdentity(
        channel_id="UC-skeleton",
        title="Skeleton Coast Fishing Adventures & Tours",
        uploads_playlist_id="UU-skeleton",
    )


def test_get_authenticated_channel_requires_a_token_before_any_google_request(tmp_path: Path):
    """Deleting token validation would allow a vague downstream Google error."""
    client = YouTubeClient(token_path=tmp_path / "missing-token.json")

    with pytest.raises(YouTubeAuthorizationRequired, match="authorization"):
        client.get_authenticated_channel()


class _Credentials:
    def to_json(self):
        return '{"token":"very-secret-access-token"}'


class _Flow:
    def __init__(self):
        self.credentials = _Credentials()
        self.code = None

    def authorization_url(self, **kwargs):
        assert kwargs == {"access_type": "offline", "prompt": "consent"}
        return "https://accounts.example.test/authorize", "google-issued-state"

    def fetch_token(self, *, code):
        self.code = code


def test_oauth_callback_rejects_an_unknown_state_and_never_writes_a_token(tmp_path: Path):
    """Removing state validation would accept a forged browser callback."""
    flow = _Flow()
    client = YouTubeClient(
        token_path=tmp_path / "private" / "token.json",
        client_secret_path=tmp_path / "client.json",
        flow_factory=lambda **_: flow,
    )

    client.start_oauth()

    with pytest.raises(YouTubeOAuthStateError, match="state"):
        client.complete_oauth(code="authorization-code", state="forged-state")

    assert not client.token_path.exists()
    assert flow.code is None


def test_oauth_callback_validates_state_and_persists_token_without_returning_it(tmp_path: Path):
    """A callback that exposes credentials or skips persistence would break this flow."""
    flow = _Flow()
    client = YouTubeClient(
        token_path=tmp_path / "private" / "token.json",
        client_secret_path=tmp_path / "client.json",
        flow_factory=lambda **_: flow,
    )

    start = client.start_oauth()
    completed = client.complete_oauth(code="authorization-code", state=start.state)

    assert start.authorization_url == "https://accounts.example.test/authorize"
    assert completed is None
    assert flow.code == "authorization-code"
    assert client.token_path.read_text(encoding="utf-8") == '{"token":"very-secret-access-token"}'
    assert not client.oauth_state_path.exists()


class _PlaylistItems:
    def list(self, **kwargs):
        if "pageToken" not in kwargs:
            assert kwargs["playlistId"] == "UU-skeleton"
            return _Request({"items": [{"contentDetails": {"videoId": "long"}}], "nextPageToken": "p2"})
        return _Request({"items": [{"contentDetails": {"videoId": "short"}}]})


class _Videos:
    def list(self, **kwargs):
        assert set(kwargs["id"].split(",")) == {"long", "short"}
        return _Request({"items": [
            {"id": "long", "snippet": {"title": "Pilchard story", "publishedAt": "2026-09-01T10:00:00Z"}, "contentDetails": {"duration": "PT1M1S"}},
            {"id": "short", "snippet": {"title": "A fish", "publishedAt": "2026-09-02T10:00:00Z"}, "contentDetails": {"duration": "PT59S"}},
        ]})


class _UploadsApi(_DataApi):
    def playlistItems(self):
        return _PlaylistItems()

    def videos(self):
        return _Videos()


def test_list_uploaded_videos_paginates_and_infers_long_and_short_formats(tmp_path: Path):
    """Ignoring pages or duration would silently omit uploads or misclassify Shorts."""
    client = YouTubeClient(token_path=tmp_path / "token.json", data_api=_UploadsApi())

    videos = client.list_uploaded_videos("UU-skeleton")

    assert [(video.video_id, video.video_type, video.duration_seconds) for video in videos] == [
        ("long", "long_form", 61),
        ("short", "short", 59),
    ]


class _Reports:
    def query(self, **kwargs):
        if kwargs["metrics"] == "returningViewers":
            return _Request({"columnHeaders": [{"name": "returningViewers"}], "rows": [[19]]})
        if kwargs["dimensions"] == "video":
            return _Request({"columnHeaders": [{"name": name} for name in ["views", "estimatedMinutesWatched", "averageViewDuration", "subscribersGained", "impressions", "impressionsCtr", "averageViewPercentage"]], "rows": [[422, 480.0, 68.0, 5, 5000, 7.1, 42.8]]})
        if kwargs["dimensions"] == "insightTrafficSourceType":
            return _Request({"columnHeaders": [{"name": "insightTrafficSourceType"}, {"name": "views"}], "rows": [["BROWSE", 240], ["EXTERNAL", 20]]})
        raise AssertionError(f"Unexpected Analytics query: {kwargs}")


class _AnalyticsApi:
    def reports(self):
        return _Reports()


def test_fetch_video_metrics_maps_mocked_data_and_analytics_responses(tmp_path: Path):
    """Changing Analytics column mapping or traffic normalization must fail this test."""
    client = YouTubeClient(token_path=tmp_path / "token.json", data_api=_DataApi(), analytics_api=_AnalyticsApi())

    metrics = client.fetch_video_metrics("abc123", "UC-skeleton", "2026-09-01", "2026-09-06")

    assert metrics["views"] == 422
    assert metrics["ctr"] == 7.1
    assert metrics["traffic"] == {"BROWSE": 240 / 260, "EXTERNAL": 20 / 260}
    assert metrics["returning_viewers"] == 19


def test_status_and_sync_report_configuration_required_before_any_channel_query(monkeypatch):
    """Without the single expected id, sync must not accept whichever account OAuth has."""
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.delenv("EXPECTED_YOUTUBE_CHANNEL_ID", raising=False)
    get_settings.cache_clear()

    client = TestClient(create_app())
    status = client.get("/youtube/status")
    sync = client.post("/youtube/sync")

    assert status.status_code == 200
    assert status.json()["status"] == "configuration_required"
    assert sync.status_code == 503
    assert "EXPECTED_YOUTUBE_CHANNEL_ID" in sync.json()["detail"]
    get_settings.cache_clear()


def test_sync_rejects_a_different_authorized_channel_with_http_409(monkeypatch):
    """Removing the identity check would make V1 ingest an unrestricted second channel."""
    from app.config import get_settings
    from app.main import create_app
    from app.routes import youtube

    class WrongChannelClient:
        def get_authenticated_channel(self):
            return ChannelIdentity("UC-wrong", "Wrong account", "UU-wrong")

    monkeypatch.setenv("EXPECTED_YOUTUBE_CHANNEL_ID", "UC-skeleton")
    monkeypatch.setattr(youtube, "get_youtube_client", lambda: WrongChannelClient())
    get_settings.cache_clear()

    response = TestClient(create_app()).post("/youtube/sync")

    assert response.status_code == 409
    assert "one channel" in response.json()["detail"].lower()
    get_settings.cache_clear()
