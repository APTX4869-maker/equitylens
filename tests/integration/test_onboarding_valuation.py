from __future__ import annotations

from fastapi.testclient import TestClient

from equitylens.api.main import app
from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository
from equitylens.valuation.dcf import MODEL_VERSION


ASSUMPTIONS = {
    "revenue_base": 1_000.0,
    "revenue_growth": [0.08, 0.07, 0.06, 0.05, 0.04],
    "op_margin_start": 0.20,
    "op_margin_end": 0.22,
    "tax_rate": 0.21,
    "da_pct": 0.03,
    "capex_pct": 0.05,
    "nwc_pct": 0.01,
    "wacc": 0.09,
    "terminal_growth": 0.025,
    "net_cash": 100.0,
    "shares": 10.0,
    "share_basis_label": "verified security diluted shares",
    "terminal_roic": 0.20,
}


def _install_company(
    db,
    *,
    company_id="0000000004",
    ticker="NEWCO",
    security_id="security-newco",
    currency="USD",
    instrument_type="COMMON_STOCK",
    evidence=None,
    profile_version=401,
    complete_valuation_facts=False,
):
    registry = CompanyRegistry(db)
    registry.register_company(
        CompanyIdentity(
            company_id=company_id,
            cik=company_id,
            legal_name=f"{ticker} Inc.",
            reporting_template="us_gaap_operating_v1",
            quality_status="PASS",
        ),
        legacy_ticker=ticker,
    )
    registry.register_security(
        SecurityIdentity(
            security_id=security_id,
            company_id=company_id,
            ticker=ticker,
            exchange="NYSE",
            currency=currency,
            instrument_type=instrument_type,
            identity_evidence=evidence or {"verified": True},
        )
    )
    publications = PublicationRepository(db)
    profile_id = publications.create_profile(
        company_id,
        version=profile_version,
        schema_version=1,
        content={"company_id": company_id, "version": profile_version},
    )
    facts = [
        ("REVENUE", 1_000.0, "USD", "FY", None),
    ]
    if complete_valuation_facts:
        facts.extend([
            ("OPERATING_INCOME", 200.0, "USD", "FY", None),
            ("PRETAX_INCOME", 180.0, "USD", "FY", None),
            ("INCOME_TAX_EXPENSE", 36.0, "USD", "FY", None),
            ("CAPITAL_EXPENDITURES", 50.0, "USD", "FY", None),
            ("DEPRECIATION_AMORTIZATION", 30.0, "USD", "FY", None),
            ("DILUTED_WEIGHTED_AVG_SHARES", 10.0, "shares", "FY", None),
            ("LONG_TERM_DEBT", 100.0, "USD", "INSTANT", "2025-12-31"),
            ("LONG_TERM_DEBT_CURRENT", 0.0, "USD", "INSTANT", "2025-12-31"),
            ("CASH_AND_EQUIVALENTS", 200.0, "USD", "INSTANT", "2025-12-31"),
            ("SHORT_TERM_INVESTMENTS", 0.0, "USD", "INSTANT", "2025-12-31"),
        ])
    rows = []
    for metric, value, unit, period_type, instant_date in facts:
        fact_id = f"{metric.lower()}-{profile_version}"
        rows.append((
            "canonical_fact",
            fact_id,
            {
                "canonical_fact_id": fact_id,
                "company_id": company_id,
                "canonical_metric": metric,
                "period_type": period_type,
                "fiscal_year": 2025,
                "period_end": "2025-12-31",
                "instant_date": instant_date,
                "value": value,
                "unit": unit,
                "status": "REPORTED",
                "mapping_rule_id": "fixture",
                "mapping_version": "v1",
                "source_raw_fact_ids": [],
            },
        ))
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": []},
        rows=rows,
    )
    publication = publications.publish_dataset(
        company_id=company_id,
        dataset_id=dataset_id,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
    )
    if complete_valuation_facts:
        for _, _, payload in rows:
            db._conn.execute(
                """
                INSERT INTO canonical_fact (
                  canonical_fact_id, company_id, canonical_metric, period_type,
                  fiscal_year, fiscal_quarter, period_start, period_end, instant_date,
                  value, unit, status, mapping_rule_id, mapping_version,
                  source_raw_fact_ids, as_known_at, created_at, warnings_json
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, '[]', now(), now(), '[]')
                """,
                [
                    payload["canonical_fact_id"], payload["company_id"],
                    payload["canonical_metric"], payload["period_type"],
                    payload["fiscal_year"],
                    "2025-01-01" if payload["period_type"] == "FY" else None,
                    payload["period_end"], payload["instant_date"], payload["value"],
                    payload["unit"], payload["status"], payload["mapping_rule_id"],
                    payload["mapping_version"],
                ],
            )
    return publication


def _client(db, monkeypatch):
    monkeypatch.setattr("equitylens.api.routes.DuckDBStore", lambda: db)
    return TestClient(app, raise_server_exceptions=False)


def _confirm(client, publication, **overrides):
    body = {
        "security_id": "security-newco",
        "publication_id": publication.publication_id,
        "model_version": MODEL_VERSION,
        "assumptions": ASSUMPTIONS,
        "confirmed": True,
    }
    body.update(overrides)
    return client.put("/api/v1/companies/NEWCO/valuation-profile", json=body)


def test_new_security_requires_confirmed_assumptions(db, monkeypatch):
    _install_company(db)
    client = _client(db, monkeypatch)

    response = client.get(
        "/api/v1/companies/NEWCO/valuation/default",
        params={"security_id": "security-newco"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VALUATION_NEEDS_CONFIGURATION"


def test_unconfirmed_company_can_load_identity_bound_draft(db, monkeypatch):
    publication = _install_company(
        db,
        ticker="AAPL",
        complete_valuation_facts=True,
    )
    client = _client(db, monkeypatch)
    before_sets = db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"]
    before_runs = db.query_one("SELECT count(*) AS n FROM valuation_run")["n"]

    response = client.get(
        "/api/v1/companies/AAPL/valuation-profile/draft",
        params={
            "security_id": "security-newco",
            "publication_id": publication.publication_id,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["security_id"] == "security-newco"
    assert body["publication_id"] == publication.publication_id
    assert body["model_version"] == MODEL_VERSION
    assert body["status"] == "NEEDS_CONFIGURATION"
    assert body["acknowledgement_required"] is True
    assert body["assumptions"]["inputs"]["shares"] > 0
    assert body["preview"]["scenarios"]["base"]["status"] == "OK"
    assert db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"] == before_sets
    assert db.query_one("SELECT count(*) AS n FROM valuation_run")["n"] == before_runs


def test_confirmation_rejects_draft_after_active_publication_changes(db, monkeypatch):
    publication = _install_company(
        db,
        ticker="AAPL",
        complete_valuation_facts=True,
    )
    client = _client(db, monkeypatch)
    draft = client.get(
        "/api/v1/companies/AAPL/valuation-profile/draft",
        params={
            "security_id": "security-newco",
            "publication_id": publication.publication_id,
        },
    ).json()
    _install_new_publication(db, publication.company_id, version=402)
    before = db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"]

    response = client.put(
        "/api/v1/companies/AAPL/valuation-profile",
        json={
            "security_id": draft["security_id"],
            "publication_id": draft["publication_id"],
            "model_version": draft["model_version"],
            "assumptions": draft["assumptions"]["inputs"],
            "confirmed": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VALUATION_DRAFT_STALE"
    assert db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"] == before


def test_confirmation_binds_security_publication_model_and_assumptions(db, monkeypatch):
    publication = _install_company(db)
    client = _client(db, monkeypatch)
    confirmed = _confirm(client, publication)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "READY"

    result = client.get(
        "/api/v1/companies/NEWCO/valuation/default",
        params={"security_id": "security-newco"},
    )
    assert result.status_code == 200
    assert result.json()["security_id"] == "security-newco"
    assert result.json()["publication_id"] == publication.publication_id
    assert result.json()["assumptions"]["inputs"] == ASSUMPTIONS
    reverse = client.post(
        "/api/v1/companies/NEWCO/valuation/reverse-dcf",
        params={"security_id": "security-newco"},
        json={"target_price": 100.0},
    )
    assert reverse.status_code == 200
    assert reverse.json()["security_id"] == "security-newco"

    newer = _install_new_publication(db, publication.company_id, version=402)
    stale = client.get(
        "/api/v1/companies/NEWCO/valuation/default",
        params={"security_id": "security-newco", "publication_id": newer.publication_id},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VALUATION_NEEDS_CONFIGURATION"


def _install_new_publication(db, company_id: str, *, version: int):
    publications = PublicationRepository(db)
    profile_id = publications.create_profile(
        company_id,
        version=version,
        schema_version=1,
        content={"company_id": company_id, "version": version},
    )
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": []},
        rows=[],
    )
    return publications.publish_dataset(
        company_id=company_id,
        dataset_id=dataset_id,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
    )


def test_currency_and_adr_identity_gates_cannot_be_confirmed(db, monkeypatch):
    eur = _install_company(
        db,
        company_id="0000000005",
        ticker="EUCO",
        security_id="security-euco",
        currency="EUR",
        profile_version=501,
    )
    adr = _install_company(
        db,
        company_id="0000000006",
        ticker="ADRCO",
        security_id="security-adrco",
        instrument_type="ADR",
        evidence={"verified": True},
        profile_version=601,
    )
    client = _client(db, monkeypatch)

    currency = client.put(
        "/api/v1/companies/EUCO/valuation-profile",
        json={
            "security_id": "security-euco",
            "publication_id": eur.publication_id,
            "model_version": MODEL_VERSION,
            "assumptions": ASSUMPTIONS,
            "confirmed": True,
        },
    )
    assert currency.status_code == 409
    assert currency.json()["error"]["code"] == "VALUATION_CURRENCY_MISMATCH"

    unknown_adr = client.put(
        "/api/v1/companies/ADRCO/valuation-profile",
        json={
            "security_id": "security-adrco",
            "publication_id": adr.publication_id,
            "model_version": MODEL_VERSION,
            "assumptions": ASSUMPTIONS,
            "confirmed": True,
        },
    )
    assert unknown_adr.status_code == 409
    assert unknown_adr.json()["error"]["code"] == "VALUATION_ADR_RATIO_UNKNOWN"


def test_quote_identity_is_separate_for_each_security(db, monkeypatch):
    publication = _install_company(db)
    CompanyRegistry(db).register_security(
        SecurityIdentity(
            security_id="security-newco-b",
            company_id=publication.company_id,
            ticker="NEWCO.B",
            exchange="NYSE",
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"verified": True},
        )
    )
    for quote_id, security_id, ticker, price in (
        ("quote-a", "security-newco", "NEWCO", 10.0),
        ("quote-b", "security-newco-b", "NEWCO.B", 20.0),
    ):
        db.insert_market_quote(
            {
                "quote_id": quote_id,
                "company_id": publication.company_id,
                "security_id": security_id,
                "ticker": ticker,
                "provider": "fixture",
                "observed_at": "2026-09-12 00:00:00",
                "price": price,
                "currency": "USD",
                "fetched_at": "2026-09-12 00:00:00",
            }
        )
    client = _client(db, monkeypatch)
    a = client.get(
        "/api/v1/companies/NEWCO/market/quote",
        params={"security_id": "security-newco"},
    )
    b = client.get(
        "/api/v1/companies/NEWCO.B/market/quote",
        params={"security_id": "security-newco-b"},
    )
    assert a.json()["quote"]["price"] == 10.0
    assert b.json()["quote"]["price"] == 20.0


def test_multiple_share_classes_require_security_level_share_basis(db, monkeypatch):
    publication = _install_company(db)
    CompanyRegistry(db).register_security(
        SecurityIdentity(
            security_id="security-newco-b",
            company_id=publication.company_id,
            ticker="NEWCO.B",
            exchange="NASDAQ",
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"verified": True},
        )
    )
    client = _client(db, monkeypatch)

    blocked = _confirm(client, publication)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "VALUATION_SHARE_BASIS_UNVERIFIED"

    scoped = _confirm(
        client,
        publication,
        assumptions={**ASSUMPTIONS, "share_basis_security_id": "security-newco"},
    )
    assert scoped.status_code == 200


def test_new_publication_marks_plan_for_review_without_mutating_old_run(db, monkeypatch):
    publication = _install_company(db)
    client = _client(db, monkeypatch)
    assert _confirm(client, publication).status_code == 200
    run = client.post(
        "/api/v1/companies/NEWCO/valuation/run",
        params={"security_id": "security-newco"},
        json={"persist": True},
    ).json()
    saved_before = db.query_one(
        "SELECT * FROM valuation_run WHERE valuation_run_id=?",
        [run["valuation_run_id"]],
    )
    plan = client.post(
        "/api/v1/companies/NEWCO/valuation/plans",
        json={
            "valuation_run_id": run["valuation_run_id"],
            "scenario_key": "base",
            "margin_of_safety": 0.2,
        },
    ).json()

    _install_new_publication(db, publication.company_id, version=403)
    saved_after = db.query_one(
        "SELECT * FROM valuation_run WHERE valuation_run_id=?",
        [run["valuation_run_id"]],
    )
    current_plan = client.get(
        f"/api/v1/companies/NEWCO/valuation/plans/{plan['plan_id']}"
    ).json()
    copied = client.post(
        f"/api/v1/companies/NEWCO/valuation/plans/{plan['plan_id']}/copy",
        json={"name": "copy after publication"},
    ).json()

    assert saved_after == saved_before
    assert current_plan["review_status"] == "needs_review"
    assert copied["review_status"] == "needs_review"
    assert copied["publication_id"] == publication.publication_id
