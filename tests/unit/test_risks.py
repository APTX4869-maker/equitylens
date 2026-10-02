from __future__ import annotations

from types import SimpleNamespace


def _fact(fact_id: str, company_id: str, metric: str, year: int, value: float) -> dict:
    return {
        "canonical_fact_id": fact_id,
        "company_id": company_id,
        "canonical_metric": metric,
        "period_type": "FY",
        "fiscal_year": year,
        "fiscal_quarter": None,
        "period_start": f"{year}-01-01",
        "period_end": f"{year}-12-31",
        "instant_date": None,
        "value": value,
        "unit": "shares" if metric == "DILUTED_WEIGHTED_AVG_SHARES" else "USD",
        "status": "REPORTED",
        "mapping_rule_id": "fixture",
        "mapping_version": "v1",
        "source_raw_fact_ids": "[]",
        "as_known_at": f"{year + 1}-02-01T00:00:00",
        "created_at": f"{year + 1}-02-01T00:00:00",
        "warnings_json": "[]",
        "source_document_id": None,
    }


def test_missing_segment_evidence_is_not_a_completed_risk_check(db):
    from equitylens.domain.risks import risk_signals

    result = risk_signals(db, "0000000992", "NOSEG")
    concentration = next(
        check for check in result["checks"] if check["key"] == "concentration"
    )

    assert concentration["status"] == "EVIDENCE_GAP"
    assert concentration["reason"]
    assert concentration["next_evidence"]
    assert result["coverage"]["complete"] is False


def test_missing_evidence_comparison_period_is_incomplete_not_a_growth_verdict(db):
    from equitylens.domain.risks import risk_signals

    result = risk_signals(db, "0000000995", "NOHISTORY")
    growth = next(check for check in result["checks"] if check["key"] == "growth")

    assert growth["status"] == "INCOMPLETE_PERIOD"
    assert not any(
        risk["title"] in {"收入增速明显放缓", "增长动能偏弱"}
        for risk in result["risks"]
    )


def test_negative_base_and_zero_base_are_not_reported_as_growth(db):
    from equitylens.metrics.engine import MetricEngine

    for suffix, base in (("negative", -100.0), ("zero", 0.0)):
        company_id = f"0000000993-{suffix}"
        db._insert_many("canonical_fact", [
            _fact(f"{suffix}-base", company_id, "REVENUE", 2024, base),
            _fact(f"{suffix}-current", company_id, "REVENUE", 2025, 50.0),
        ])

        point = MetricEngine(db).compute(
            "REVENUE_GROWTH_YOY", company_id, frequency="annual"
        )[0]

        assert point.value is None
        assert point.status == "INCOMPARABLE_BASE"
        assert "positive" in (point.missing_reason or "").lower()


def test_stock_split_like_share_jump_is_unverified_corporate_action_not_dilution(db):
    from equitylens.api.routes import _management_watch_items
    from equitylens.domain.management_score import capital_allocation

    company_id = "0000000994"
    db._insert_many("canonical_fact", [
        _fact("shares-before-split", company_id, "DILUTED_WEIGHTED_AVG_SHARES", 2020, 100.0),
        _fact("shares-after-split", company_id, "DILUTED_WEIGHTED_AVG_SHARES", 2025, 400.0),
    ])

    allocation = capital_allocation(db, company_id)
    watch_items = _management_watch_items("SPLT", allocation, {
        "overall_score": 50.0, "coverage": 1.0, "minimum_coverage": 0.7,
    })

    assert allocation["summary"]["share_count_change_status"] == "EVIDENCE_GAP"
    assert allocation["summary"]["share_count_5y_change"] is None
    assert not any(item["topic"] == "股本净增长" for item in watch_items)


def test_nonpositive_operating_cash_flow_is_not_a_completed_cash_check(db):
    from equitylens.domain.risks import risk_signals

    class Engine:
        def compute(self, *_args, **_kwargs):
            return []

        def current(self, metric, *_args, **_kwargs):
            value = -10.0 if metric == "OPERATING_CASH_FLOW" else 2.0
            return SimpleNamespace(
                status="OK", missing_reason=None, value=value,
                input_fact_ids=[f"{metric}-fact"],
            )

    context = SimpleNamespace(
        metric_engine=Engine(), security_id="security-test",
        publication_id="publication-test",
        segments=lambda **_kwargs: {
            "segments": [], "total_revenue": None, "profit_disclosed": False,
        },
    )

    result = risk_signals(db, "0000000996", "NEGOCF", context=context)
    cash = next(check for check in result["checks"] if check["key"] == "cash_flow")

    assert cash["status"] == "INCOMPARABLE_BASE"
    assert cash["reason"]
    assert cash["next_evidence"]
