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
    eps_reconciliation,
    evidence_required,
    required_period_coverage,
    segment_reconciliation,
)
from equitylens.storage.raw_store import sha256_bytes
from equitylens.storage.writer import writer_for


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
        for module, claim in (profile.get("applicability") or {}).items():
            status = {
                "not_applicable": CheckStatus.NOT_APPLICABLE,
                "not_disclosed": CheckStatus.NOT_DISCLOSED,
            }.get(claim)
            if status:
                checks.append(
                    evidence_required(
                        check_id=f"{module}.applicability",
                        claimed_status=status,
                        evidence=evidence,
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

        def value(metric):
            item = latest.get(metric)
            return item.get("value") if item else None

        balance_values = [value("TOTAL_ASSETS"), value("TOTAL_LIABILITIES"), value("STOCKHOLDERS_EQUITY")]
        if all(item is not None for item in balance_values):
            checks.append(
                balance_equation(
                    assets=balance_values[0],
                    liabilities=balance_values[1],
                    equity=balance_values[2],
                    mezzanine=value("MEZZANINE_EQUITY") or 0,
                    decimals=latest["TOTAL_ASSETS"].get("decimals", 0),
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

        cash_names = (
            "CASH_BEGINNING",
            "OPERATING_CASH_FLOW",
            "INVESTING_CASH_FLOW",
            "FINANCING_CASH_FLOW",
            "FX_EFFECT_ON_CASH",
            "CASH_ENDING",
        )
        cash_values = [value(name) for name in cash_names]
        if all(item is not None for item in cash_values):
            checks.append(
                cash_bridge(
                    opening=cash_values[0],
                    operating=cash_values[1],
                    investing=cash_values[2],
                    financing=cash_values[3],
                    fx=cash_values[4],
                    closing=cash_values[5],
                    other=value("OTHER_CASH_CHANGE") or 0,
                    decimals=latest["CASH_ENDING"].get("decimals", 0),
                )
            )
        else:
            checks.append(
                CheckResult(
                    check_id="CASH.bridge",
                    status=CheckStatus.FAIL,
                    actual={"missing": [name for name, item in zip(cash_names, cash_values) if item is None]},
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
        segment_revenue = [
            item for item in segments
            if item.get("metric_name") == "REVENUE" and not item.get("aggregate")
        ]
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
            checks.append(
                evidence_required(
                    check_id="SEGMENTS.reconciliation",
                    claimed_status=status,
                    evidence=evidence if status == CheckStatus.NOT_DISCLOSED else [],
                )
            )

        raw_concepts = {item.get("concept") for item in parsed.get("raw_fact", [])}
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
        security_ok = bool(profile.get("securities")) and bool(
            self.store.query_one(
                "SELECT security_id FROM security WHERE company_id=? LIMIT 1",
                [dataset["company_id"]],
            )
        )
        checks.append(
            CheckResult(
                check_id="SECURITY.identity",
                status=CheckStatus.PASS if security_ok else CheckStatus.FAIL,
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
