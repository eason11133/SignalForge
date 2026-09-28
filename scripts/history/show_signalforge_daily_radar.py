from __future__ import annotations

import argparse
import asyncio

from processors.founder_daily_surface import (
    build_founder_daily_surface,
    print_founder_daily_surface,
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    snapshot = await build_founder_daily_surface(
        limit=max(3, min(args.limit, 25)),
        save_snapshot=True,
    )
    print_founder_daily_surface(snapshot)


if __name__ == "__main__":
    asyncio.run(main())
