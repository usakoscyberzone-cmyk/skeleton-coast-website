"""Read-only OAuth and YouTube API access for the private dashboard."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
from datetime import UTC, datetime, timedelta
import re

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


class YouTubeAuthorizationRequired(RuntimeError):
    """Raised before an API call when the local OAuth grant is unavailable."""


class YouTubeOAuthStateError(RuntimeError):
    """Raised when an OAuth callback is not tied to a locally initiated flow."""


@dataclass(frozen=True)
class ChannelIdentity:
    channel_id: str
    title: str
    uploads_playlist_id: str


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    state: str


@dataclass(frozen=True)
class UploadedVideo:
    video_id: str
    title: str
    published_at: str
    duration_seconds: int
    video_type: str


class YouTubeClient:
    """Small facade around the YouTube Data and Analytics clients.

    The optional API arguments are dependency-injection seams for offline tests.
    """

    def __init__(
        self,
        *,
        token_path: Path,
        client_secret_path: Path | None = None,
        redirect_uri: str = "http://127.0.0.1:8000/youtube/oauth/callback",
        data_api=None,
        analytics_api=None,
        flow_factory=None,
        credentials_loader=None,
        api_builder=None,
    ):
        self.token_path = Path(token_path)
        self.client_secret_path = (
            Path(client_secret_path) if client_secret_path is not None else None
        )
        self.redirect_uri = redirect_uri
        self._data_api = data_api
        self._analytics_api = analytics_api
        self._flow_factory = flow_factory or self._default_flow_factory
        self._credentials_loader = credentials_loader or self._default_credentials_loader
        self._api_builder = api_builder or self._default_api_builder

    @property
    def oauth_state_path(self) -> Path:
        return self.token_path.with_name(f"{self.token_path.name}.oauth-state")

    def start_oauth(self) -> OAuthStart:
        flow = self._new_flow()
        authorization_url, state = flow.authorization_url(
            access_type="offline", prompt="consent"
        )
        self._write_private_json(
            self.oauth_state_path,
            {"state": state, "created_at": datetime.now(UTC).isoformat()},
        )
        return OAuthStart(authorization_url=authorization_url, state=state)

    def complete_oauth(self, *, code: str, state: str) -> None:
        expected = self._read_pending_state()
        if not secrets.compare_digest(state, expected):
            raise YouTubeOAuthStateError("OAuth callback state is invalid")
        flow = self._new_flow()
        flow.fetch_token(code=code)
        self._write_private_text(self.token_path, flow.credentials.to_json())
        self.oauth_state_path.unlink(missing_ok=True)

    def get_authenticated_channel(self) -> ChannelIdentity:
        data_api = self._get_data_api()
        payload = data_api.channels().list(
            part="snippet,contentDetails", mine=True
        ).execute()
        items = payload.get("items", [])
        if not items:
            raise YouTubeAuthorizationRequired("No authorized YouTube channel was returned")
        item = items[0]
        return ChannelIdentity(
            channel_id=item["id"],
            title=item["snippet"]["title"],
            uploads_playlist_id=item["contentDetails"]["relatedPlaylists"]["uploads"],
        )

    def list_uploaded_videos(self, uploads_playlist_id: str) -> list[UploadedVideo]:
        data_api = self._get_data_api()
        video_ids: list[str] = []
        page_token = None
        while True:
            arguments = {"part": "contentDetails", "playlistId": uploads_playlist_id, "maxResults": 50}
            if page_token:
                arguments["pageToken"] = page_token
            payload = data_api.playlistItems().list(**arguments).execute()
            video_ids.extend(item["contentDetails"]["videoId"] for item in payload.get("items", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        if not video_ids:
            return []
        by_id = {}
        for index in range(0, len(video_ids), 50):
            response = data_api.videos().list(
                part="snippet,contentDetails", id=",".join(video_ids[index:index + 50])
            ).execute()
            by_id.update({item["id"]: item for item in response.get("items", [])})
        return [self._to_uploaded_video(by_id[video_id]) for video_id in video_ids if video_id in by_id]

    def fetch_video_metrics(self, video_id: str, channel_id: str, start_date: str, end_date: str) -> dict:
        analytics_api = self._get_analytics_api()
        common = {"ids": f"channel=={channel_id}", "startDate": start_date, "endDate": end_date, "filters": f"video=={video_id}"}
        aggregate = self._query_rows(analytics_api, **common, dimensions="video", metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,impressions,impressionsCtr,averageViewPercentage")
        traffic_rows = self._query_rows(analytics_api, **common, dimensions="insightTrafficSourceType", metrics="views")
        returning_rows = self._query_rows(analytics_api, **common, dimensions="video", metrics="returningViewers")
        metrics = {"video_id": video_id, **(aggregate[0] if aggregate else {})}
        metrics["watch_minutes"] = metrics.pop("estimatedMinutesWatched", None)
        metrics["avg_view_duration_seconds"] = metrics.pop("averageViewDuration", None)
        metrics["subscribers_gained"] = metrics.pop("subscribersGained", None)
        metrics["ctr"] = metrics.pop("impressionsCtr", None)
        metrics["average_percentage_viewed"] = metrics.pop("averageViewPercentage", None)
        traffic_total = sum(row.get("views", 0) or 0 for row in traffic_rows)
        metrics["traffic"] = {row["insightTrafficSourceType"]: row["views"] / traffic_total for row in traffic_rows if traffic_total}
        metrics["returning_viewers"] = returning_rows[0].get("returningViewers") if returning_rows else None
        return metrics

    def _get_data_api(self):
        if self._data_api is not None:
            return self._data_api
        if not self.token_path.is_file():
            raise YouTubeAuthorizationRequired("YouTube authorization is required")
        self._data_api = self._api_builder("youtube", "v3", self._load_credentials())
        return self._data_api

    def _get_analytics_api(self):
        if self._analytics_api is not None:
            return self._analytics_api
        self._analytics_api = self._api_builder("youtubeAnalytics", "v2", self._load_credentials())
        return self._analytics_api

    @staticmethod
    def _query_rows(analytics_api, **kwargs) -> list[dict]:
        try:
            payload = analytics_api.reports().query(**kwargs).execute()
        except Exception:
            return []
        headers = [header["name"] for header in payload.get("columnHeaders", [])]
        return [dict(zip(headers, row, strict=True)) for row in payload.get("rows", [])]

    @staticmethod
    def _to_uploaded_video(item: dict) -> UploadedVideo:
        seconds = _parse_duration_seconds(item["contentDetails"]["duration"])
        return UploadedVideo(
            video_id=item["id"],
            title=item["snippet"]["title"],
            published_at=item["snippet"]["publishedAt"],
            duration_seconds=seconds,
            video_type="short" if seconds <= 60 else "long_form",
        )

    def _new_flow(self):
        if self.client_secret_path is None:
            raise YouTubeAuthorizationRequired("OAuth client credentials are required")
        return self._flow_factory(
            client_secret_path=self.client_secret_path,
            scopes=YOUTUBE_SCOPES,
            redirect_uri=self.redirect_uri,
        )

    @staticmethod
    def _default_flow_factory(*, client_secret_path: Path, scopes: list[str], redirect_uri: str):
        from google_auth_oauthlib.flow import Flow

        return Flow.from_client_secrets_file(
            str(client_secret_path), scopes=scopes, redirect_uri=redirect_uri
        )

    def _load_credentials(self):
        if not self.token_path.is_file():
            raise YouTubeAuthorizationRequired("YouTube authorization is required")
        return self._credentials_loader(self.token_path, YOUTUBE_SCOPES)

    @staticmethod
    def _default_credentials_loader(token_path: Path, scopes: list[str]):
        from google.oauth2.credentials import Credentials

        return Credentials.from_authorized_user_file(str(token_path), scopes=scopes)

    @staticmethod
    def _default_api_builder(service_name: str, version: str, credentials):
        from googleapiclient.discovery import build

        return build(service_name, version, credentials=credentials, cache_discovery=False)

    def _read_pending_state(self) -> str:
        try:
            payload = json.loads(self.oauth_state_path.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(payload["created_at"])
            if datetime.now(UTC) - created_at > timedelta(minutes=10):
                raise ValueError("expired")
            return str(payload["state"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise YouTubeOAuthStateError("OAuth callback state is invalid or expired") from error

    def _write_private_json(self, path: Path, payload: dict[str, str]) -> None:
        self._write_private_text(path, json.dumps(payload))

    @staticmethod
    def _write_private_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            temporary_path.write_text(content, encoding="utf-8")
            os.replace(temporary_path, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                # Windows ACLs are retained from the private directory.  Never fail a
                # successful authorization merely because POSIX permissions are absent.
                pass
        finally:
            temporary_path.unlink(missing_ok=True)


def _parse_duration_seconds(value: str) -> int:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds
