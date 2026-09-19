from __future__ import annotations

import argparse
import asyncio

from init_db import init_db
from processors.opportunity_decision import print_founder_daily_v5


async def main() -> None:
    parser = argparse.ArgumentParser(description="Founder Daily Radar V6")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    await init_db()
    await print_founder_daily_v5(
        limit=max(1, min(int(args.limit), 25))
    )


if __name__ == "__main__":
    asyncio.run(main())
