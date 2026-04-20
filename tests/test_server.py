from __future__ import annotations

import threading
import urllib.request
from pathlib import Path

from preflight.server import serve


def test_manifest_json_endpoint(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Hi\n", encoding="utf-8")
    httpd = serve(tmp_path, host="127.0.0.1", port=0, use_cache=False)
    port = httpd.server_address[1]

    def run() -> None:
        httpd.serve_forever()

    threading.Thread(target=run, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/manifest.json", timeout=2) as resp:  # noqa: S310
            body = resp.read().decode("utf-8")
        assert '"preflight_version": 3' in body

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/manifest.md", timeout=2) as resp:  # noqa: S310
            markdown = resp.read().decode("utf-8")
        assert "# Preflight manifest" in markdown

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/bootstrap.txt", timeout=2) as resp:  # noqa: S310
            bootstrap_text = resp.read().decode("utf-8")
        assert "Preflight bootstrap" in bootstrap_text

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/schema.json", timeout=2) as resp:  # noqa: S310
            schema = resp.read().decode("utf-8")
        assert '"preflight_version"' in schema
    finally:
        httpd.shutdown()
