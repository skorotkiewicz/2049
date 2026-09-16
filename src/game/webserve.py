"""Serve the web version locally: `uv run game-web [port]`.

Copies the game core next to the web assets (so the directory is also
deployable as a static site, e.g. GitHub Pages) and opens your browser.
Stdlib only.
"""

from __future__ import annotations

import functools
import http.server
import pathlib
import shutil
import threading
import webbrowser

PKG_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent.parent
WEB_DIR = REPO_ROOT / "web"
CORE_SRC = PKG_DIR / "core.py"


def _sync_core() -> pathlib.Path:
    WEB_DIR.mkdir(exist_ok=True)
    dst = WEB_DIR / "core.py"
    if not dst.exists() or dst.read_text() != CORE_SRC.read_text():
        shutil.copy(CORE_SRC, dst)
    return WEB_DIR


def main() -> None:
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    web_dir = _sync_core()
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(web_dir)
    )
    url = f"http://localhost:{port}"
    print(f"2049 -- Mines of Merge (web)")
    print(f"  serving {web_dir}")
    print(f"  -> {url}  (Ctrl-C to stop)")
    threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        http.server.HTTPServer(("", port), handler).serve_forever()
    except KeyboardInterrupt:
        print("\nbye!")
