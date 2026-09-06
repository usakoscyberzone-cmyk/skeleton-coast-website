from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
from typing import Any


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".m4v"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt"}
SUPPORTED_EXTENSIONS = (
    VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS | SUBTITLE_EXTENSIONS
)


@dataclass(frozen=True)
class MediaProbeResult:
    path: Path
    kind: str
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: float | None = None
    codec: str | None = None
    probe_error: str | None = None


def media_kind(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in SUBTITLE_EXTENSIONS:
        return "subtitle"
    return None


def parse_ffprobe_payload(path: Path, payload: dict[str, Any]) -> MediaProbeResult:
    kind = media_kind(path) or "unknown"
    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []
    stream_type = {"audio": "audio", "subtitle": "subtitle"}.get(kind, "video")
    stream = next(
        (
            entry
            for entry in streams
            if isinstance(entry, dict) and entry.get("codec_type") == stream_type
        ),
        {},
    )
    format_data = payload.get("format")
    if not isinstance(format_data, dict):
        format_data = {}
    return MediaProbeResult(
        path=path,
        kind=kind,
        duration_seconds=_as_finite_float(format_data.get("duration")),
        width=_as_positive_int(stream.get("width")),
        height=_as_positive_int(stream.get("height")),
        frame_rate=_parse_frame_rate(stream.get("avg_frame_rate")),
        codec=_as_text(stream.get("codec_name")),
    )


def probe_media(
    path: Path, *, ffprobe_executable: str = "ffprobe", timeout_seconds: float = 30.0
) -> MediaProbeResult:
    kind = media_kind(path)
    if kind is None:
        return MediaProbeResult(path=path, kind="unknown", probe_error="unsupported_extension")
    try:
        with path.open("rb"):
            pass
    except OSError:
        return MediaProbeResult(path=path, kind=kind, probe_error="unreadable_file")

    command = [
        ffprobe_executable,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return MediaProbeResult(path=path, kind=kind, probe_error="ffprobe_not_found")
    except subprocess.TimeoutExpired:
        return MediaProbeResult(path=path, kind=kind, probe_error="ffprobe_timeout")
    except OSError:
        return MediaProbeResult(path=path, kind=kind, probe_error="ffprobe_execution_error")
    if completed.returncode != 0:
        return MediaProbeResult(path=path, kind=kind, probe_error="ffprobe_failed")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return MediaProbeResult(path=path, kind=kind, probe_error="invalid_ffprobe_json")
    if not isinstance(payload, dict):
        return MediaProbeResult(path=path, kind=kind, probe_error="invalid_ffprobe_json")
    return parse_ffprobe_payload(path, payload)


def _as_finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _as_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        parsed = int(value)
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
    return parsed if parsed > 0 else None


def _parse_frame_rate(value: Any) -> float | None:
    if not isinstance(value, str):
        return _as_finite_float(value)
    try:
        numerator, denominator = value.split("/", maxsplit=1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return None
        return _as_finite_float(float(numerator) / denominator_value)
    except (TypeError, ValueError):
        return _as_finite_float(value)


def _as_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
