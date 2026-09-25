"""Golden tests for segment extraction (M4) — vs official 10-K/10-Q figures.

Fixtures: the extracted filing documents live under tests/fixtures/sec/{cik}/filing_docs/
and are re-parsed by the segment pipeline (same code path as production).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from equitylens.domain.companies import get_company
from equitylens.ingestion.sec.filing_docs import fetch_filing_documents
from equitylens.normalization.fiscal_periods import FiscalCalendar
from equitylens.normalization.ixbrl import IxbrlDocument
from equitylens.normalization.segments import SegmentConfigRegistry, extract_segments

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(scope="session")
def segment_rows(tmp_path_factory):
    """Re-extract segments from the fixture filing documents into memory."""
    registry = SegmentConfigRegistry()
    out: dict[str, list[dict]] = {"AAPL": [], "MSFT": []}
    for ticker in ("AAPL", "MSFT"):
        company = get_company(ticker)
        cik = company.cik
        subs = json.loads((FIXTURE_ROOT / "sec" / cik / "submissions.json").read_text())
        calendar = FiscalCalendar.from_submissions(subs, fallback_mm_dd=company.fiscal_year_end)
        config = registry.get(ticker)
        docs_dir = FIXTURE_ROOT / "sec" / cik / "filing_docs"
        for accn_dir in sorted(docs_dir.iterdir()) if docs_dir.exists() else []:
            primary = accn_dir / "primary.html"
            if not primary.exists():
                continue
            ixbrl = IxbrlDocument.parse(primary.read_bytes())
            rows, _ = extract_segments(ticker, ixbrl, config, calendar, f"src_fixture_{accn_dir.name}")
            for r in rows:
                r["company_id"] = cik
            out[ticker].extend(rows)
    return out


def _latest_fy(rows: list[dict], name: str, metric: str, fy: int) -> float:
    cands = [
        r for r in rows
        if r["segment_name_canonical"] == name and r["metric_name"] == metric
        and r["fiscal_year"] == fy and r["period_type"] == "FY"
    ]
    assert cands, f"no FY{fy} {metric} for {name}"
    return max(cands, key=lambda r: r.get("segment_fact_id"))["value"]


def test_aapl_segment_revenue_sum_matches_total(segment_rows):
    """AAPL FY2025 five reportable segments sum to total revenue (416,161M)."""
    rows = segment_rows["AAPL"]
    fy2025 = [r for r in rows if r["fiscal_year"] == 2025 and r["period_type"] == "FY"
              and r["metric_name"] == "REVENUE" and r["segment_kind"] == "segment"]
    assert len(fy2025) >= 5
    total = sum(r["value"] for r in fy2025)
    assert total == pytest.approx(416_161_000_000, rel=1e-6)


def test_aapl_segment_values_match_official_10k(segment_rows):
    """Spot-check official 10-K figures (FY2025)."""
    rows = segment_rows["AAPL"]
    assert _latest_fy(rows, "美洲", "REVENUE", 2025) == pytest.approx(178_353_000_000, rel=1e-9)
    assert _latest_fy(rows, "欧洲", "REVENUE", 2025) == pytest.approx(111_032_000_000, rel=1e-9)
    assert _latest_fy(rows, "大中华区", "REVENUE", 2025) == pytest.approx(64_377_000_000, rel=1e-9)
    assert _latest_fy(rows, "日本", "REVENUE", 2025) == pytest.approx(28_703_000_000, rel=1e-9)


def test_aapl_product_categories_match_official_10k(segment_rows):
    rows = segment_rows["AAPL"]
    assert _latest_fy(rows, "iPhone", "REVENUE", 2025) == pytest.approx(209_586_000_000, rel=1e-9)
    assert _latest_fy(rows, "服务", "REVENUE", 2025) == pytest.approx(109_158_000_000, rel=1e-9)
    assert _latest_fy(rows, "Mac", "REVENUE", 2025) == pytest.approx(33_708_000_000, rel=1e-9)
    assert _latest_fy(rows, "iPad", "REVENUE", 2025) == pytest.approx(28_023_000_000, rel=1e-9)


def test_aapl_does_not_disclose_segment_profit(segment_rows):
    """Apple has no segment operating income facts: NOT_DISCLOSED, never estimated."""
    rows = segment_rows["AAPL"]
    profit = [r for r in rows if r["metric_name"] == "OPERATING_INCOME"]
    assert profit == [], "Apple must not have segment profit facts"


def test_msft_segment_revenue_and_profit(segment_rows):
    rows = segment_rows["MSFT"]
    # FY2026 (from the FY2026 10-K)
    assert _latest_fy(rows, "智能云", "REVENUE", 2026) == pytest.approx(137_791_000_000, rel=1e-9)
    assert _latest_fy(rows, "生产力与业务流程", "REVENUE", 2026) == pytest.approx(139_996_000_000, rel=1e-9)
    assert _latest_fy(rows, "更多个人计算", "REVENUE", 2026) == pytest.approx(54_052_000_000, rel=1e-9)
    # segment operating income IS disclosed for MSFT
    assert _latest_fy(rows, "智能云", "OPERATING_INCOME", 2026) == pytest.approx(56_972_000_000, rel=1e-9)
    assert _latest_fy(rows, "生产力与业务流程", "OPERATING_INCOME", 2026) == pytest.approx(83_879_000_000, rel=1e-9)


def test_msft_segments_sum_to_total(segment_rows):
    rows = segment_rows["MSFT"]
    fy2026 = [r for r in rows if r["fiscal_year"] == 2026 and r["period_type"] == "FY"
              and r["metric_name"] == "REVENUE" and r["segment_kind"] == "segment"]
    total = sum(r["value"] for r in fy2026)
    assert total == pytest.approx(331_839_000_000, rel=1e-9)


def test_aapl_quarterly_segment_from_10q(segment_rows):
    """FY2026 Q3 standalone segment revenue from the Q3 10-Q."""
    rows = segment_rows["AAPL"]
    q3 = [
        r for r in rows
        if r["fiscal_year"] == 2026 and r["fiscal_quarter"] == 3
        and r["period_type"] == "Q_STANDALONE" and r["metric_name"] == "REVENUE"
        and r["segment_kind"] == "segment"
    ]
    by_name = {r["segment_name_canonical"]: r["value"] for r in q3}
    assert by_name.get("美洲") == pytest.approx(45_781_000_000, rel=1e-9)
    assert by_name.get("欧洲") == pytest.approx(29_395_000_000, rel=1e-9)
    assert by_name.get("大中华区") == pytest.approx(18_816_000_000, rel=1e-9)
