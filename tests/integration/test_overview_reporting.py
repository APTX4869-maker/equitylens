from datetime import datetime, timezone

import pytest

from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository
from tests.integration.test_onboarding_api import _client


@pytest.mark.parametrize("annual,persisted", [(True, False), (True, True), (False, False)], ids=["annual-q4", "persisted-q4", "quarter-gap"])
def test_overview_separates_published_report_from_calculable_quarters(db, monkeypatch, annual, persisted):
    client, _ = _client(db, monkeypatch)
    company = "0000320193"
    repo = PublicationRepository(db)
    profile = repo.create_profile(company, version=401, schema_version=1, content={"version": 401})
    end = "2026-12-31" if annual else "2026-09-30"
    rows = []
    for doc_id, report_date, filed_at, form in [
        ("report", end, "2027-02-01" if annual else "2026-11-01", "10-K" if annual else "10-Q"),
        ("old-amendment", "2025-12-31", "2027-03-01", "10-K/A"),
    ]:
        rows.append(("source_document", doc_id, {
            "source_document_id": doc_id, "company_id": company, "provider": "SEC",
            "document_type": "FILING_DOCUMENT", "form_type": form,
            "report_date": report_date, "filed_at": filed_at,
            "source_url": f"https://www.sec.gov/Archives/{doc_id}",
            "fetched_at": datetime.now(timezone.utc).isoformat(), "content_sha256": "a" * 64,
        }))
    # Revenue is complete through Q3 for the annual case, only Q2 for the gap.
    for quarter in range(1, 4 if annual else 3):
        rows.append(("canonical_fact", f"revenue-q{quarter}", {
            "canonical_fact_id": f"revenue-q{quarter}", "company_id": company,
            "canonical_metric": "REVENUE", "period_type": "Q_STANDALONE",
            "fiscal_year": 2026, "fiscal_quarter": quarter,
            "period_start": f"2026-{quarter * 3 - 2:02d}-01",
            "period_end": f"2026-{quarter * 3:02d}-30", "value": quarter * 10,
            "unit": "USD", "status": "REPORTED", "mapping_rule_id": "fixture",
            "mapping_version": "v1", "source_raw_fact_ids": [],
        }))
    if annual:
        rows.append(("canonical_fact", "revenue-ytd9", {
            "canonical_fact_id": "revenue-ytd9", "company_id": company,
            "canonical_metric": "REVENUE", "period_type": "YTD_9M",
            "fiscal_year": 2026, "fiscal_quarter": 3, "period_start": "2026-01-01",
            "period_end": "2026-09-30", "value": 60, "unit": "USD", "status": "REPORTED",
            "mapping_rule_id": "fixture", "mapping_version": "v1", "source_raw_fact_ids": [],
        }))
    rows.append(("canonical_fact", "report-fact", {
        "canonical_fact_id": "report-fact", "company_id": company,
        "canonical_metric": "REVENUE" if annual else "NET_INCOME",
        "period_type": "FY" if annual else "Q_STANDALONE",
        "fiscal_year": 2026, "fiscal_quarter": None if annual else 3,
        "period_start": "2026-01-01" if annual else "2026-07-01",
        "period_end": end, "value": 100 if annual else 5,
        "unit": "USD", "status": "REPORTED", "mapping_rule_id": "fixture",
        "mapping_version": "v1", "source_raw_fact_ids": [],
    }))
    if persisted:
        rows.append(("canonical_fact", "persisted-q4", {
            "canonical_fact_id": "persisted-q4", "company_id": company,
            "canonical_metric": "REVENUE", "period_type": "Q_STANDALONE",
            "fiscal_year": 2026, "fiscal_quarter": 4, "period_start": "2026-10-01",
            "period_end": end, "value": 40, "unit": "USD", "status": "CALCULATED",
            "mapping_rule_id": "standalone_quarter.ytd_diff.v1", "mapping_version": "v1",
            "source_raw_fact_ids": [],
        }))
    dataset = DatasetBuilder(db).seal_rows(company_id=company, profile_id=profile,
                                         source_manifest={"documents": []}, rows=rows)
    publication = repo.publish_dataset(company_id=company, dataset_id=dataset, profile_id=profile,
                                       quality_report_id=None, review_id=None)
    response = client.get("/api/v1/companies/AAPL/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["publication_id"] == publication.publication_id
    assert data["latest_period"]["fiscal_quarter"] == (4 if annual else 3)
    reporting = data["reporting"]
    assert reporting["latest_report"]["source_document_id"] == "report"
    assert reporting["latest_report"]["report_date"] == end
    assert reporting["latest_report"]["fiscal_year"] == 2026
    assert reporting["latest_report"]["fiscal_quarter"] == (4 if annual else 3)
    assert {"OPERATING_CASH_FLOW_LATEST", "CAPITAL_EXPENDITURES_LATEST"} <= {g["key"] for g in reporting["gaps"]}
    if annual:
        assert data["kpis"]["REVENUE_LATEST"]["value"] == 40
        assert data["kpis"]["REVENUE_LATEST"]["period"] == "FY2026Q4"
        assert reporting["derived_q4_metrics"] == ["REVENUE"]
        assert not any(gap["key"] == "REVENUE_LATEST" for gap in reporting["gaps"])
    else:
        assert data["kpis"]["REVENUE_LATEST"]["period"] == "FY2026Q2"
        gap = next(g for g in reporting["gaps"] if g["key"] == "REVENUE_LATEST")
        assert gap["available_period"] == "FY2026Q2"
        assert gap["target_period"] == "FY2026Q3"
        assert "当前发布" in gap["reason"]
    newer_doc = {**rows[0][2], "source_document_id": "newer-report", "report_date": "2027-12-31", "filed_at": "2028-02-01", "form_type": "10-K"}
    newer_fact = {**next(row[2] for row in rows if row[1] == "report-fact"),
                  "canonical_fact_id": "newer-fact", "canonical_metric": "REVENUE", "period_type": "FY",
                  "fiscal_year": 2027, "fiscal_quarter": None, "period_start": "2027-01-01", "period_end": "2027-12-31"}
    newer_dataset = DatasetBuilder(db).seal_rows(company_id=company, profile_id=profile,
        source_manifest={"documents": []}, rows=[("source_document", "newer-report", newer_doc), ("canonical_fact", "newer-fact", newer_fact)])
    repo.publish_dataset(company_id=company, dataset_id=newer_dataset, profile_id=profile,
                         quality_report_id=None, review_id=None)
    current = client.get("/api/v1/companies/AAPL/overview")
    assert current.status_code == 200
    assert current.json()["reporting"]["latest_report"]["report_date"] == "2027-12-31"
    historical = client.get("/api/v1/companies/AAPL/overview", params={"publication_id": publication.publication_id})
    assert historical.status_code == 200
    assert historical.json()["reporting"] == reporting
