"""Normalization: SEC companyfacts JSON -> raw_fact + canonical_fact rows.

The anti-hallucination rule (CODEX_START_HERE.md) forbids
`LLM -> number -> persisted fact`. Here the chain is strictly
`SEC source -> parser -> raw fact -> normalized canonical fact`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from equitylens.config import PARSER_VERSION
from equitylens.normalization.fiscal_periods import FiscalCalendar, derive_standalone_quarters
from equitylens.normalization.taxonomy.mappings import MappingRegistry


@dataclass
class NormalizeResult:
    facts_seen: int = 0
    facts_accepted: int = 0
    facts_rejected: int = 0
    canonical_count: int = 0
    derived_count: int = 0
    rejected_reasons: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _fact_id(prefix: str, doc_id: str, concept: str, unit: str, start, end, instant, value, accn) -> str:
    h = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{doc_id}|{concept}|{unit}|{start}|{end}|{instant}|{value}|{accn}",
    ).hex[:12]
    return f"{prefix}_{h}"


def normalize_companyfacts(
    companyfacts: dict,
    mappings: MappingRegistry,
    calendar: FiscalCalendar,
    source_document_id: str,
    company_id: str,
) -> tuple[list[dict], list[dict], NormalizeResult]:
    """Return (raw_fact_rows, canonical_fact_rows, result)."""
    raw_rows: list[dict] = []
    canonical_rows: list[dict] = []
    result = NormalizeResult()
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    seen: set[tuple] = set()

    facts = companyfacts.get("facts", {})
    for taxonomy, concepts in facts.items():
        for concept, cdata in concepts.items():
            rule = mappings.find(taxonomy, concept)
            for unit, entries in (cdata.get("units") or {}).items():
                for e in entries:
                    result.facts_seen += 1
                    dedupe_key = (taxonomy, concept, unit, e.get("start"), e.get("end"),
                                  e.get("instant"), e.get("val"), e.get("accn"))
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)

                    raw_id = _fact_id("rf", source_document_id, concept, unit,
                                      e.get("start"), e.get("end"), e.get("instant"),
                                      e.get("val"), e.get("accn"))
                    raw_row = {
                        "raw_fact_id": raw_id,
                        "source_document_id": source_document_id,
                        "taxonomy": taxonomy,
                        "concept": concept,
                        "unit": unit,
                        "raw_value": e.get("val"),
                        "start_date": e.get("start"),
                        "end_date": e.get("end") if e.get("start") else None,
                        "instant_date": e.get("instant") or (None if e.get("start") else e.get("end")),
                        "context_id": None,
                        "dimensions_json": None,
                        "fiscal_year": e.get("fy"),
                        "fiscal_period": e.get("fp"),
                        "frame": e.get("frame"),
                        "accession_number": e.get("accn"),
                        "form_type": e.get("form"),
                        "filed_at": e.get("filed"),
                        "raw_json": json.dumps(e, ensure_ascii=False),
                    }
                    raw_rows.append(raw_row)

                    if rule is None:
                        result.facts_rejected += 1
                        result.rejected_reasons.setdefault("unmapped_concept", 0)
                        result.rejected_reasons["unmapped_concept"] += 1
                        continue

                    # unit family sanity: reject obviously incompatible units
                    unit_family = rule.unit_family
                    ok_unit = unit.lower() in {
                        "usd", "usd/shares", "shares", "pure", "usd/shares,",
                    } or unit.lower().startswith(("usd", "shares", "pure"))
                    if not ok_unit:
                        result.facts_rejected += 1
                        result.rejected_reasons.setdefault("unexpected_unit", 0)
                        result.rejected_reasons["unexpected_unit"] += 1
                        continue

                    if rule.metric_type == "instant":
                        instant_date = e.get("instant") or (None if e.get("start") else e.get("end"))
                        if not instant_date:
                            result.facts_rejected += 1
                            result.rejected_reasons.setdefault("missing_period", 0)
                            result.rejected_reasons["missing_period"] += 1
                            continue
                        period = calendar.resolve_instant(instant_date)
                    elif rule.metric_type == "duration" and e.get("start") and e.get("end"):
                        period = calendar.resolve_duration(e["start"], e["end"], e.get("fp"))
                    else:
                        result.facts_rejected += 1
                        result.rejected_reasons.setdefault("missing_period", 0)
                        result.rejected_reasons["missing_period"] += 1
                        continue

                    if period.period_type == "UNKNOWN":
                        result.facts_rejected += 1
                        result.rejected_reasons.setdefault("unknown_period", 0)
                        result.rejected_reasons["unknown_period"] += 1
                        continue

                    value = float(e["val"])
                    if rule.sign == "outflow_positive":
                        value = abs(value)

                    cf_id = _fact_id("cf", source_document_id, rule.canonical_metric, unit,
                                     raw_id, None, None, e.get("val"), e.get("accn"))
                    canonical_rows.append({
                        "canonical_fact_id": cf_id,
                        "company_id": company_id,
                        "canonical_metric": rule.canonical_metric,
                        "period_type": period.period_type,
                        "fiscal_year": period.fiscal_year,
                        "fiscal_quarter": period.fiscal_quarter,
                        "period_start": period.period_start,
                        "period_end": period.period_end,
                        "instant_date": period.instant_date,
                        "value": value,
                        "unit": unit,
                        "status": "NORMALIZED",
                        "mapping_rule_id": rule.rule_id,
                        "mapping_version": mappings.mapping_version,
                        "source_raw_fact_ids": json.dumps([raw_id], ensure_ascii=False),
                        "source_document_id": source_document_id,
                        "as_known_at": e.get("filed") or e.get("accn"),
                        "created_at": created_at,
                        "warnings_json": json.dumps(period.warnings, ensure_ascii=False),
                    })
                    result.canonical_count += 1
                    result.facts_accepted += 1

    # Some issuers disclose only total liabilities-and-equity plus total equity.
    # Derive liabilities from those two reported lines while preserving both raw
    # facts as lineage; never infer it from unrelated balance-sheet components.
    raw_by_id = {row["raw_fact_id"]: row for row in raw_rows}

    def balance_basis(row: dict) -> tuple | None:
        refs = json.loads(row["source_raw_fact_ids"])
        accessions = {
            raw_by_id[raw_id].get("accession_number")
            for raw_id in refs
            if raw_id in raw_by_id
        }
        if len(accessions) != 1 or None in accessions:
            return None
        return (
            row.get("instant_date"),
            row.get("unit"),
            row.get("as_known_at"),
            next(iter(accessions)),
        )

    direct_liability_bases = {
        basis
        for row in canonical_rows
        if row["canonical_metric"] == "TOTAL_LIABILITIES"
        and (basis := balance_basis(row)) is not None
    }
    balance_by_basis: dict[tuple, dict[str, dict]] = {}
    for row in canonical_rows:
        if row["canonical_metric"] not in {"BALANCE_TOTAL", "TOTAL_EQUITY"}:
            continue
        basis = balance_basis(row)
        if basis is not None:
            balance_by_basis.setdefault(basis, {})[row["canonical_metric"]] = row
    for basis, pair in balance_by_basis.items():
        if basis in direct_liability_bases or set(pair) != {"BALANCE_TOTAL", "TOTAL_EQUITY"}:
            continue
        total, equity = pair["BALANCE_TOTAL"], pair["TOTAL_EQUITY"]
        instant_date = total["instant_date"]
        raw_ids = sorted(
            set(json.loads(total["source_raw_fact_ids"]))
            | set(json.loads(equity["source_raw_fact_ids"]))
        )
        canonical_rows.append(
            {
                **total,
                "canonical_fact_id": _fact_id(
                    "cf", source_document_id, "TOTAL_LIABILITIES", total["unit"],
                    instant_date, None, None, float(total["value"]) - float(equity["value"]),
                    f"derived-balance|{basis[3]}|{basis[2]}",
                ),
                "canonical_metric": "TOTAL_LIABILITIES",
                "value": float(total["value"]) - float(equity["value"]),
                "status": "CALCULATED",
                "mapping_rule_id": "total_liabilities.balance_difference.v1",
                "source_raw_fact_ids": json.dumps(raw_ids, ensure_ascii=False),
                "warnings_json": json.dumps(["derived: liabilities-and-equity minus total equity"]),
            }
        )
        result.derived_count += 1

    # Derive standalone quarters for cash-flow style metrics (YTD chain).
    derived_rows: list[dict] = []
    raw_lineage_by_fact = {
        row["canonical_fact_id"]: json.loads(row["source_raw_fact_ids"])
        for row in canonical_rows
    }
    derive_metrics = [m for m in mappings.all_metrics()
                      if (mappings.metric(m) and mappings.metric(m).derive_standalone_quarter)]
    for metric in derive_metrics:
        metric_facts = [c for c in canonical_rows if c["canonical_metric"] == metric]
        for year in sorted({c["fiscal_year"] for c in metric_facts if c["fiscal_year"]}):
            year_facts = [c for c in metric_facts if c["fiscal_year"] == year]
            for d in derive_standalone_quarters(year_facts, year, calendar):
                    source_raw_ids = sorted(
                        {
                            raw_id
                            for fact_id in d.get("input_ids") or []
                            for raw_id in raw_lineage_by_fact.get(fact_id, [])
                        }
                    )
                    d_id = _fact_id("cf", source_document_id, metric, d.get("unit") or "USD",
                                    d.get("period_start"), d.get("period_end"), None,
                                    d.get("value"), "derived")
                    derived_rows.append({
                        "canonical_fact_id": d_id,
                        "company_id": company_id,
                        "canonical_metric": metric,
                        "period_type": "Q_STANDALONE",
                        "fiscal_year": d["fiscal_year"],
                        "fiscal_quarter": d["fiscal_quarter"],
                        "period_start": d.get("period_start"),
                        "period_end": d.get("period_end"),
                        "instant_date": None,
                        "value": d["value"],
                        "unit": d.get("unit"),
                        "status": "CALCULATED",
                        "mapping_rule_id": d.get("formula_id"),
                        "mapping_version": mappings.mapping_version,
                        "source_raw_fact_ids": json.dumps(source_raw_ids, ensure_ascii=False),
                        "source_document_id": source_document_id,
                        "as_known_at": d.get("as_known_at"),
                        "created_at": created_at,
                        "warnings_json": json.dumps([f"derived: {d.get('derivation')}"], ensure_ascii=False),
                    })
                    result.derived_count += 1
    canonical_rows.extend(derived_rows)
    return raw_rows, canonical_rows, result
