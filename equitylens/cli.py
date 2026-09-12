"""EquityLens CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from equitylens.issuers.profile import load_profile_yaml

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


def _cmd_quotes(args) -> int:
    from equitylens.market.service import sync_quotes

    reports = sync_quotes(args.tickers, fetch=not args.no_fetch, provider_name=args.provider)
    for r in reports:
        print(r.line())
    return 0


def _cmd_promises(args) -> int:
    from equitylens.domain.companies import get_company
    from equitylens.domain.promises import ingest_cards, load_cards
    from equitylens.storage.duckdb_store import DuckDBStore

    store = DuckDBStore()
    store.connect()
    store.init_schema()
    for ticker in args.tickers:
        company = get_company(ticker, store=store)
        cards = load_cards(ticker)
        if not cards:
            print(f"{ticker}: data/evidence/promises/{ticker.upper()}/ 没有证据卡（*.json，忽略 _ 前缀）")
            continue
        r = ingest_cards(store, company.cik, ticker, cards)
        print(f"{ticker}: {r}")
    return 0


def cmd_sync(args) -> int:
    for ticker in args.tickers:
        report = sync_company(ticker, fetch=not args.no_fetch, force=args.force)
        print(report.line())
        if report.rejected_reasons:
            print("  rejected:", report.rejected_reasons)
    return 0


def _onboarding_request(method: str, path: str, *, json_body: dict | None = None):
    base = os.environ.get("EQUITYLENS_API_URL", "http://127.0.0.1:8000/api/v1")
    try:
        response = httpx.request(
            method,
            f"{base.rstrip('/')}{path}",
            json=json_body,
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            "local EquityLens API request failed; start the API and retry"
        ) from exc
    return response.json()


def _cmd_onboarding(args) -> int:
    path = f"/company-onboardings/{args.onboarding_id}"
    if args.onboarding_command == "show":
        print(json.dumps(_onboarding_request("GET", path), ensure_ascii=False, indent=2))
    elif args.onboarding_command == "export":
        package = _onboarding_request("GET", f"{path}/review-package")
        Path(args.output).write_text(
            json.dumps(package, ensure_ascii=False, indent=2) + "\n"
        )
        print(args.output)
    elif args.onboarding_command == "profile-import":
        profile = load_profile_yaml(args.file)
        result = _onboarding_request(
            "POST",
            f"{path}/profile",
            json_body={
                "expected_revision": args.revision,
                "profile": profile.model_dump(mode="json", exclude={"content_sha256"}),
            },
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.onboarding_command == "review":
        result = _onboarding_request(
            "POST",
            f"{path}/review",
            json_body={
                "expected_revision": args.revision,
                "fingerprint": args.fingerprint,
                "decision": args.decision,
                "reviewer": args.reviewer,
                "note": args.note,
            },
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
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

    quotes = sub.add_parser("sync-quotes", help="Sync latest market quotes (snapshot + market_quote row)")
    quotes.add_argument("tickers", nargs="+", help="Tickers, e.g. AAPL MSFT")
    quotes.add_argument("--no-fetch", action="store_true", help="Replay newest local snapshots only")
    quotes.add_argument("--provider", choices=["nasdaq", "tencent"], default=None,
                        help="Force one provider instead of the configured chain")
    quotes.set_defaults(func=lambda a: _cmd_quotes(a))

    prom = sub.add_parser("ingest-promises", help="Upsert promise evidence cards (data/evidence/promises/{TICKER}/*.json)")
    prom.add_argument("tickers", nargs="+", help="Tickers, e.g. AAPL MSFT")
    prom.set_defaults(func=lambda a: _cmd_promises(a))

    onboarding = sub.add_parser(
        "onboarding", help="Inspect and review company onboarding through the local API"
    )
    onboarding_sub = onboarding.add_subparsers(
        dest="onboarding_command", required=True
    )
    show = onboarding_sub.add_parser("show", help="Show one onboarding task")
    show.add_argument("onboarding_id")
    show.set_defaults(func=_cmd_onboarding)

    export = onboarding_sub.add_parser("export", help="Export a fixed review package")
    export.add_argument("onboarding_id")
    export.add_argument("--output", required=True)
    export.set_defaults(func=_cmd_onboarding)

    profile_import = onboarding_sub.add_parser(
        "profile-import", help="Validate and import an immutable issuer profile"
    )
    profile_import.add_argument("onboarding_id")
    profile_import.add_argument("--file", required=True)
    profile_import.add_argument("--revision", required=True, type=int)
    profile_import.set_defaults(func=_cmd_onboarding)

    review = onboarding_sub.add_parser("review", help="Approve or reject an exact candidate")
    review.add_argument("onboarding_id")
    review.add_argument("--fingerprint", required=True)
    review.add_argument("--revision", required=True, type=int)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", default="")
    review.add_argument("--decision", choices=["APPROVE", "REJECT"], required=True)
    review.set_defaults(func=_cmd_onboarding)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
