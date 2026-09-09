from pathlib import Path
import subprocess

import pytest

from app.services import media_probe
from app.services.media_probe import media_kind, parse_ffprobe_payload, probe_media


def test_parse_ffprobe_payload_extracts_primary_video_stream():
    """Breaks if primary video metadata is not selected from ffprobe output."""
    payload = {
        "format": {"duration": "28.950000"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "60000/1001",
            }
        ],
    }

    result = parse_ffprobe_payload(Path("reel.mp4"), payload)

    assert result.duration_seconds == 28.95
    assert result.width == 1080
    assert result.height == 1920
    assert round(result.frame_rate, 2) == 59.94
    assert result.codec == "h264"


def test_parse_ffprobe_payload_skips_audio_before_primary_video_stream():
    """Breaks if a cover/audio stream is chosen instead of the first video stream."""
    payload = {
        "format": {"duration": "10"},
        "streams": [
            {"codec_type": "audio", "codec_name": "aac"},
            {
                "codec_type": "video",
                "codec_name": "h265",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24/1",
            },
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 360,
                "avg_frame_rate": "30/1",
            },
        ],
    }

    result = parse_ffprobe_payload(Path("clip.mov"), payload)

    assert (result.codec, result.width, result.height, result.frame_rate) == (
        "h265",
        1920,
        1080,
        24.0,
    )


@pytest.mark.parametrize(
    ("filename", "stream", "kind", "expected_codec"),
    [
        ("sound.MP3", {"codec_type": "audio", "codec_name": "mp3"}, "audio", "mp3"),
        ("still.JpEg", {"codec_type": "video", "codec_name": "mjpeg"}, "image", "mjpeg"),
        ("captions.VTT", {"codec_type": "subtitle", "codec_name": "webvtt"}, "subtitle", "webvtt"),
    ],
)
def test_parse_ffprobe_payload_supports_non_video_media(
    filename: str, stream: dict, kind: str, expected_codec: str
):
    """Breaks if a supported audio, image, or subtitle file is labeled as video."""
    result = parse_ffprobe_payload(
        Path(filename), {"format": {"duration": "5"}, "streams": [stream]}
    )

    assert result.kind == kind
    assert result.codec == expected_codec


def test_parse_ffprobe_payload_normalizes_absent_or_invalid_numeric_values():
    """Breaks if ffprobe placeholders or invalid rates reach persisted metadata."""
    result = parse_ffprobe_payload(
        Path("bad-rate.mp4"),
        {
            "format": {"duration": "N/A"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": "not-a-number",
                    "height": 0,
                    "avg_frame_rate": "0/0",
                }
            ],
        },
    )

    assert result.duration_seconds is None
    assert result.width is None
    assert result.height is None
    assert result.frame_rate is None


def test_parse_ffprobe_payload_accepts_absent_duration_and_frame_rate():
    """Breaks if stream formats without optional ffprobe fields crash a project scan."""
    result = parse_ffprobe_payload(
        Path("no-timing.mp4"),
        {"format": {}, "streams": [{"codec_type": "video", "codec_name": "h264"}]},
    )

    assert result.duration_seconds is None
    assert result.frame_rate is None


def test_parse_ffprobe_payload_rejects_fractional_dimensions():
    """Breaks if malformed dimensions are silently truncated before persistence."""
    result = parse_ffprobe_payload(
        Path("fractional.mp4"),
        {
            "format": {"duration": "1"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920.9,
                    "height": "1080.5",
                    "avg_frame_rate": "24/1",
                }
            ],
        },
    )

    assert result.width is None
    assert result.height is None


@pytest.mark.parametrize(
    ("filename", "expected_kind"),
    [
        ("MOVIE.MP4", "video"),
        ("song.M4A", "audio"),
        ("photo.WeBp", "image"),
        ("subtitles.SRT", "subtitle"),
        ("notes.txt", None),
    ],
)
def test_media_kind_handles_supported_extensions_case_insensitively(
    filename: str, expected_kind: str | None
):
    """Breaks if Windows-style extension casing causes supported media to be skipped."""
    assert media_kind(Path(filename)) == expected_kind


def test_probe_media_passes_a_path_with_spaces_as_one_subprocess_argument(
    tmp_path: Path, monkeypatch
):
    """Breaks if probing a valid Windows path is shell-split or interpreted as code."""
    source = tmp_path / "clips with spaces" / "reel one.mp4"
    source.parent.mkdir()
    source.write_bytes(b"placeholder")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '{"format": {}, "streams": []}', "")

    monkeypatch.setattr(media_probe.subprocess, "run", fake_run)

    result = probe_media(source)

    assert result.probe_error is None
    assert commands == [
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(source),
        ]
    ]


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        ("invalid_json", "invalid_ffprobe_json"),
        ("nonzero_exit", "ffprobe_failed"),
        ("timeout", "ffprobe_timeout"),
        ("missing_executable", "ffprobe_not_found"),
    ],
)
def test_probe_media_returns_structured_errors_from_ffprobe(
    tmp_path: Path, monkeypatch, failure: str, expected_error: str
):
    """Breaks if one ffprobe failure raises instead of producing a scan result."""
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"placeholder")

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if failure == "missing_executable":
            raise FileNotFoundError()
        if failure == "nonzero_exit":
            return subprocess.CompletedProcess(command, 1, "", "invalid file")
        return subprocess.CompletedProcess(command, 0, "not json", "")

    monkeypatch.setattr(media_probe.subprocess, "run", fake_run)

    result = probe_media(source)

    assert result.probe_error == expected_error


def test_probe_media_returns_structured_error_for_unreadable_file(tmp_path: Path):
    """Breaks if a missing or unreadable local file aborts the project scan."""
    result = probe_media(tmp_path / "missing.mp4")

    assert result.kind == "video"
    assert result.probe_error == "unreadable_file"


def test_probe_media_returns_structured_error_for_permission_denied_file(
    tmp_path: Path, monkeypatch
):
    """Breaks if an existing but unreadable file raises before ffprobe can be called."""
    source = tmp_path / "locked.mp4"
    source.write_bytes(b"locked")

    def deny_read(_: Path, *args: object, **kwargs: object):
        raise PermissionError()

    monkeypatch.setattr(Path, "open", deny_read)

    result = probe_media(source)

    assert result.probe_error == "unreadable_file"
