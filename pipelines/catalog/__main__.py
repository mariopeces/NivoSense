"""Command line for the catalogue steps of the workflows: `rebuild-index --target staging|prod` and
`promote --start YYYY-MM-DD --end YYYY-MM-DD [--layer ID ...]`."""

from __future__ import annotations

import argparse
import json

from .index import promote, rebuild_index
from .storage import storage_from_env


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m pipelines.catalog")
    commands = parser.add_subparsers(dest="command", required=True)
    rebuild = commands.add_parser("rebuild-index", help="rebuild catalog/index.json from the entries")
    rebuild.add_argument("--target", choices=["staging", "prod"], required=True)
    promote_ = commands.add_parser("promote", help="copy a date range from staging to prod")
    promote_.add_argument("--start", required=True)
    promote_.add_argument("--end", required=True)
    promote_.add_argument("--layer", action="append", dest="layers")
    args = parser.parse_args(argv)

    if args.command == "rebuild-index":
        index = rebuild_index(storage_from_env(args.target))
        summary = {layer: len(item["dates"]) for layer, item in index["layers"].items()}
    else:
        entries = promote(storage_from_env("staging"), storage_from_env("prod"), args.start, args.end, args.layers)
        summary = {"promoted": len(entries)}
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
