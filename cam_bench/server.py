"""Local HTTP server: serves the UI and one background grab loop that feeds both
the live JPEG endpoint and any active recording - mirrors the proven pattern in
iwata-detect-panel-defect/test_scripts/view_camera_live.py, so frame delivery
doesn't depend on request timing and recording needs no second capture thread."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from . import imaging
from .session import Session

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
GRAB_INTERVAL_SEC = 1 / 15

_CONTENT_TYPES = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}


class _State:
    def __init__(self) -> None:
        self.jpeg: bytes = b""
        self.focus: float = 0.0
        self.histogram: list[float] = []
        self.resolution: tuple[int, int] = (0, 0)
        self.fps: float = 0.0
        self.error: str | None = None


def _grab_loop(session: Session, state: _State, stop: threading.Event) -> None:
    frame_count, window_start = 0, time.monotonic()
    while not stop.is_set():
        if session.backend is None:
            time.sleep(GRAB_INTERVAL_SEC)
            continue
        try:
            frame = session.backend.get_frame()
            state.error = None
        except Exception as e:  # noqa: BLE001 - surfaced to the UI, loop keeps running
            state.error = str(e)
            time.sleep(GRAB_INTERVAL_SEC)
            continue

        session.last_frame = frame
        if session.recorder is not None:
            session.recorder.write(frame)

        display = imaging.apply_zebra(frame) if session.zebra else frame
        ok, buf = cv2.imencode(".jpg", display)
        if ok:
            state.jpeg = buf.tobytes()
        state.focus = imaging.focus_score(frame)
        state.histogram = imaging.histogram(frame)
        h, w = frame.shape[:2]
        state.resolution = (w, h)

        frame_count += 1
        now = time.monotonic()
        if now - window_start >= 1.0:
            state.fps = frame_count / (now - window_start)
            frame_count, window_start = 0, now
        time.sleep(GRAB_INTERVAL_SEC)


def _make_handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def do_GET(self) -> None:
            if self.path == "/frame.jpg":
                self._send_bytes(state.jpeg, "image/jpeg")
            elif self.path == "/stats.json":
                body = json.dumps({
                    "focus": round(state.focus, 1),
                    "fps": round(state.fps, 1),
                    "resolution": state.resolution,
                    "histogram": state.histogram,
                    "error": state.error,
                }).encode()
                self._send_bytes(body, "application/json")
            else:
                self._serve_static()

        def _send_bytes(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_static(self) -> None:
            rel = self.path.lstrip("/") or "index.html"
            path = (WEB_DIR / rel).resolve()
            if path != WEB_DIR and WEB_DIR not in path.parents:
                self.send_error(404)
                return
            if not path.is_file():
                self.send_error(404)
                return
            content_type = _CONTENT_TYPES.get(path.suffix, "application/octet-stream")
            self._send_bytes(path.read_bytes(), content_type)

    return Handler


def start_server(session: Session, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    state = _State()
    stop = threading.Event()
    threading.Thread(target=_grab_loop, args=(session, state, stop), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), _make_handler(state))
    httpd._cam_bench_stop = stop  # type: ignore[attr-defined]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
