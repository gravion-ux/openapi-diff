"""Command-line interface for openapi-diff.

Exit codes (CI-friendly):
    0  no breaking changes (or breaking changes found with --no-fail)
    1  breaking changes found (default --fail-on-breaking behaviour)
    2  usage or parse error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .differ import compare_specs
from .report import render_json, render_text


def _load_spec(path: str) -> dict[str, Any]:
    """Load and minimally validate an OpenAPI JSON document."""
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level JSON value must be an object")
    if not isinstance(data.get("paths"), dict):
        raise ValueError(f"{path}: missing or invalid 'paths' object")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openapi-diff",
        description="Compare two OpenAPI 3.x JSON specs and report breaking changes.",
    )
    parser.add_argument("old", help="path to the old (baseline) OpenAPI JSON spec")
    parser.add_argument("new", help="path to the new OpenAPI JSON spec")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="report format (default: text)",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="write the report to PATH instead of stdout",
    )
    parser.add_argument(
        "--fail-on-breaking",
        dest="fail_on_breaking",
        action="store_true",
        default=True,
        help="exit 1 when breaking changes are found (default)",
    )
    parser.add_argument(
        "--no-fail",
        dest="fail_on_breaking",
        action="store_false",
        help="exit 0 even when breaking changes are found",
    )
    parser.add_argument("--version", action="version", version=f"openapi-diff {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        old_spec = _load_spec(args.old)
        new_spec = _load_spec(args.new)
    except (OSError, ValueError) as exc:
        print(f"openapi-diff: error: {exc}", file=sys.stderr)
        return 2

    result = compare_specs(old_spec, new_spec)
    report = render_json(result) if args.format == "json" else render_text(result)

    if args.output:
        try:
            Path(args.output).write_text(report, encoding="utf-8")
        except OSError as exc:
            print(f"openapi-diff: error: {exc}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(report)

    if result.has_breaking and args.fail_on_breaking:
        return 1
    return 0
