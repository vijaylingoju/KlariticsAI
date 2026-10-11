"""Build the event store: `python -m app.seed [--path data/klaritics.duckdb] [--seed 42]`."""

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.seed.generator import seed
from app.seed.scenarios import SEED, USERS


def main(argv: list[str] | None = None) -> int:
    """Seed the store and print one summary line."""
    parser = argparse.ArgumentParser(prog="klaritics-seed")
    parser.add_argument("--path", type=Path, default=get_settings().store_path)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--users", type=int, default=USERS)
    args = parser.parse_args(argv)
    result = seed(args.path, args.seed, args.users)
    sys.stdout.write(
        f"seed: {result.users} users, {result.events} events written to {result.path}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
