"""Run configured quality gates and persist their immutable report."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import yaml

from equitylens.config import CONFIG_DIR
from equitylens.publication.models import sha256_json
from equitylens.quality.models import CheckResult, CheckStatus, QualityReport, Severity
from equitylens.quality.rules import (
    balance_equation,
    cash_bridge,
    cash_bridge_with_disclosed_change,
    eps_reconciliation,
    evidence_required,
    required_period_coverage,
    segment_reconciliation,
)
from equitylens.storage.raw_store import sha256_bytes
from equitylens.storage.writer import writer_for


def _segment_revenue_for_anchor(
    segments: list[dict], annual_anchor: dict | None
) -> list[dict]:
    """Select segment revenue on the same annual basis as consolidated revenue."""
    if annual_anchor is None:
        return []
    anchor_year = annual_anchor.get("fiscal_year")
    anchor_end = str(annual_anchor.get("period_end") or "")
    return [
        item
        for item in segments
        if item.get("metric_name") == "REVENUE"
        and item.get("period_type") == "FY"
        and item.get("fiscal_year") == anchor_year
        and str(item.get("period_end") or "") == anchor_end
        and not item.get("aggregate")
    ]


class QualityEngine:
    def __init__(self, store, *, config_path: Path | None = None):
        self.store = store
        self.config_path = config_path or CONFIG_DIR / "quality" / "us_gaap_operating_v1.yaml"
        self.config = yaml.safe_load(self.config_path.read_text())
        self.rule_version = str(self.config["version"])

    def validate(self, dataset_id: str) -> QualityReport:
        dataset = self.store.query_one(
            "SELECT * FROM dataset_version WHERE dataset_id=?", [dataset_id]
        )
        if dataset is None:
            raise KeyError(dataset_id)
        profile_row = self.store.query_one(
            "SELECT content_json FROM issuer_profile_version WHERE profile_id=?",
            [dataset["profile_id"]],
        )
        profile = json.loads(profile_row["content_json"])
        rows = self.store.query(
            "SELECT entity_type,row_id,payload_json,payload_sha256 FROM dataset_row WHERE dataset_id=?",
            [dataset_id],
        )
        parsed: dict[str, list[dict]] = {}
        checks: list[CheckResult] = []
        for row in rows:
            payload = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) else row["payload_json"]
            if sha256_json(payload) != row["payload_sha256"]:
                checks.append(
                    CheckResult(
                        check_id="LINEAGE.payload_hash",
                        scope_key=f"{row['entity_type']}:{row['row_id']}",
                        status=CheckStatus.FAIL,
                        reason="SOURCE_CORRUPTED",
                    )
                )
            parsed.setdefault(row["entity_type"], []).append(payload)

        template = profile.get("template")
        supported = template == "us_gaap_operating_v1"
        checks.append(
            CheckResult(
                check_id="IDENTITY.template",
                status=CheckStatus.PASS if supported else CheckStatus.UNSUPPORTED,
                reason=None if supported else "TEMPLATE_UNSUPPORTED",
            )
        )
        facts = parsed.get("canonical_fact", [])
        metrics = {fact.get("canonical_metric") for fact in facts}
        for metric in self.config.get("required_metrics") or []:
            checks.append(
                CheckResult(
                    check_id="CORE.metric",
                    scope_key=metric,
                    status=CheckStatus.PASS if metric in metrics else CheckStatus.FAIL,
                    actual={"present": metric in metrics},
                    expected={"present": True},
                    reason=None if metric in metrics else "CORE_METRIC_MISSING",
                )
            )
        coverage_metric = self.config.get("coverage_metric", "REVENUE")
        coverage_facts = [f for f in facts if f.get("canonical_metric") == coverage_metric]
        annual = [f["fiscal_year"] for f in coverage_facts if f.get("period_type") == "FY" and f.get("fiscal_year")]
        quarters = [
            f"{f['fiscal_year']}Q{f['fiscal_quarter']}"
            for f in coverage_facts
            if f.get("period_type") == "Q_STANDALONE" and f.get("fiscal_year") and f.get("fiscal_quarter")
        ]
        checks.append(
            required_period_coverage(
                annual_years=annual,
                quarters=quarters,
                required_annual=int(self.config["coverage"]["annual_years"]),
                required_quarters=int(self.config["coverage"]["quarters"]),
            )
        )
        raw_ids = {item.get("raw_fact_id") for item in parsed.get("raw_fact", [])}
        raw_by_id = {
            item.get("raw_fact_id"): item for item in parsed.get("raw_fact", [])
        }
        for fact in facts:
            refs = fact.get("source_raw_fact_ids") or []
            if isinstance(refs, str):
                refs = json.loads(refs)
            missing = set(refs) - raw_ids
            checks.append(
                CheckResult(
                    check_id="LINEAGE.fact_sources",
                    scope_key=str(fact.get("canonical_fact_id")),
                    status=CheckStatus.PASS if refs and not missing else CheckStatus.FAIL,
                    actual={"source_count": len(refs), "missing": sorted(missing)},
                    reason=None if refs and not missing else "EVIDENCE_MISSING",
                )
            )
        filing_document_ids = {
            document.get("source_document_id")
            for document in parsed.get("source_document", [])
            if document.get("document_type") in {"FILING_DOCUMENT", "IXBRL_DOCUMENT"}
        }
        required_metrics = set(self.config.get("required_metrics") or [])
        missing_filing_context = []
        for fact in facts:
            if fact.get("canonical_metric") not in required_metrics:
                continue
            refs = fact.get("source_raw_fact_ids") or []
            if isinstance(refs, str):
                refs = json.loads(refs)
            sources = [raw_by_id.get(raw_id) for raw_id in refs]
            if not sources or any(
                source is None
                or source.get("source_document_id") not in filing_document_ids
                or not source.get("context_id")
                or not source.get("locator")
                for source in sources
            ):
                missing_filing_context.append(fact.get("canonical_fact_id"))
        checks.append(
            CheckResult(
                check_id="LINEAGE.filing_context",
                status=CheckStatus.FAIL if missing_filing_context else CheckStatus.PASS,
                actual={"missing_fact_ids": sorted(str(item) for item in missing_filing_context)},
                reason="FILING_CONTEXT_MISSING" if missing_filing_context else None,
            )
        )
        document_keys = {
            (document.get("source_document_id"), document.get("content_sha256"))
            for document in parsed.get("source_document", [])
        }
        for document in parsed.get("source_document", []):
            local_path = document.get("local_path")
            valid = False
            if local_path:
                path = Path(local_path)
                if path.exists():
                    valid = sha256_bytes(path.read_bytes()) == document.get("content_sha256")
            checks.append(
                CheckResult(
                    check_id="LINEAGE.source_hash",
                    scope_key=str(document.get("source_document_id")),
                    status=CheckStatus.PASS if valid else CheckStatus.FAIL,
                    evidence=[{"local_path": local_path, "content_sha256": document.get("content_sha256")}],
                    reason=None if valid else "SOURCE_CORRUPTED",
                )
            )
        evidence = profile.get("evidence") or []
        resolved_evidence = {
            item.get("evidence_id"): item
            for item in evidence
            if (item.get("source_document_id"), item.get("content_sha256"))
            in document_keys
        }
        applicability_evidence = profile.get("applicability_evidence") or {}
        for module, claim in (profile.get("applicability") or {}).items():
            status = {
                "not_applicable": CheckStatus.NOT_APPLICABLE,
                "not_disclosed": CheckStatus.NOT_DISCLOSED,
            }.get(claim)
            if status:
                claim_evidence = [
                    resolved_evidence[evidence_id]
                    for evidence_id in applicability_evidence.get(module, [])
                    if evidence_id in resolved_evidence
                ]
                checks.append(
                    evidence_required(
                        check_id=f"{module}.applicability",
                        claimed_status=status,
                        evidence=claim_evidence,
                    )
                )
        latest = {}
        for fact in facts:
            metric = fact.get("canonical_metric")
            if metric and metric not in latest:
                latest[metric] = fact
            elif metric:
                current_key = (
                    str(fact.get("period_end") or fact.get("instant_date") or ""),
                    str(fact.get("as_known_at") or ""),
                )
                existing_key = (
                    str(latest[metric].get("period_end") or latest[metric].get("instant_date") or ""),
                    str(latest[metric].get("as_known_at") or ""),
                )
                if current_key > existing_key:
                    latest[metric] = fact

        annual_anchors = [
            fact
            for fact in coverage_facts
            if fact.get("period_type") == "FY" and fact.get("fiscal_year")
        ]
        annual_anchor = max(
            annual_anchors,
            key=lambda fact: (
                int(fact["fiscal_year"]),
                str(fact.get("period_end") or ""),
                str(fact.get("as_known_at") or ""),
            ),
            default=None,
        )
        latest_annual_year = annual_anchor.get("fiscal_year") if annual_anchor else None
        anchor_end = str(annual_anchor.get("period_end") or "") if annual_anchor else ""
        anchor_known = str(annual_anchor.get("as_known_at") or "") if annual_anchor else ""
        annual_basis: dict[str, dict] = {}
        for fact in facts:
            if latest_annual_year is None or fact.get("fiscal_year") != latest_annual_year:
                continue
            if fact.get("period_type") not in {"FY", "INSTANT"}:
                continue
            if str(fact.get("period_end") or fact.get("instant_date") or "") != anchor_end:
                continue
            if str(fact.get("as_known_at") or "") != anchor_known:
                continue
            metric = fact.get("canonical_metric")
            if not metric:
                continue
            key = (str(fact.get("period_end") or fact.get("instant_date") or ""), str(fact.get("as_known_at") or ""))
            current = annual_basis.get(metric)
            current_key = (str(current.get("period_end") or current.get("instant_date") or ""), str(current.get("as_known_at") or "")) if current else ("", "")
            if current is None or key > current_key:
                annual_basis[metric] = fact

        def value(metric):
            item = annual_basis.get(metric)
            return item.get("value") if item else None

        equity_metric = "TOTAL_EQUITY" if value("TOTAL_EQUITY") is not None else "STOCKHOLDERS_EQUITY"
        balance_values = [value("TOTAL_ASSETS"), value("TOTAL_LIABILITIES"), value(equity_metric)]
        if all(item is not None for item in balance_values):
            checks.append(
                balance_equation(
                    assets=balance_values[0],
                    liabilities=balance_values[1],
                    equity=balance_values[2],
                    mezzanine=0 if equity_metric == "TOTAL_EQUITY" else value("MEZZANINE_EQUITY") or 0,
                    decimals=(annual_basis.get("TOTAL_ASSETS") or latest["TOTAL_ASSETS"]).get("decimals", 0),
                )
            )
        else:
            checks.append(
                CheckResult(
                    check_id="BALANCE.equation",
                    status=CheckStatus.FAIL,
                    actual={"available": [name for name in ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "STOCKHOLDERS_EQUITY") if value(name) is not None]},
                    reason="BALANCE_INPUT_MISSING",
                )
            )

        bridge_cash_metric = (
            "CASH_AND_RESTRICTED_CASH"
            if value("CASH_AND_RESTRICTED_CASH") is not None
            else "CASH_AND_EQUIVALENTS"
        )
        prior_cash = [
            fact for fact in facts
            if fact.get("canonical_metric") == bridge_cash_metric
            and fact.get("period_type") == "INSTANT"
            and latest_annual_year is not None
            and fact.get("fiscal_year") == latest_annual_year - 1
            and str(fact.get("as_known_at") or "") == anchor_known
        ]
        opening_cash = max(
            prior_cash,
            key=lambda fact: (str(fact.get("instant_date") or ""), str(fact.get("as_known_at") or "")),
            default=None,
        )
        cash_names = (
            "OPERATING_CASH_FLOW",
            "INVESTING_CASH_FLOW",
            "FINANCING_CASH_FLOW",
            bridge_cash_metric,
        )
        cash_values = [value(name) for name in cash_names]
        fx_effect = value("FX_EFFECT_ON_CASH")
        disclosed_change = value("NET_CHANGE_IN_CASH_INCLUDING_FX")
        if opening_cash is not None and all(item is not None for item in cash_values):
            decimals = (annual_basis.get(bridge_cash_metric) or latest[bridge_cash_metric]).get("decimals", 0)
            if fx_effect is not None:
                checks.append(
                    cash_bridge(
                        opening=opening_cash["value"],
                        operating=cash_values[0],
                        investing=cash_values[1],
                        financing=cash_values[2],
                        fx=fx_effect,
                        closing=cash_values[3],
                        other=value("OTHER_CASH_CHANGE") or 0,
                        decimals=decimals,
                    )
                )
            elif disclosed_change is not None:
                checks.append(
                    cash_bridge_with_disclosed_change(
                        opening=opening_cash["value"],
                        operating=cash_values[0],
                        investing=cash_values[1],
                        financing=cash_values[2],
                        disclosed_change=disclosed_change,
                        closing=cash_values[3],
                        decimals=decimals,
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        check_id="CASH.bridge",
                        status=CheckStatus.FAIL,
                        actual={"missing": ["FX_EFFECT_ON_CASH_OR_NET_CHANGE_IN_CASH_INCLUDING_FX"]},
                        reason="CASH_BRIDGE_INPUT_MISSING",
                    )
                )
        else:
            checks.append(
                CheckResult(
                    check_id="CASH.bridge",
                    status=CheckStatus.FAIL,
                    actual={"missing": (["CASH_BEGINNING"] if opening_cash is None else []) + [name for name, item in zip(cash_names, cash_values) if item is None]},
                    reason="CASH_BRIDGE_INPUT_MISSING",
                )
            )

        eps_values = [value("DILUTED_EPS"), value("NET_INCOME"), value("DILUTED_WEIGHTED_AVG_SHARES")]
        if all(item is not None for item in eps_values):
            checks.append(
                eps_reconciliation(
                    reported_eps=eps_values[0],
                    numerator=eps_values[1],
                    weighted_shares=eps_values[2],
                    explicit_method=profile.get("eps_method"),
                )
            )
        else:
            checks.append(
                CheckResult(
                    check_id="EPS.reconciliation",
                    status=CheckStatus.FAIL,
                    reason="EPS_INPUT_MISSING",
                )
            )

        segments = parsed.get("segment_fact", [])
        segment_revenue = _segment_revenue_for_anchor(segments, annual_anchor)
        if segment_revenue and value("REVENUE") is not None:
            eliminations = sum(
                float(item.get("value") or 0)
                for item in segment_revenue
                if item.get("segment_kind") in ("elimination", "unallocated")
            )
            operating_segments = [
                float(item.get("value") or 0)
                for item in segment_revenue
                if item.get("segment_kind") not in ("elimination", "unallocated", "product", "geo")
            ]
            checks.append(
                segment_reconciliation(
                    consolidated=float(value("REVENUE")),
                    segments=operating_segments,
                    eliminations=eliminations if any(item.get("segment_kind") in ("elimination", "unallocated") for item in segment_revenue) else None,
                )
            )
        else:
            segment_claim = (profile.get("applicability") or {}).get("SEGMENTS")
            status = CheckStatus.NOT_DISCLOSED if segment_claim == "not_disclosed" else CheckStatus.FAIL
            segment_evidence = [
                resolved_evidence[evidence_id]
                for evidence_id in applicability_evidence.get("SEGMENTS", [])
                if evidence_id in resolved_evidence
            ]
            checks.append(
                evidence_required(
                    check_id="SEGMENTS.reconciliation",
                    claimed_status=status,
                    evidence=segment_evidence if status == CheckStatus.NOT_DISCLOSED else [],
                )
            )

        raw_concepts = {
            f"{item.get('taxonomy')}:{item.get('concept')}"
            for item in parsed.get("raw_fact", [])
            if item.get("taxonomy") and item.get("concept")
        }
        cash_debt = profile.get("cash_debt") or {}
        configured_components = set(cash_debt.get("cash_components") or []) | set(cash_debt.get("debt_components") or [])
        missing_components = configured_components - raw_concepts
        checks.append(
            CheckResult(
                check_id="CASH_DEBT.components",
                status=CheckStatus.PASS if configured_components and not missing_components else CheckStatus.FAIL,
                actual={"missing_concepts": sorted(item for item in missing_components if item)},
                reason=None if configured_components and not missing_components else "CASH_DEBT_EVIDENCE_MISSING",
            )
        )
        registry_securities = self.store.query(
            """
            SELECT s.class_label, s.exchange, s.currency, s.instrument_type, a.ticker
            FROM security s
            JOIN security_ticker_alias a ON a.security_id=s.security_id
            WHERE s.company_id=? AND s.status='ACTIVE'
              AND a.valid_from <= CURRENT_DATE
              AND (a.valid_to IS NULL OR a.valid_to >= CURRENT_DATE)
            """,
            [dataset["company_id"]],
        )
        def security_identity(item: dict) -> dict:
            return {
                "ticker": str(item.get("ticker") or "").upper(),
                "class_label": item.get("class_label"),
                "exchange": str(item.get("exchange") or ""),
                "currency": str(item.get("currency") or "").upper(),
                "instrument_type": item.get("instrument_type"),
            }

        def security_key(item: dict) -> tuple:
            identity = security_identity(item)
            return (
                identity["ticker"],
                identity["class_label"],
                identity["exchange"].casefold(),
                identity["currency"],
                identity["instrument_type"],
            )

        configured_securities = profile.get("securities") or []
        configured_by_key = {security_key(item): item for item in configured_securities}
        registry_by_key = {security_key(item): item for item in registry_securities}
        identity_failures = []
        for configured in configured_securities:
            matches = security_key(configured) in registry_by_key
            evidence_ids = configured.get("evidence") or []
            evidence_ok = bool(evidence_ids) and all(
                evidence_id in resolved_evidence for evidence_id in evidence_ids
            )
            if not matches or not evidence_ok:
                identity_failures.append(
                    {
                        "ticker": configured.get("ticker"),
                        "registry_match": matches,
                        "evidence_resolved": evidence_ok,
                    }
                )
        missing_registry = [
            security_identity(configured_by_key[key])
            for key in sorted(
                configured_by_key.keys() - registry_by_key.keys(),
                key=lambda value: tuple(str(part or "") for part in value),
            )
        ]
        unreviewed_registry = [
            security_identity(registry_by_key[key])
            for key in sorted(
                registry_by_key.keys() - configured_by_key.keys(),
                key=lambda value: tuple(str(part or "") for part in value),
            )
        ]
        security_ok = bool(configured_securities) and not (
            identity_failures or missing_registry or unreviewed_registry
        )
        checks.append(
            CheckResult(
                check_id="SECURITY.identity",
                status=CheckStatus.PASS if security_ok else CheckStatus.FAIL,
                actual={
                    "failures": identity_failures,
                    "missing_registry": missing_registry,
                    "unreviewed_registry": unreviewed_registry,
                },
                reason=None if security_ok else "SECURITY_EVIDENCE_MISSING",
            )
        )

        failed = any(
            item.severity == Severity.BLOCKER
            and item.status in (CheckStatus.FAIL, CheckStatus.UNSUPPORTED)
            for item in checks
        )
        fingerprint = sha256_json(
            {
                "dataset_hash": dataset["dataset_hash"],
                "rule_version": self.rule_version,
                "checks": [item.model_dump(mode="json") for item in checks],
            }
        )
        report_id = str(uuid.uuid4())
        with writer_for(self.store).transaction(self.store):
            self.store._conn.execute(
                "INSERT INTO quality_report VALUES (?, ?, ?, ?, ?, now())",
                [report_id, dataset_id, self.rule_version, "FAIL" if failed else "PASS", fingerprint],
            )
            for item in checks:
                self.store._conn.execute(
                    """
                    INSERT INTO company_quality_check VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        report_id,
                        item.check_id,
                        item.scope_key,
                        item.status.value,
                        item.severity.value,
                        json.dumps(item.actual) if item.actual is not None else None,
                        json.dumps(item.expected) if item.expected is not None else None,
                        json.dumps(item.tolerance) if item.tolerance is not None else None,
                        json.dumps(item.evidence),
                        item.reason,
                    ],
                )
        row = self.store.query_one(
            "SELECT created_at FROM quality_report WHERE report_id=?", [report_id]
        )
        return QualityReport(
            report_id=report_id,
            dataset_id=dataset_id,
            rule_version=self.rule_version,
            result="FAIL" if failed else "PASS",
            fingerprint=fingerprint,
            created_at=row["created_at"],
            checks=checks,
        )
