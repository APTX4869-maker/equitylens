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
    dataset_id = DatasetBuilder(db).seal_rows(
        company_id=company_id,
        profile_id=profile_id,
        source_manifest={"documents": []},
        rows=[
            (
                "canonical_fact",
                f"revenue-{profile_version}",
                {
                    "canonical_fact_id": f"revenue-{profile_version}",
                    "company_id": company_id,
                    "canonical_metric": "REVENUE",
                    "period_type": "FY",
                    "fiscal_year": 2025,
                    "value": 1_000.0,
                    "unit": "USD",
                    "status": "REPORTED",
                    "mapping_rule_id": "fixture",
                    "mapping_version": "v1",
                    "source_raw_fact_ids": [],
                },
            )
        ],
    )
    publication = publications.publish_dataset(
        company_id=company_id,
        dataset_id=dataset_id,
        profile_id=profile_id,
        quality_report_id=None,
        review_id=None,
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
