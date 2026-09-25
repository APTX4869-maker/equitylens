"""Cross-layer normalization counterexamples from the remediation handoff."""

from datetime import date

from equitylens.metrics.engine import MetricEngine
from equitylens.normalization.fiscal_periods import FiscalCalendar
from equitylens.normalization.normalize import normalize_companyfacts
from equitylens.normalization.taxonomy.mappings import MappingRegistry


def test_same_day_overlapping_revenue_concepts_are_order_independent():
    """D05: concept iteration order cannot change the one selected FY value."""
    entries = {
        "Revenues": (100.0, "accn-a"),
        "RevenueFromContractWithCustomerExcludingAssessedTax": (120.0, "accn-b"),
    }

    def normalize(order: list[str]):
        concepts = {}
        for concept in order:
            value, accn = entries[concept]
            concepts[concept] = {"units": {"USD": [{
                "start": "2024-07-01", "end": "2025-06-30", "val": value,
                "accn": accn, "fy": 2025, "fp": "FY", "form": "10-K",
                "filed": "2025-07-30",
            }]}}
        payload = {"facts": {"us-gaap": concepts}}
        calendar = FiscalCalendar(
            year_ends={2024: date(2024, 6, 30), 2025: date(2025, 6, 30)},
            quarter_ends={}, fallback_mm_dd="06-30",
        )
        _, canonical, result = normalize_companyfacts(
            payload, MappingRegistry(), calendar, "source-same-day", "TEST",
        )
        selected = MetricEngine._annual_series(canonical)
        assert result.facts_accepted == 2
        assert len(selected) == 1
        return selected[(2025, None)]

    forward = normalize(list(entries))
    reverse = normalize(list(reversed(entries)))
    assert forward["canonical_fact_id"] == reverse["canonical_fact_id"]
    assert forward["value"] == reverse["value"]
