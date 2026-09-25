"""Inline XBRL (iXBRL) parser.

Extracts dimensional facts from SEC filing documents (10-K/10-Q HTML).
The handoff's Phase 4 requirement: dimensional segment facts are NOT in
`companyfacts`; they must be read directly from the filing's inline XBRL.

Fact semantics per the Inline XBRL spec:
  raw value = float(displayed text) * 10 ** scale
  `decimals` expresses the rounding precision (e.g. -6 = millions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from lxml import etree

IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
XBRLI_NS = "http://www.xbrl.org/2003/instance"
XBRLDI_NS = "http://xbrl.org/2006/xbrldi"
NS = {
    "ix": IX_NS,
    "xbrli": XBRLI_NS,
    "xbrldi": XBRLDI_NS,
}


@dataclass
class IxbrlFact:
    name: str  # full prefixed name, e.g. us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax
    context_ref: str
    unit_ref: str | None
    text: str | None
    scale: int = 0
    sign: int = 1
    decimals: str | None = None
    dims: list[tuple[str, str]] = field(default_factory=list)  # [(dimension, member)] full names
    period_start: str | None = None
    period_end: str | None = None
    instant: str | None = None
    locator: str = ""

    @property
    def value(self) -> float | None:
        if self.text is None:
            return None
        try:
            return self.sign * float(self.text.replace(",", "").strip()) * (10 ** self.scale)
        except ValueError:
            return None

    @property
    def axis_members(self) -> dict[str, str]:
        """dimension-short-name -> member-short-name."""
        return {d.split(":")[-1]: m.split(":")[-1] for d, m in self.dims}


class IxbrlDocument:
    def __init__(self, root: etree._Element):
        self.root = root
        self._contexts: dict[str, dict] = {}
        self._parse_contexts()

    @classmethod
    def parse(cls, content: bytes) -> "IxbrlDocument":
        parser = etree.XMLParser(recover=True, huge_tree=True)
        root = etree.fromstring(content, parser)
        return cls(root)

    def _parse_contexts(self) -> None:
        for c in self.root.findall(".//xbrli:context", NS):
            cid = c.get("id")
            if not cid:
                continue
            dims = []
            for em in c.findall(".//xbrldi:explicitMember", NS):
                dim = em.get("dimension")
                if dim and em.text:
                    dims.append((dim, em.text))
            self._contexts[cid] = {
                "period_start": c.findtext(".//xbrli:startDate", namespaces=NS),
                "period_end": c.findtext(".//xbrli:endDate", namespaces=NS),
                "instant": c.findtext(".//xbrli:instant", namespaces=NS),
                "dims": dims,
            }

    def facts(self, name: str) -> list[IxbrlFact]:
        """All numeric facts with the exact prefixed concept name."""
        out: list[IxbrlFact] = []
        for el in self.root.findall(f".//ix:nonFraction[@name='{name}']", NS):
            cref = el.get("contextRef")
            ctx = self._contexts.get(cref, {})
            scale = el.get("scale")
            try:
                scale_int = int(scale) if scale else 0
            except ValueError:
                scale_int = 0
            out.append(
                IxbrlFact(
                    name=name,
                    context_ref=cref,
                    unit_ref=el.get("unitRef"),
                    text=el.text,
                    scale=scale_int,
                    sign=-1 if el.get("sign") == "-" else 1,
                    decimals=el.get("decimals"),
                    dims=ctx.get("dims", []),
                    period_start=ctx.get("period_start"),
                    period_end=ctx.get("period_end"),
                    instant=ctx.get("instant"),
                    locator=self.root.getroottree().getpath(el),
                )
            )
        return out

    def facts_for(self, concept: str, axis: str) -> list[IxbrlFact]:
        """Facts of `concept` that carry an explicit member on `axis`."""
        return [f for f in self.facts(concept) if axis in f.axis_members]

    def fact_catalog(self) -> list[dict]:
        """Evidence locators available for issuer-profile candidate generation."""
        out = []
        for el in self.root.findall(".//ix:nonFraction", NS):
            name = el.get("name")
            context_ref = el.get("contextRef")
            if not name or not context_ref:
                continue
            out.append(
                {
                    "concept": name,
                    "context_ref": context_ref,
                    "unit_ref": el.get("unitRef"),
                    "decimals": el.get("decimals"),
                    "locator": self.root.getroottree().getpath(el),
                }
            )
        return out


def normalize_profiled_ixbrl(
    document: IxbrlDocument,
    *,
    profile: Any,
    mappings: Any,
    calendar: Any,
    source_document_id: str,
    company_id: str,
    accession_number: str,
    form_type: str,
    filed_at: str,
):
    """Normalize only reviewed profile concepts from a fixed iXBRL document."""
    from equitylens.normalization.normalize import normalize_companyfacts

    facts: dict[str, dict] = {}
    evidence: dict[tuple, IxbrlFact] = {}
    for metric in profile.metrics.values():
        for qualified_name in metric.concepts:
            taxonomy, concept = qualified_name.split(":", 1)
            for fact in document.facts(qualified_name):
                if fact.value is None or fact.dims:
                    continue
                entry = {
                    "start": fact.period_start,
                    "end": fact.period_end or fact.instant,
                    "val": fact.value,
                    "accn": accession_number,
                    "form": form_type,
                    "filed": filed_at,
                }
                unit = fact.unit_ref or metric.unit
                facts.setdefault(taxonomy, {}).setdefault(concept, {}).setdefault(
                    "units", {}
                ).setdefault(unit, []).append(entry)
                evidence[(concept, unit, entry["start"], entry["end"], entry["val"])] = fact
    raw, canonical, result = normalize_companyfacts(
        {"facts": facts}, mappings, calendar, source_document_id, company_id
    )
    for row in raw:
        fact = evidence.get(
            (
                row["concept"],
                row["unit"],
                row.get("start_date"),
                row.get("end_date") or row.get("instant_date"),
                row.get("raw_value"),
            )
        )
        if fact is None:
            continue
        row["context_id"] = fact.context_ref
        row["locator"] = fact.locator
        row["dimensions_json"] = json.dumps(fact.dims, ensure_ascii=False)
    return raw, canonical, result
