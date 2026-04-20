from __future__ import annotations

import argparse
import sys
from pathlib import Path

from preflight import __version__
from preflight.manifest import (
    build_manifest,
    manifest_to_bootstrap,
    manifest_to_json,
    manifest_to_markdown,
)
from preflight.schema import manifest_schema
from preflight.server import serve
from preflight.verify import verify_manifest


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="preflight", description="AI-oriented project manifests.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Print manifest JSON to stdout.")
    p_scan.add_argument("path", nargs="?", default=".", type=Path, help="Project root")
    p_scan.add_argument(
        "--md",
        action="store_true",
        help="Print Markdown instead of JSON.",
    )
    p_scan.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the scan cache.",
    )

    p_serve = sub.add_parser("serve", help="Serve manifest over HTTP.")
    p_serve.add_argument("path", nargs="?", default=".", type=Path, help="Project root")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the scan cache.",
    )

    p_bootstrap = sub.add_parser("bootstrap", help="Print the agent bootstrap brief.")
    p_bootstrap.add_argument("path", nargs="?", default=".", type=Path, help="Project root")
    p_bootstrap.add_argument(
        "--text",
        action="store_true",
        help="Print plain text instead of Markdown.",
    )
    p_bootstrap.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the scan cache.",
    )

    sub.add_parser("schema", help="Print the manifest JSON schema.")

    p_verify = sub.add_parser("verify", help="Validate inferred commands.")
    p_verify.add_argument("path", nargs="?", default=".", type=Path, help="Project root")
    p_verify.add_argument(
        "--command",
        action="append",
        default=[],
        help="Specific command name to verify. May be repeated.",
    )
    p_verify.add_argument(
        "--run",
        action="store_true",
        help="Execute commands instead of returning a dry-run plan.",
    )
    p_verify.add_argument(
        "--allow-risky",
        action="store_true",
        help="Allow install or otherwise risky commands to run.",
    )
    p_verify.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-command timeout in seconds when using --run.",
    )
    p_verify.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the scan cache.",
    )

    args = parser.parse_args(argv)

    if args.cmd == "scan":
        m = build_manifest(args.path, use_cache=not args.no_cache)
        if args.md:
            sys.stdout.write(manifest_to_markdown(m))
        else:
            sys.stdout.write(manifest_to_json(m))
        return 0

    if args.cmd == "serve":
        root: Path = args.path
        httpd = serve(root, host=args.host, port=args.port, use_cache=not args.no_cache)
        url = f"http://{args.host}:{args.port}"
        print(f"Preflight serving {root.resolve()} at {url}", file=sys.stderr)
        print(f"  {url}/manifest.json", file=sys.stderr)
        print(f"  {url}/manifest.md", file=sys.stderr)
        print(f"  {url}/bootstrap.md", file=sys.stderr)
        print(f"  {url}/bootstrap.txt", file=sys.stderr)
        print(f"  {url}/schema.json", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.", file=sys.stderr)
            httpd.shutdown()
        return 0

    if args.cmd == "bootstrap":
        manifest = build_manifest(args.path, use_cache=not args.no_cache)
        sys.stdout.write(manifest_to_bootstrap(manifest, plain=args.text))
        if not args.text:
            sys.stdout.write("\n")
        return 0

    if args.cmd == "schema":
        sys.stdout.write(manifest_to_json(manifest_schema()))
        return 0

    if args.cmd == "verify":
        manifest = build_manifest(args.path, use_cache=not args.no_cache)
        result = verify_manifest(
            manifest,
            selected_commands=args.command or None,
            run=args.run,
            allow_risky=args.allow_risky,
            timeout_seconds=args.timeout,
        )
        sys.stdout.write(manifest_to_json(result))
        return 0 if result["success"] else 1

    return 2
