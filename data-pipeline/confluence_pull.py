"""Read-only Confluence Cloud exporter for authoritative Wiki source artifacts."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from confluence_export import (
    ConfluenceClient,
    ConfluenceError,
    ConfluenceExporter,
    load_confluence_config,
)


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "data-persistence" / "data" / "raws" / "confluence"
DEFAULT_ENV = HERE / ".confluence.env"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export authoritative Confluence XHTML, normalized Markdown, metadata and structure sidecars without indexing them.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--space-key", help="Export every current page visible in this space")
    target.add_argument("--page-id", help="Export one page and resolve its ancestor path")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT,
        help=f"Export root (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--env-file", type=Path, default=DEFAULT_ENV,
        help="Optional local credentials file; process environment variables take precedence",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    parser.add_argument("--max-attempts", type=int, default=5, help="Maximum attempts for retryable requests")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        config = load_confluence_config(args.env_file)
        client = ConfluenceClient(
            **config, timeout=args.timeout, max_attempts=args.max_attempts,
        )
        exporter = ConfluenceExporter(client=client, output_dir=args.output_dir)
        manifest = (
            exporter.export_space(args.space_key)
            if args.space_key
            else exporter.export_page(args.page_id)
        )
    except (ConfluenceError, ValueError, OSError) as exc:
        logging.getLogger("confluence_pull").error("Export failed: %s", exc)
        return 1

    summary = {
        key: manifest.get(key)
        for key in ("space_key", "status", "exported", "skipped", "failed")
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if manifest.get("status") == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
