"""Segment fact extraction from iXBRL filing documents (M4).

Distinguishes, per the handoff:
- company-reported segment (StatementBusinessSegmentsAxis, kind=segment)
- product/service category (ProductOrServiceAxis, kind=product)
- geographic disclosure (kind=geo)

Missing profitability is recorded as NOT_DISCLOSED, never estimated by
copying total-company margins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any

import yaml

from equitylens.config import CONFIG_DIR
from equitylens.normalization.fiscal_periods import FiscalCalendar
from equitylens.normalization.ixbrl import IxbrlDocument

CONFIG_PATH = CONFIG_DIR / "mappings" / "segment_axes.yaml"

STATUS_DISCLOSED = "DISCLOSED"
STATUS_NOT_DISCLOSED = "NOT_DISCLOSED"


@dataclass(frozen=True)
class SegmentAxis:
    name: str
    kind: str  # segment | product | geo
    label: str
    members: dict  # member -> {label, aggregate?}


@dataclass(frozen=True)
class IssuerSegmentConfig:
    ticker: str
    axes: list[SegmentAxis]
    revenue_concept: str
    profit_concept: str | None

    def axis(self, name: str) -> SegmentAxis | None:
        return next((a for a in self.axes if a.name == name), None)

    def member_label(self, axis_name: str, member: str) -> str:
        axis = self.axis(axis_name)
        if axis and member in axis.members:
            return axis.members[member].get("label", member)
        return member


class SegmentConfigRegistry:
    def __init__(self, path: Path = CONFIG_PATH):
        raw = yaml.safe_load(Path(path).read_text())
        self.version = raw.get("version")
        self._issuers: dict[str, IssuerSegmentConfig] = {}
        for ticker, spec in raw["issuers"].items():
            axes = [
                SegmentAxis(
                    name=a["name"],
                    kind=a["kind"],
                    label=a.get("label", a["name"]),
                    members=a.get("members", {}),
                )
                for a in spec["axes"]
            ]
            self._issuers[ticker] = IssuerSegmentConfig(
                ticker=ticker,
                axes=axes,
                revenue_concept=spec["metrics"]["REVENUE"],
                profit_concept=spec.get("profit_concept"),
            )

    def get(self, ticker: str) -> IssuerSegmentConfig | None:
        return self._issuers.get(ticker.upper())


def segment_config_from_profile(profile: Any) -> IssuerSegmentConfig:
    """Build the declarative segment parser config from a reviewed v2 profile."""
    if profile.schema_version != 2 or profile.segments.parser != "ixbrl_segments_v1":
        raise ValueError("profile does not declare the supported iXBRL segment parser")
    return IssuerSegmentConfig(
        ticker=profile.securities[0].ticker,
        axes=[
            SegmentAxis(
                name=axis.name,
                kind=axis.kind,
                label=axis.label,
                members={
                    name: member.model_dump(mode="json")
                    for name, member in axis.members.items()
                },
            )
            for axis in profile.segments.axes
        ],
        revenue_concept=profile.segments.revenue_concept,
        profit_concept=profile.segments.profit_concept,
    )


def extract_segments(
    ticker: str,
    ixbrl: IxbrlDocument,
    config: IssuerSegmentConfig,
    calendar: FiscalCalendar,
    source_document_id: str,
) -> tuple[list[dict], list[str]]:
    """Extract segment_fact rows from one filing document.

    Returns (rows, warnings). Rows carry the same shape as the segment_fact
    table; the caller persists them.
    """
    rows: list[dict] = []
    warnings: list[str] = []

    def resolve_period(fact) -> tuple[int | None, int | None, str, str | None, str | None] | None:
        """(fiscal_year, fiscal_quarter, period_type, period_start, period_end)."""
        if fact.instant:
            p = calendar.resolve_instant(fact.instant)
            return p.fiscal_year, p.fiscal_quarter, "INSTANT", None, fact.instant
        if fact.period_start and fact.period_end:
            p = calendar.resolve_duration(fact.period_start, fact.period_end)
            if p.period_type == "UNKNOWN":
                return None
            return p.fiscal_year, p.fiscal_quarter, p.period_type, fact.period_start, fact.period_end
        return None

    seen: set[tuple] = set()

    def add(axis_name: str, member: str, metric: str, concept: str, fact, kind: str, label: str) -> None:
        per = resolve_period(fact)
        if per is None or fact.value is None:
            return
        fy, fq, ptype, start, end = per
        key = (axis_name, member, metric, fy, fq, ptype, fact.value)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "segment_fact_id": f"sf_{hashlib.sha256(source_document_id.encode()).hexdigest()[:12]}_{axis_name}_{member}_{metric}_{fy}_{fq or 'fy'}_{ptype}_{len(rows)}",
                "company_id": None,  # caller fills
                "segment_name_reported": member,
                "segment_name_canonical": label,
                "segment_kind": kind,
                "disclosure_level": kind,
                "metric_name": metric,
                "fiscal_year": fy,
                "fiscal_quarter": fq,
                "period_type": ptype,
                "period_start": start,
                "period_end": end,
                "value": fact.value,
                "unit": "USD",
                "status": STATUS_DISCLOSED,
                "source_raw_fact_ids": "[]",
                "source_document_id": source_document_id,
                "disclosure_level": kind,
            }
        )

    for axis in config.axes:
        # revenue
        for fact in ixbrl.facts_for(config.revenue_concept, axis.name):
            member = fact.axis_members.get(axis.name)
            if not member or member not in axis.members:
                continue
            if axis.members[member].get("aggregate"):
                continue  # keep out of the mix view (hardware total etc.)
            add(axis.name, member, "REVENUE", config.revenue_concept, fact, axis.kind,
                config.member_label(axis.name, member))
        # profit (only when the issuer discloses it)
        if config.profit_concept:
            for fact in ixbrl.facts_for(config.profit_concept, axis.name):
                member = fact.axis_members.get(axis.name)
                if not member or member not in axis.members:
                    continue
                if axis.members[member].get("aggregate"):
                    continue
                add(axis.name, member, "OPERATING_INCOME", config.profit_concept, fact, axis.kind,
                    config.member_label(axis.name, member))

    return rows, warnings
