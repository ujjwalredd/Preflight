from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from preflight.manifest import (
    build_manifest,
    manifest_to_bootstrap,
    manifest_to_json,
    manifest_to_markdown,
)
from preflight.schema import manifest_schema


def serve(
    root: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    use_cache: bool = True,
) -> ThreadingHTTPServer:
    root = root.resolve()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path or "/"
            if path == "/":
                body = (
                    b"<!doctype html><meta charset=utf-8><title>Preflight</title>"
                    b"<pre>GET /manifest.json\nGET /manifest.md\nGET /bootstrap.md\n"
                    b"GET /bootstrap.txt\nGET /schema.json</pre>"
                )
                self._send(HTTPStatus.OK, body, "text/html; charset=utf-8")
                return
            if path == "/manifest.json":
                m = build_manifest(root, use_cache=use_cache)
                raw = manifest_to_json(m).encode("utf-8")
                self._send(HTTPStatus.OK, raw, "application/json; charset=utf-8")
                return
            if path == "/manifest.md":
                m = build_manifest(root, use_cache=use_cache)
                raw = manifest_to_markdown(m).encode("utf-8")
                self._send(HTTPStatus.OK, raw, "text/markdown; charset=utf-8")
                return
            if path == "/bootstrap.md":
                m = build_manifest(root, use_cache=use_cache)
                raw = (manifest_to_bootstrap(m) + "\n").encode("utf-8")
                self._send(HTTPStatus.OK, raw, "text/markdown; charset=utf-8")
                return
            if path == "/bootstrap.txt":
                m = build_manifest(root, use_cache=use_cache)
                raw = manifest_to_bootstrap(m, plain=True).encode("utf-8")
                self._send(HTTPStatus.OK, raw, "text/plain; charset=utf-8")
                return
            if path == "/schema.json":
                raw = manifest_to_json(manifest_schema()).encode("utf-8")
                self._send(HTTPStatus.OK, raw, "application/json; charset=utf-8")
                return
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

    return ThreadingHTTPServer((host, port), Handler)
