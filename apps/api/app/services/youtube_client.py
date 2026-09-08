"""Read-only, single-credential YouTube Data/Analytics access."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import ctypes, hashlib, json, os, re, secrets, subprocess
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/yt-analytics.readonly"]
AGGREGATE_METRICS = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained"
class YouTubeAuthorizationRequired(RuntimeError): pass
class YouTubeOAuthStateError(RuntimeError): pass
class YouTubeOAuthCallbackError(RuntimeError): pass
class YouTubeConfigurationError(RuntimeError): pass
class YouTubeApiError(RuntimeError): pass
class YouTubeQuotaError(YouTubeApiError): pass
class YouTubeTransientError(YouTubeApiError): pass
class YouTubeTokenChanged(RuntimeError): pass

@dataclass(frozen=True)
class ChannelIdentity: channel_id: str; title: str; uploads_playlist_id: str
@dataclass(frozen=True)
class OAuthStart: authorization_url: str; state: str
@dataclass(frozen=True)
class UploadedVideo: video_id: str; title: str; published_at: datetime | None; duration_seconds: int | None; video_type: str = "unknown"
@dataclass(frozen=True)
class RawVideoMetrics:
    video_id: str
    views: int | None = None
    watch_minutes: float | None = None
    avg_view_duration_seconds: float | None = None
    average_percentage_viewed: float | None = None
    subscribers_gained: int | None = None
    impressions: int | None = None
    ctr: float | None = None
    returning_viewers: int | None = None
    traffic_raw: dict[str, int] = field(default_factory=dict)


class _ExclusiveTokenLock:
    """An OS-held lock whose identity does not depend on the sidecar path."""

    def __init__(self, token_path: Path):
        self._token_path = token_path
        self._handle = None
        self._descriptor = None

    def acquire(self) -> None:
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            name = "Local\\SkeletonCoastYouTubeToken-" + hashlib.sha256(
                os.path.normcase(str(self._token_path)).encode("utf-8")
            ).hexdigest()
            handle = kernel32.CreateMutexW(None, True, name)
            if not handle:
                raise OSError(ctypes.get_last_error(), "Could not create token mutex")
            if ctypes.get_last_error() == 183:
                kernel32.CloseHandle(handle)
                raise YouTubeTokenChanged("Authorization is already in use")
            self._handle = (kernel32, handle)
            return

        import fcntl

        lock_path = self._token_path.with_name(self._token_path.name + ".lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise YouTubeTokenChanged("Authorization is already in use") from error
        self._descriptor = descriptor

    def release(self) -> None:
        if self._handle is not None:
            kernel32, handle = self._handle
            self._handle = None
            kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)
        if self._descriptor is not None:
            import fcntl

            descriptor, self._descriptor = self._descriptor, None
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

class YouTubeClient:
    def __init__(self, *, token_path: Path, client_secret_path: Path | None = None, redirect_uri="http://127.0.0.1:8000/youtube/oauth/callback", data_api=None, analytics_api=None, flow_factory=None, credentials_loader=None, api_builder=None):
        token_path = Path(token_path)
        if not token_path.is_absolute():
            raise ValueError("YOUTUBE_TOKEN_PATH must be absolute and outside the repository")
        token_path = token_path.resolve()
        repo_root = Path(__file__).resolve().parents[4]
        if token_path == repo_root or repo_root in token_path.parents:
            raise ValueError("YOUTUBE_TOKEN_PATH must be absolute and outside the repository")
        self.token_path, self.client_secret_path, self.redirect_uri = token_path, Path(client_secret_path) if client_secret_path else None, redirect_uri
        self._data_api, self._analytics_api = data_api, analytics_api
        self._flow_factory, self._credentials_loader, self._api_builder = flow_factory or self._default_flow_factory, credentials_loader or self._default_credentials_loader, api_builder or self._default_api_builder
        self._credentials = None
        self._token_digest = None

    @property
    def oauth_state_path(self): return self.token_path.with_name(self.token_path.name + ".oauth-state")
    def start_oauth(self):
        flow = self._new_flow(); url, state = flow.authorization_url(access_type="offline", prompt="consent")
        self._write(self.oauth_state_path, json.dumps({"state": state, "created_at": datetime.now(UTC).isoformat()}))
        return OAuthStart(url, state)
    def complete_oauth(self, *, code, state):
        if state != self._consume_state(): raise YouTubeOAuthStateError("OAuth callback state is invalid")
        flow = self._new_flow()
        try: flow.fetch_token(code=code)
        except Exception as error: raise YouTubeOAuthCallbackError("OAuth callback was rejected") from error
        with self.token_guard():
            self._write(self.token_path, flow.credentials.to_json())
    def reject_oauth(self, state):
        if not state or state != self._consume_state(): raise YouTubeOAuthStateError("OAuth callback state is invalid")
    def get_authenticated_channel(self):
        payload = self._execute(self._data().channels().list(part="snippet,contentDetails", mine=True)); items = payload.get("items", [])
        if not items: raise YouTubeAuthorizationRequired("No authorized YouTube channel was returned")
        item = items[0]; return ChannelIdentity(item["id"], item["snippet"]["title"], item["contentDetails"]["relatedPlaylists"]["uploads"])
    def list_uploaded_videos(self, playlist_id):
        api, ids, page = self._data(), [], None
        while True:
            kwargs = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
            if page: kwargs["pageToken"] = page
            payload = self._execute(api.playlistItems().list(**kwargs)); ids += [item["contentDetails"]["videoId"] for item in payload.get("items", [])]; page = payload.get("nextPageToken")
            if not page: break
        found = {}
        for offset in range(0, len(ids), 50):
            payload = self._execute(api.videos().list(part="snippet,contentDetails", id=",".join(ids[offset:offset + 50]))); found.update({item["id"]: item for item in payload.get("items", [])})
        return [self._video(found[item_id]) for item_id in ids if item_id in found]
    def fetch_video_metrics(self, video_id: str, start_date: str, end_date: str) -> RawVideoMetrics:
        common = {"ids":"channel==MINE", "startDate":start_date, "endDate":end_date, "filters":f"video=={video_id}"}; api = self._analytics()
        aggregate = self._query(api, **common, metrics=AGGREGATE_METRICS); traffic = self._query(api, **common, dimensions="insightTrafficSourceType", metrics="views"); values = aggregate[0] if aggregate else {}
        return RawVideoMetrics(video_id, values.get("views"), values.get("estimatedMinutesWatched"), values.get("averageViewDuration"), values.get("averageViewPercentage"), values.get("subscribersGained"), traffic_raw={row["insightTrafficSourceType"]: row["views"] for row in traffic})

    def fetch_video_views(self, video_id: str, start_date: str, end_date: str) -> int | None:
        rows = self._query(
            self._analytics(), ids="channel==MINE", startDate=start_date, endDate=end_date,
            filters=f"video=={video_id}", metrics="views",
        )
        return int(rows[0]["views"]) if rows and rows[0].get("views") is not None else None

    @contextmanager
    def token_guard(self):
        lock = self.token_path.with_name(self.token_path.name + ".lock")
        self._secure_parent(lock.parent)
        mutex = _ExclusiveTokenLock(self.token_path)
        mutex.acquire()
        try:
            if lock.exists():
                self._verify_owner_only_acl(lock)
            else:
                self._write(lock, "")
            yield
        finally:
            mutex.release()
    def ensure_token_unchanged(self):
        if self._token_digest is None: return
        try: current = hashlib.sha256(self.token_path.read_bytes()).digest()
        except OSError as error: raise YouTubeTokenChanged("Authorization changed during sync") from error
        if current != self._token_digest: raise YouTubeTokenChanged("Authorization changed during sync")
    def _query(self, api, **kwargs):
        payload = self._execute(api.reports().query(**kwargs)); headers = [item["name"] for item in payload.get("columnHeaders", [])]
        return [dict(zip(headers, row, strict=True)) for row in payload.get("rows", [])]
    @staticmethod
    def _execute(request):
        try: return request.execute()
        except HttpError as error:
            status, reasons = getattr(error.resp, "status", 0), _google_error_reasons(error)
            if status == 401 or reasons & {"authError", "invalidCredentials", "unauthorized", "insufficientPermissions"}: raise YouTubeAuthorizationRequired("YouTube authorization is invalid") from error
            if status == 429 or reasons & {"quotaExceeded", "dailyLimitExceeded", "userRateLimitExceeded", "rateLimitExceeded"}: raise YouTubeQuotaError("YouTube quota exceeded") from error
            if status >= 500 or reasons & {"backendError", "internalError"}: raise YouTubeTransientError("YouTube upstream unavailable") from error
            if status == 403: raise YouTubeAuthorizationRequired("YouTube authorization is invalid") from error
            raise YouTubeApiError("YouTube request failed") from error
        except RefreshError as error: raise YouTubeAuthorizationRequired("YouTube authorization is invalid") from error
        except (TimeoutError, ConnectionError) as error: raise YouTubeTransientError("YouTube upstream unavailable") from error
    def _data(self):
        if self._data_api is None: self._data_api = self._api_builder("youtube", "v3", self._load())
        return self._data_api
    def _analytics(self):
        if self._analytics_api is None: self._analytics_api = self._api_builder("youtubeAnalytics", "v2", self._load())
        return self._analytics_api
    def _load(self):
        if self._credentials is not None: return self._credentials
        try: token_bytes = self.token_path.read_bytes()
        except OSError as error: raise YouTubeAuthorizationRequired("YouTube authorization is required") from error
        self._verify_owner_only_acl(self.token_path); original_digest = hashlib.sha256(token_bytes).digest()
        try:
            credentials = self._credentials_loader(self.token_path, YOUTUBE_SCOPES)
            if getattr(credentials, "expired", False):
                if not getattr(credentials, "refresh_token", None): raise YouTubeAuthorizationRequired("YouTube authorization must be renewed")
                credentials.refresh(self._refresh_request()); self._write(self.token_path, credentials.to_json(), expected_digest=original_digest); original_digest = hashlib.sha256(self.token_path.read_bytes()).digest()
        except YouTubeTokenChanged: raise
        except RefreshError as error: raise YouTubeAuthorizationRequired("YouTube authorization is invalid") from error
        self._credentials, self._token_digest = credentials, original_digest
        return credentials
    def _new_flow(self):
        if not self.client_secret_path: raise YouTubeAuthorizationRequired("OAuth client credentials are required")
        return self._flow_factory(client_secret_path=self.client_secret_path, scopes=YOUTUBE_SCOPES, redirect_uri=self.redirect_uri)
    def _consume_state(self):
        consumed = self.oauth_state_path.with_name(self.oauth_state_path.name + ".consumed." + secrets.token_hex(12))
        try:
            self.oauth_state_path.replace(consumed); self._verify_owner_only_acl(consumed); payload = json.loads(consumed.read_text(encoding="utf-8")); created = datetime.fromisoformat(payload["created_at"])
            if created.tzinfo is None or (datetime.now(UTC) - created.astimezone(UTC)).total_seconds() > 600: raise ValueError("expired")
            return str(payload["state"])
        except Exception as error: raise YouTubeOAuthStateError("OAuth callback state is invalid or expired") from error
        finally: consumed.unlink(missing_ok=True)
    @staticmethod
    def _write(path, text, *, expected_digest=None):
        path = Path(path); YouTubeClient._secure_parent(path.parent)
        if path.exists(): YouTubeClient._verify_owner_only_acl(path)
        temporary = path.with_name("." + path.name + "." + secrets.token_hex(12) + ".tmp")
        try:
            with open(temporary, "x", encoding="utf-8") as handle: handle.write(text); handle.flush(); os.fsync(handle.fileno())
            YouTubeClient._secure_acl(temporary)
            if expected_digest is not None:
                try: current = hashlib.sha256(path.read_bytes()).digest()
                except OSError as error: raise YouTubeTokenChanged("Authorization changed during refresh") from error
                if current != expected_digest: raise YouTubeTokenChanged("Authorization changed during refresh")
            os.replace(temporary, path); YouTubeClient._verify_owner_only_acl(path)
        finally: temporary.unlink(missing_ok=True)
    @staticmethod
    def _secure_parent(path):
        path = Path(path); created = not path.exists(); path.mkdir(parents=True, exist_ok=True)
        if created: YouTubeClient._secure_acl(path, directory=True)
        else:
            try: YouTubeClient._verify_owner_only_acl(path, directory=True)
            except PermissionError: YouTubeClient._secure_acl(path, directory=True)
    @staticmethod
    def _secure_acl(path, directory=False):
        if os.name != "nt": os.chmod(path, 0o700 if directory else 0o600); YouTubeClient._verify_owner_only_acl(path, directory); return
        script = "$ErrorActionPreference='Stop';$p=$env:SCGD_SECURE_PATH;$d=$env:SCGD_SECURE_DIR -eq '1';$id=[Security.Principal.WindowsIdentity]::GetCurrent();$a=if($d){New-Object Security.AccessControl.DirectorySecurity}else{New-Object Security.AccessControl.FileSecurity};$a.SetOwner($id.User);$a.SetAccessRuleProtection($true,$false);$i=if($d){[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None};$r=New-Object Security.AccessControl.FileSystemAccessRule($id.User,[Security.AccessControl.FileSystemRights]::FullControl,$i,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow);[void]$a.AddAccessRule($r);Set-Acl -LiteralPath $p -AclObject $a"
        env = os.environ.copy(); env.update(SCGD_SECURE_PATH=str(path), SCGD_SECURE_DIR="1" if directory else "0")
        result = subprocess.run(["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env, capture_output=True, text=True)
        if result.returncode: raise PermissionError("Could not apply owner-only credential ACL")
        YouTubeClient._verify_owner_only_acl(path, directory)
    @staticmethod
    def _verify_owner_only_acl(path, directory=False):
        if os.name != "nt":
            if Path(path).stat().st_mode & 0o077: raise PermissionError("Credential path is not owner-only")
            return
        script = "$ErrorActionPreference='Stop';$a=Get-Acl -LiteralPath $env:SCGD_SECURE_PATH;$s=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;$r=@($a.Access);if($r.Count -ne 1 -or $r[0].IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -ne $s -or $r[0].AccessControlType -ne 'Allow' -or $r[0].IsInherited -or (($r[0].FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -ne [Security.AccessControl.FileSystemRights]::FullControl)){exit 7}"
        env = os.environ.copy(); env["SCGD_SECURE_PATH"] = str(path)
        if subprocess.run(["pwsh.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env, capture_output=True).returncode: raise PermissionError("Credential path ACL is not owner-only")
    @staticmethod
    def _refresh_request():
        from google.auth.transport.requests import Request
        return Request()
    @staticmethod
    def _video(item): return UploadedVideo(item["id"], item["snippet"]["title"], _time(item["snippet"].get("publishedAt")), _duration(item["contentDetails"].get("duration")))
    @staticmethod
    def _default_flow_factory(**kwargs):
        from google_auth_oauthlib.flow import Flow
        return Flow.from_client_secrets_file(str(kwargs["client_secret_path"]), scopes=kwargs["scopes"], redirect_uri=kwargs["redirect_uri"])
    @staticmethod
    def _default_credentials_loader(path, scopes):
        from google.oauth2.credentials import Credentials
        return Credentials.from_authorized_user_file(str(path), scopes=scopes)
    @staticmethod
    def _default_api_builder(name, version, credentials):
        from googleapiclient.discovery import build
        return build(name, version, credentials=credentials, cache_discovery=False)

def _google_error_reasons(error):
    try:
        payload = json.loads(error.content.decode() if isinstance(error.content, bytes) else error.content)
        return {item.get("reason", "") for item in payload.get("error", {}).get("errors", [])}
    except (ValueError, TypeError, AttributeError): return set()
def _duration(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    return None if not match else int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60 + int(match.group(3) or 0)
def _time(value):
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (AttributeError, ValueError): return None
