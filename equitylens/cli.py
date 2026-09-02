"""EquityLens CLI."""

from __future__ import annotations

import argparse
import sys

from equitylens.ingestion.sec.management import sync_management
from equitylens.ingestion.sec.sync import sync_company, sync_segments


def _cmd_segments(args) -> int:
    for ticker in args.tickers:
        report = sync_segments(ticker, fetch=not args.no_fetch, limit_per_form=args.limit)
        print(f"{report.company}: segment facts={report.facts_accepted}")
    return 0


def _cmd_management(args) -> int:
    for ticker in args.tickers:
        r = sync_management(ticker, fetch=not args.no_fetch, forms4_limit=args.forms4)
        print(f"{r.company}: execs={r.executives} comp={r.compensation_rows} board={r.board_members} form4={r.insider_transactions}")
        if r.warnings:
            print("  warnings:", r.warnings)
    return 0


def cmd_sync(args) -> int:
    for ticker in args.tickers:
        report = sync_company(ticker, fetch=not args.no_fetch, force=args.force)
        print(report.line())
        if report.rejected_reasons:
            print("  rejected:", report.rejected_reasons)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="equitylens", description="EquityLens CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="Fetch + normalize SEC data for a company")
    sync.add_argument("tickers", nargs="+", help="Tickers, e.g. AAPL MSFT")
    sync.add_argument("--no-fetch", action="store_true", help="Normalize from cached raw snapshots only")
    sync.add_argument("--force", action="store_true", help="Refetch even if cached snapshots exist")
    sync.set_defaults(func=cmd_sync)

    seg = sub.add_parser("sync-segments", help="Fetch 10-K/10-Q filings and extract segment facts")
    seg.add_argument("tickers", nargs="+", help="Tickers, e.g. AAPL MSFT")
    seg.add_argument("--no-fetch", action="store_true", help="Use cached filing documents only")
    seg.add_argument("--limit", type=int, default=5, help="Filings per form (10-K/10-Q)")
    seg.set_defaults(func=lambda a: _cmd_segments(a))

    mgmt = sub.add_parser("sync-management", help="Fetch DEF 14A + Form 4 and extract management data")
    mgmt.add_argument("tickers", nargs="+", help="Tickers, e.g. AAPL MSFT")
    mgmt.add_argument("--no-fetch", action="store_true", help="Use cached documents only")
    mgmt.add_argument("--forms4", type=int, default=12, help="Number of recent Form 4 filings to parse")
    mgmt.set_defaults(func=lambda a: _cmd_management(a))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
