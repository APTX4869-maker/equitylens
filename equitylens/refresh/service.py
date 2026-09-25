"""Serialized, independently retryable publication of company data modules."""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

from equitylens.config import DB_PATH, RAW_DIR
from equitylens.domain.companies import get_company
from equitylens.storage.raw_store import MANIFEST_NAME, _write_immutable, _write_manifest
from equitylens.storage.writer import WriterBusy, writer_for

MODULES = ("financials", "segments", "management", "quotes")
_COMPANY_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class RefreshBusy(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _company_lock(ticker: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _COMPANY_LOCKS.setdefault(ticker, threading.Lock())


@contextmanager
def _staged_raw(raw_dir: Path, module: str, cik: str, ticker: str):
    """Give one synchronizer a private copy of the raw subtree it may update."""
    raw_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"equitylens-{ticker.lower()}-", dir=raw_dir.parent) as tmp:
        stage = Path(tmp) / "raw"
        stage.mkdir()
        relative = Path("market") / ticker if module == "quotes" else Path("sec") / cik
        source = raw_dir / relative
        if source.exists():
            shutil.copytree(source, stage / relative, dirs_exist_ok=True)
        yield stage, relative


def _publish_staged(stage: Path, raw_dir: Path, relative: Path) -> list[tuple[Path, bytes | None]]:
    """Publish immutable bytes first, then atomically advance staged manifests."""
    source = stage / relative
    if not source.exists():
        return []
    backups: list[tuple[Path, bytes | None]] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name in (MANIFEST_NAME, ".manifest.lock"):
            continue
        destination = raw_dir / path.relative_to(stage)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_immutable(destination, path.read_bytes())
    for manifest in sorted(source.rglob(MANIFEST_NAME)):
        destination = raw_dir / manifest.relative_to(stage)
        backups.append((destination, destination.read_bytes() if destination.exists() else None))
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_manifest(destination.parent, json.loads(manifest.read_text()))
    return backups


def _restore_manifests(backups: list[tuple[Path, bytes | None]]) -> None:
    for path, content in backups:
        if content is None:
            path.unlink(missing_ok=True)
        else:
            _write_manifest(path.parent, json.loads(content))


def _identity_snapshot(store, company_id: str) -> dict[str, str | None]:
    filing = store.query_one(
        """SELECT source_document_id FROM source_document
           WHERE company_id = ? AND document_type = 'COMPANYFACTS_SNAPSHOT'
           ORDER BY fetched_at DESC NULLS LAST, source_document_id DESC LIMIT 1""",
        [company_id],
    )
    proxy = store.query_one(
        """SELECT source_document_id FROM source_document
           WHERE company_id = ? AND form_type = 'DEF 14A'
           ORDER BY filed_at DESC NULLS LAST LIMIT 1""",
        [company_id],
    )
    quote = store.latest_market_quote(company_id)
    segment = store.query_one(
        "SELECT source_document_id FROM segment_fact WHERE company_id = ? ORDER BY period_end DESC NULLS LAST LIMIT 1",
        [company_id],
    )
    return {
        "financials": filing.get("source_document_id") if filing else None,
        "segments": segment.get("source_document_id") if segment else None,
        "management": proxy.get("source_document_id") if proxy else None,
        "quotes": quote.get("quote_id") if quote else None,
    }


def _result_fields(value) -> dict:
    if is_dataclass(value):
        data = asdict(value)
    elif isinstance(value, dict):
        data = dict(value)
    else:
        data = {}
    return {key: val for key, val in data.items() if key not in ("company",)}


def _run_module(store, ticker: str, module: str, raw_dir: Path):
    if module == "financials":
        from equitylens.ingestion.sec import sync as sec_sync
        return sec_sync.sync_company(ticker, fetch=True, store=store, raw_dir=raw_dir)
    if module == "segments":
        from equitylens.ingestion.sec import sync as sec_sync
        return sec_sync.sync_segments(ticker, fetch=True, store=store, raw_dir=raw_dir)
    if module == "management":
        from equitylens.ingestion.sec import management as management_sync
        return management_sync.sync_management(ticker, fetch=True, store=store, raw_dir=raw_dir)
    from equitylens.market import service as market_service
    reports = market_service.sync_quotes([ticker], fetch=True, store=store, raw_dir=raw_dir)
    if not any(getattr(report, "quotes", None) for report in reports):
        reasons = [warning for report in reports for warning in getattr(report, "warnings", [])]
        raise RuntimeError("; ".join(reasons) or "quote providers returned no observation")
    return {"reports": [report.line() for report in reports]}


def refresh_company(store, ticker: str, modules: list[str] | None = None,
                    raw_dir: Path | None = None) -> dict:
    raw_dir = raw_dir or (RAW_DIR if store.path == DB_PATH else store.path.parent / "raw")
    selected = list(dict.fromkeys(modules or MODULES))
    invalid = [module for module in selected if module not in MODULES]
    if invalid:
        raise ValueError(f"unknown refresh modules: {', '.join(invalid)}")
    company = get_company(ticker, store=store)
    company_lock = _company_lock(company.ticker)
    if not company_lock.acquire(blocking=False):
        raise RefreshBusy(f"{ticker} 正在刷新中，请稍后")
    writer_guard = writer_for(store).serialized(blocking=False)
    try:
        writer_guard.__enter__()
    except WriterBusy:
        company_lock.release()
        raise RefreshBusy("另一个公司正在写入 DuckDB，请稍后")

    try:
        before = _identity_snapshot(store, company.cik)
        results = {module: {"status": "skipped", "retryable": False} for module in MODULES}
        for module in selected:
            started = _now()
            backups: list[tuple[Path, bytes | None]] = []
            try:
                with _staged_raw(raw_dir, module, company.cik, company.ticker) as (stage, relative):
                    with store.transaction():
                        value = _run_module(store, company.ticker, module, stage)
                        backups = _publish_staged(stage, raw_dir, relative)
                results[module] = {
                    "status": "ok", "retryable": False, "started_at": started,
                    "finished_at": _now(), **_result_fields(value),
                }
            except Exception as exc:
                _restore_manifests(backups)
                results[module] = {
                    "status": "error", "retryable": True, "started_at": started,
                    "finished_at": _now(), "reason": str(exc),
                }

        after = _identity_snapshot(store, company.cik)
        for module in MODULES:
            results[module]["changed"] = before[module] != after[module]
        review_required = results["financials"]["changed"] or results["quotes"]["changed"]
        if review_required:
            reasons = []
            if results["financials"]["changed"]:
                reasons.append("财务披露已更新")
            if results["quotes"]["changed"]:
                reasons.append("行情观察已更新")
            with store.transaction():
                store._conn.execute(
                    """UPDATE valuation_plan SET review_status = 'needs_review', review_reason = ?
                       WHERE company_id = ? AND review_status = 'current'""",
                    ["；".join(reasons), company.cik],
                )
        errors = [module for module in selected if results[module]["status"] == "error"]
        return {
            "refresh_id": f"refresh_{uuid.uuid4().hex[:12]}",
            "ticker": company.ticker,
            "status": "partial" if errors else "ok",
            "modules": results,
            "review_required": review_required,
        }
    finally:
        writer_guard.__exit__(None, None, None)
        company_lock.release()
