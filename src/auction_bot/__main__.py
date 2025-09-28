"""CLI entry point for the Avtor24 auction bot."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .config import load_config_directory
from .worker import run_workers


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Avtor24 auction bot")
    parser.add_argument(
        "--config-dir",
        type=Path,
        required=True,
        help="Directory containing per-account YAML configs",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _configure_logging(args.verbose)
    configs = load_config_directory(args.config_dir)
    asyncio.run(run_workers(configs))


if __name__ == "__main__":  # pragma: no cover
    main()
