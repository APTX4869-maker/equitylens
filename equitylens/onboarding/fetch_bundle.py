"""Deterministic selection for immutable onboarding SEC filing bundles."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from equitylens.onboarding.models import FetchDocument


class FetchBundleIncomplete(ValueError):
    """A required filing input cannot be fixed safely."""

    code = "FETCH_BUNDLE_INCOMPLETE"
    remediation = "REFETCH"


class FetchBundleCorrupted(ValueError):
    """A fixed bundle locator no longer contains the recorded bytes."""

    code = "FETCH_BUNDLE_CORRUPTED"
    remediation = "REFETCH"


def load_bundle_document(raw_dir: Path, document: FetchDocument) -> bytes:
    root = Path(raw_dir).resolve()
    path = (root / document.raw_locator).resolve()
    if root not in path.parents:
        raise FetchBundleCorrupted(f"bundle locator escapes raw root: {document.document_id}")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise FetchBundleCorrupted(f"bundle document is missing: {document.document_id}") from exc
    if hashlib.sha256(content).hexdigest() != document.content_sha256:
        raise FetchBundleCorrupted(f"bundle document hash mismatch: {document.document_id}")
    return content


class SelectedFiling(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accession_number: str
    form_type: str
    base_form: str
    report_date: date
    filing_date: date
    primary_document: str


def _submission_rows(value: dict | list) -> list[dict]:
    if isinstance(value, list):
        return [dict(item) for item in value]
    if not isinstance(value, dict) or not value:
        return []
    keys = list(value)
    return [dict(zip(keys, values)) for values in zip(*(value[key] for key in keys))]


def collect_submission_rows(
    submissions: dict, history_payloads: dict[str, dict]
) -> list[dict]:
    filings = submissions.get("filings") or {}
    rows = _submission_rows(filings.get("recent") or {})
    for declared in filings.get("files") or []:
        name = str(declared.get("name") or "")
        if not name or name not in history_payloads:
            raise FetchBundleIncomplete(f"declared submissions history is missing: {name}")
        rows.extend(_submission_rows(history_payloads[name]))
    return rows


def _base_form(form: str) -> str:
    return form[:-2] if form.endswith("/A") else form


def select_required_filings(
    rows: Iterable[dict], *, as_of: datetime
) -> list[SelectedFiling]:
    parsed: list[SelectedFiling] = []
    for row in rows:
        form = str(row.get("form") or "")
        base_form = _base_form(form)
        if base_form not in {"10-K", "10-Q"}:
            continue
        try:
            filing_date = date.fromisoformat(str(row["filingDate"]))
            report_date = date.fromisoformat(str(row["reportDate"]))
            accession = str(row["accessionNumber"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FetchBundleIncomplete("required filing identity is incomplete") from exc
        if filing_date > as_of.date():
            continue
        primary = str(row.get("primaryDocument") or "")
        parsed.append(
            SelectedFiling(
                accession_number=accession,
                form_type=form,
                base_form=base_form,
                report_date=report_date,
                filing_date=filing_date,
                primary_document=primary,
            )
        )

    selected_reports: dict[str, set[date]] = {}
    for base_form, count in (("10-K", 3), ("10-Q", 8)):
        reports = sorted(
            {item.report_date for item in parsed if item.base_form == base_form and not item.form_type.endswith("/A")},
            reverse=True,
        )[:count]
        if len(reports) < count:
            raise FetchBundleIncomplete(f"required {base_form} quality window is incomplete")
        selected_reports[base_form] = set(reports)

    selected = [
        item
        for item in parsed
        if item.report_date in selected_reports[item.base_form]
    ]
    missing_primary = [item.accession_number for item in selected if not item.primary_document]
    if missing_primary:
        raise FetchBundleIncomplete(
            f"required filing primaryDocument is missing: {', '.join(missing_primary)}"
        )
    return sorted(
        selected,
        key=lambda item: (item.report_date, item.filing_date, item.accession_number),
    )
