from __future__ import annotations

from types import SimpleNamespace


def test_negative_segment_revenue_base_is_not_directional_growth(monkeypatch):
    from equitylens.api.segments_service import get_segments

    monkeypatch.setattr(
        "equitylens.domain.companies.get_company",
        lambda _ticker, store=None: SimpleNamespace(cik="0000000997"),
    )
    rows = [
        {
            "segment_name_reported": "ExampleSegment",
            "segment_name_canonical": "Example",
            "segment_kind": "segment",
            "metric_name": "REVENUE",
            "fiscal_year": year,
            "fiscal_quarter": None,
            "period_type": "FY",
            "value": value,
            "status": "DISCLOSED",
            "source_raw_fact_ids": [],
            "source_document_id": f"source-{year}",
            "form_type": "10-K",
            "accession_number": str(year),
            "filed_at": f"{year}-12-31",
            "source_url": f"https://www.sec.gov/{year}",
        }
        for year, value in ((2024, -100.0), (2025, 50.0))
    ]

    result = get_segments(
        None,
        "TEST",
        published_rows=rows,
        published_config=SimpleNamespace(profit_concept=None),
    )
    segment = result["segments"][0]

    assert segment["growth_yoy"] is None
    assert segment["growth_status"] == "INCOMPARABLE_BASE"
    assert segment["growth_reason"]
