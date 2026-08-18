"""Entry point: starts the local server, opens a pywebview window over it with the
JS bridge attached - same launch shape as iwata-detect-panel-defect/deploy/launch_app.py."""
from __future__ import annotations

import argparse
import sys

import webview

from .api import JsApi
from .server import start_server
from .session import Session


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    args = ap.parse_args(argv)

    session = Session()
    start_server(session, host=args.host, port=args.port)

    api = JsApi(session)
    window = webview.create_window("Cam Bench", f"http://{args.host}:{args.port}",
                                    width=args.width, height=args.height, js_api=api)
    api.window = window

    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
