from __future__ import annotations


def _fact(fact_id: str, company_id: str, year: int, value: float) -> dict:
    return {
        "canonical_fact_id": fact_id,
        "company_id": company_id,
        "canonical_metric": "REVENUE",
        "period_type": "FY",
        "fiscal_year": year,
        "fiscal_quarter": None,
        "period_start": f"{year}-01-01",
        "period_end": f"{year}-12-31",
        "instant_date": None,
        "value": value,
        "unit": "USD",
        "status": "REPORTED",
        "mapping_rule_id": "fixture",
        "mapping_version": "v1",
        "source_raw_fact_ids": "[]",
        "as_known_at": f"{year + 1}-02-01T00:00:00",
        "created_at": f"{year + 1}-02-01T00:00:00",
        "warnings_json": "[]",
        "source_document_id": None,
    }


def test_period_alignment_reports_each_kpi_period_and_mismatch_reason():
    from equitylens.api.routes import _period_alignment

    result = _period_alignment({
        "TTM_REVENUE": {
            "value": 400, "period": "FY2026Q3", "period_end": "2026-09-30", "frequency": "ttm"
        },
        "OPERATING_MARGIN": {
            "value": 0.25, "period": "FY2026Q2", "period_end": "2026-06-30", "frequency": "quarterly"
        },
        "TTM_FCF": {
            "value": 80, "period": "FY2026Q1", "period_end": "2026-03-31", "frequency": "ttm"
        },
    })

    assert result["status"] == "mixed"
    assert result["reference_period_end"] == "2026-09-30"
    assert result["periods"]["OPERATING_MARGIN"]["period"] == "FY2026Q2"
    assert any("OPERATING_MARGIN" in item["reason"] for item in result["mismatches"])


def test_negative_base_growth_remains_non_comparable(db):
    from equitylens.metrics.engine import MetricEngine

    company_id = "0000000971"
    db._insert_many("canonical_fact", [
        _fact("period-negative-base", company_id, 2024, -10.0),
        _fact("period-positive-current", company_id, 2025, 20.0),
    ])

    point = MetricEngine(db).compute("REVENUE_GROWTH_YOY", company_id, "annual")[0]

    assert point.status == "INCOMPARABLE_BASE"
    assert point.value is None


def test_report_gap_does_not_call_a_null_result_period_an_available_value():
    from equitylens.api.routes import _reporting_metadata
    from equitylens.metrics.engine import MetricEngine

    result = _reporting_metadata([], [{
        "form_type": "10-Q", "report_date": "2026-06-30", "source_document_id": "report",
    }], {"TTM_FCF": {"value": None, "period": "FY2026Q2", "period_end": "2026-06-30"}},
        MetricEngine(None, published_facts=[]))
    gap = next(item for item in result["gaps"] if item["key"] == "TTM_FCF")
    assert gap["available_period"] is None
    assert gap["target_period"] == "2026-06-30"
