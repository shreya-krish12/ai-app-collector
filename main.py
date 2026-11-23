"""
Command-line entry point.

    python main.py                      # mock mode, all clients
    python main.py --mode real          # real-time mode (needs the upstream running)
    python main.py --client acme        # one tenant only
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app_collector.collector.ingester import Collector
from app_collector.config import CLIENTS, Mode, settings
from app_collector.rules import RULES_FILE, RuleStore
from app_collector.storage.db import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-tenant AI app usage collector")
    parser.add_argument("--mode", choices=[m.value for m in Mode], default=settings.default_mode.value)
    parser.add_argument("--client", action="append", choices=list(CLIENTS), dest="clients",
                        help="limit to one tenant (repeatable); default: all")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    db = Database(settings.database_url)
    db.create_all()
    run = await Collector(db, rules=RuleStore(RULES_FILE)).run(Mode(args.mode), args.clients)

    print()
    print(f"{'client':<10}{'status':<11}{'pages':>6}{'recv':>6}{'ins':>6}{'upd':>6}{'retry':>7}{'trunc':>7}{'no-risk':>9}")
    for stats in run.clients.values():
        print(f"{stats.client_id:<10}{stats.status:<11}{stats.pages:>6}{stats.received:>6}{stats.inserted:>6}"
              f"{stats.updated:>6}{stats.retries:>7}{stats.truncated:>7}{stats.missing_risk:>9}")
        if stats.error:
            print(f"  error: {stats.error}")
    print(f"\nRun {run.id} {run.status}")
    return 0 if run.status == "completed" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
