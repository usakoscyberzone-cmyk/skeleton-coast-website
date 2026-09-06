"""Read-only, single-credential YouTube Data/Analytics access."""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import hashlib, json, re

YOUTUBE_SCOPES=["https://www.googleapis.com/auth/youtube.readonly","https://www.googleapis.com/auth/yt-analytics.readonly"]
AGGREGATE_METRICS="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained"
class YouTubeAuthorizationRequired(RuntimeError): pass
class YouTubeOAuthStateError(RuntimeError): pass
class YouTubeApiError(RuntimeError): pass
@dataclass(frozen=True)
class ChannelIdentity: channel_id:str; title:str; uploads_playlist_id:str
@dataclass(frozen=True)
class OAuthStart: authorization_url:str; state:str
@dataclass(frozen=True)
class UploadedVideo: video_id:str; title:str; published_at:datetime|None; duration_seconds:int|None; video_type:str="unknown"
@dataclass(frozen=True)
class RawVideoMetrics:
    video_id:str; views:int|None=None; watch_minutes:float|None=None; avg_view_duration_seconds:float|None=None; average_percentage_viewed:float|None=None; subscribers_gained:int|None=None; impressions:int|None=None; ctr:float|None=None; returning_viewers:int|None=None; traffic_raw:dict[str,int]=field(default_factory=dict)

class YouTubeClient:
 def __init__(self,*,token_path:Path,client_secret_path:Path|None=None,redirect_uri="http://127.0.0.1:8000/youtube/oauth/callback",data_api=None,analytics_api=None,flow_factory=None,credentials_loader=None,api_builder=None):
  if not Path(token_path).is_absolute(): raise ValueError("YOUTUBE_TOKEN_PATH must be an absolute user-private path")
  self.token_path=Path(token_path); self.client_secret_path=Path(client_secret_path) if client_secret_path else None; self.redirect_uri=redirect_uri; self._data_api=data_api; self._analytics_api=analytics_api; self._flow_factory=flow_factory or self._default_flow_factory; self._credentials_loader=credentials_loader or self._default_credentials_loader; self._api_builder=api_builder or self._default_api_builder; self._credentials=None; self._token_digest=None
 @property
 def oauth_state_path(self): return self.token_path.with_name(self.token_path.name+".oauth-state")
 def start_oauth(self):
  f=self._new_flow(); url,state=f.authorization_url(access_type="offline",prompt="consent"); self._write(self.oauth_state_path,json.dumps({"state":state,"created_at":datetime.now(UTC).isoformat()})); return OAuthStart(url,state)
 def complete_oauth(self,*,code,state):
  if state != self._consume_state(): raise YouTubeOAuthStateError("OAuth callback state is invalid")
  f=self._new_flow(); f.fetch_token(code=code); self._write(self.token_path,f.credentials.to_json())
 def reject_oauth(self,state):
  if not state or state != self._consume_state(): raise YouTubeOAuthStateError("OAuth callback state is invalid")
 def get_authenticated_channel(self):
  p=self._data().channels().list(part="snippet,contentDetails",mine=True).execute(); items=p.get("items",[])
  if not items: raise YouTubeAuthorizationRequired("No authorized YouTube channel was returned")
  i=items[0]; return ChannelIdentity(i["id"],i["snippet"]["title"],i["contentDetails"]["relatedPlaylists"]["uploads"])
 def list_uploaded_videos(self,playlist_id):
  api=self._data(); ids=[]; page=None
  while True:
   kw={"part":"contentDetails","playlistId":playlist_id,"maxResults":50};
   if page: kw["pageToken"]=page
   p=api.playlistItems().list(**kw).execute(); ids += [x["contentDetails"]["videoId"] for x in p.get("items",[])]; page=p.get("nextPageToken")
   if not page: break
  found={}
  for n in range(0,len(ids),50): found.update({x["id"]:x for x in api.videos().list(part="snippet,contentDetails",id=",".join(ids[n:n+50])).execute().get("items",[])})
  return [self._video(found[i]) for i in ids if i in found]
 def fetch_video_metrics(self,video_id,start_date,end_date):
  common={"ids":"channel==MINE","startDate":start_date,"endDate":end_date,"filters":f"video=={video_id}"}; api=self._analytics(); a=self._query(api,**common,metrics=AGGREGATE_METRICS); t=self._query(api,**common,dimensions="insightTrafficSourceType",metrics="views"); x=a[0] if a else {}; return RawVideoMetrics(video_id,x.get("views"),x.get("estimatedMinutesWatched"),x.get("averageViewDuration"),x.get("averageViewPercentage"),x.get("subscribersGained"),traffic_raw={r["insightTrafficSourceType"]:r["views"] for r in t})
 def ensure_token_unchanged(self):
  if self._token_digest and self._token_digest!=hashlib.sha256(self.token_path.read_bytes()).digest(): raise YouTubeAuthorizationRequired("Authorization changed during sync")
 def _query(self,api,**kw):
  try: p=api.reports().query(**kw).execute()
  except Exception as e:
   if "metric" in str(e).lower() and "not" in str(e).lower(): return []
   raise YouTubeApiError("YouTube Analytics request failed") from e
  h=[x["name"] for x in p.get("columnHeaders",[])]; return [dict(zip(h,r,strict=True)) for r in p.get("rows",[])]
 def _data(self):
  if self._data_api is None:self._data_api=self._api_builder("youtube","v3",self._load())
  return self._data_api
 def _analytics(self):
  if self._analytics_api is None:self._analytics_api=self._api_builder("youtubeAnalytics","v2",self._load())
  return self._analytics_api
 def _load(self):
  if self._credentials is None:
   if not self.token_path.is_file():raise YouTubeAuthorizationRequired("YouTube authorization is required")
   self._token_digest=hashlib.sha256(self.token_path.read_bytes()).digest(); self._credentials=self._credentials_loader(self.token_path,YOUTUBE_SCOPES)
  return self._credentials
 @staticmethod
 def _video(i): return UploadedVideo(i["id"],i["snippet"]["title"],_time(i["snippet"].get("publishedAt")),_duration(i["contentDetails"].get("duration")))
 def _new_flow(self):
  if not self.client_secret_path:raise YouTubeAuthorizationRequired("OAuth client credentials are required")
  return self._flow_factory(client_secret_path=self.client_secret_path,scopes=YOUTUBE_SCOPES,redirect_uri=self.redirect_uri)
 def _consume_state(self):
  try:
   c=self.oauth_state_path.with_suffix(".consumed"); self.oauth_state_path.replace(c); p=json.loads(c.read_text()); c.unlink(missing_ok=True)
   if (datetime.now(UTC)-datetime.fromisoformat(p["created_at"])).total_seconds()>600:raise ValueError
   return p["state"]
  except Exception as e:raise YouTubeOAuthStateError("OAuth callback state is invalid or expired") from e
 @staticmethod
 def _write(path,text): path.parent.mkdir(parents=True,exist_ok=True); t=path.with_name("."+path.name+".tmp"); t.write_text(text); t.replace(path)
 @staticmethod
 def _default_flow_factory(**kw):
  from google_auth_oauthlib.flow import Flow; return Flow.from_client_secrets_file(str(kw["client_secret_path"]),scopes=kw["scopes"],redirect_uri=kw["redirect_uri"])
 @staticmethod
 def _default_credentials_loader(path,scopes):
  from google.oauth2.credentials import Credentials; return Credentials.from_authorized_user_file(str(path),scopes=scopes)
 @staticmethod
 def _default_api_builder(name,version,credentials):
  from googleapiclient.discovery import build; return build(name,version,credentials=credentials,cache_discovery=False)
def _duration(v):
 m=re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",v or ""); return None if not m else int(m.group(1)or 0)*3600+int(m.group(2)or 0)*60+int(m.group(3)or 0)
def _time(v):
 try:return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(UTC)
 except (AttributeError,ValueError):return None
