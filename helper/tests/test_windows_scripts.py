from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from threading import Thread


REPO_ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


class _SmokeHandler(BaseHTTPRequestHandler):
    scan_count = 0

    def log_message(self, _format, *_args):
        return

    def _send(self, status: int, payload: dict | list | str, content_type: str):
        body = payload if isinstance(payload, str) else json.dumps(payload)
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"}, "application/json")
        elif self.path == "/youtube/status":
            self._send(
                200,
                {
                    "status": "configuration_required",
                    "detail": "EXPECTED_YOUTUBE_CHANNEL_ID must be configured.",
                },
                "application/json",
            )
        else:
            self._send(200, "<!doctype html><title>Dashboard</title>", "text/html")

    def do_POST(self):
        if self.path == "/projects/scan":
            type(self).scan_count += 1
            self._send(200, [], "application/json")
        else:
            self._send(404, {"detail": "not found"}, "application/json")


def _run_script(path: Path, *arguments: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path),
            *arguments,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_smoke_test_uses_disposable_master_and_exercises_real_helper_sync(tmp_path):
    master = tmp_path / "YouTube Projects"
    master.mkdir()
    fake_ffprobe = tmp_path / "ffprobe.cmd"
    fake_ffprobe.write_text("@echo off\r\necho ffprobe version 7.1\r\n", encoding="utf-8")
    _SmokeHandler.scan_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SmokeHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        result = _run_script(
            REPO_ROOT / "scripts" / "smoke-test.ps1",
            "-TestMode",
            "-MasterProjectFolder",
            str(master),
            "-ApiBaseUrl",
            base_url,
            "-WebUrl",
            base_url + "/web",
            "-PythonPath",
            sys.executable,
            "-NodeCommand",
            "node",
            "-FfprobeCommand",
            str(fake_ffprobe),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _SmokeHandler.scan_count == 1
    assert "Python 3.12+: PASS" in result.stdout
    assert "Node 20+: PASS" in result.stdout
    assert "ffprobe: PASS" in result.stdout
    assert "API /health: PASS" in result.stdout
    assert "Web app: PASS" in result.stdout
    assert "Helper manual sync: PASS" in result.stdout
    assert "YouTube status: PASS (configuration_required)" in result.stdout
    assert "SMOKE TEST: PASS" in result.stdout


def test_smoke_test_missing_master_fails_with_creation_instruction(tmp_path):
    missing = tmp_path / "missing"
    result = _run_script(
        REPO_ROOT / "scripts" / "smoke-test.ps1",
        "-TestMode",
        "-MasterProjectFolder",
        str(missing),
        "-PythonPath",
        sys.executable,
        "-NodeCommand",
        "node",
        "-FfprobeCommand",
        "node",
    )

    assert result.returncode != 0
    assert "New-Item -ItemType Directory -Path" in result.stdout
    assert str(missing) in result.stdout


def test_api_and_web_start_scripts_offer_non_launching_dependency_checks():
    api = _run_script(
        REPO_ROOT / "scripts" / "start-api.ps1",
        "-CheckOnly",
        "-PythonPath",
        sys.executable,
    )
    web = _run_script(
        REPO_ROOT / "scripts" / "start-web.ps1",
        "-CheckOnly",
        "-NodeCommand",
        "node",
    )

    assert api.returncode == 0, api.stdout + api.stderr
    assert "API start check: PASS (127.0.0.1:8000)" in api.stdout
    assert web.returncode == 0, web.stdout + web.stderr
    assert "Web start check: PASS (127.0.0.1:5173)" in web.stdout


def test_lock_repair_requires_confirmation_and_changes_only_exact_sidecar(tmp_path):
    token = tmp_path / "youtube-token.json"
    database = tmp_path / "skeleton_growth.db"
    lock = tmp_path / "youtube-token.json.lock"
    token.write_bytes(b"secret-token")
    database.write_bytes(b"database")
    lock.write_text("externally-replaced", encoding="utf-8")
    script = REPO_ROOT / "scripts" / "repair-youtube-lock.ps1"

    refused = _run_script(script, "-TestMode", "-TokenPath", str(token))
    assert refused.returncode != 0
    assert lock.read_text(encoding="utf-8") == "externally-replaced"

    repaired = _run_script(
        script,
        "-TestMode",
        "-ConfirmServiceStopped",
        "-TokenPath",
        str(token),
    )

    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert "YouTube lock sidecar repair: PASS" in repaired.stdout
    assert token.read_bytes() == b"secret-token"
    assert database.read_bytes() == b"database"
    assert lock.read_text(encoding="utf-8") == ""
