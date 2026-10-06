from __future__ import annotations

import json

import pytest
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
    complete_valuation_facts=True,
    fact_currency="USD",
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
        ("REVENUE", 1_000.0, fact_currency, "FY", None),
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
    from equitylens.valuation.defaults import _load_wacc_config

    config = json.loads(json.dumps(_load_wacc_config()))
    config["issuers"]["NEWCO"] = config["issuers"]["AAPL"]
    monkeypatch.setattr("equitylens.valuation.defaults._load_wacc_config", lambda: config)
    monkeypatch.setattr("equitylens.valuation.service.load_valuation_config", lambda: config)
    return TestClient(app, raise_server_exceptions=False)


def _confirm(client, publication, **overrides):
    ticker = overrides.pop("ticker", "NEWCO")
    assumption_overrides = overrides.pop("assumptions", {})
    security_id = overrides.get("security_id", "security-newco")
    draft = client.get(
        f"/api/v1/companies/{ticker}/valuation-profile/draft",
        params={"security_id": security_id, "publication_id": publication.publication_id},
    ).json()
    body = {
        "security_id": security_id,
        "publication_id": publication.publication_id,
        "model_version": MODEL_VERSION,
        "assumptions": {**draft["assumptions"]["inputs"], **assumption_overrides},
        "confirmed": True,
    }
    body.update(overrides)
    return client.put(f"/api/v1/companies/{ticker}/valuation-profile", json=body)


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


def test_published_baseline_ignores_newer_unreviewed_live_facts(db, monkeypatch):
    publication = _install_company(
        db,
        ticker="AAPL",
        complete_valuation_facts=True,
    )
    db._conn.execute(
        "UPDATE canonical_fact SET value=9999 WHERE company_id=? AND canonical_metric='REVENUE'",
        [publication.company_id],
    )
    client = _client(db, monkeypatch)

    response = client.get(
        "/api/v1/companies/AAPL/valuation-profile/draft",
        params={
            "security_id": "security-newco",
            "publication_id": publication.publication_id,
        },
    )

    assert response.status_code == 200, response.text
    assumptions = response.json()["assumptions"]
    assert assumptions["inputs"]["revenue_base"] == 1_000.0
    assert assumptions["meta"]["revenue_base"]["source_ids"] == ["revenue-401"]


def test_confirmation_preserves_provenance_when_reopened(db, monkeypatch):
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

    confirmed = client.put(
        "/api/v1/companies/AAPL/valuation-profile",
        json={
            "security_id": draft["security_id"],
            "publication_id": draft["publication_id"],
            "model_version": draft["model_version"],
            "assumptions": draft["assumptions"]["inputs"],
            "confirmed": True,
        },
    )

    assert confirmed.status_code == 200, confirmed.text
    stored = db.query_one(
        "SELECT source_metadata_json FROM valuation_assumption_set WHERE assumption_set_id=?",
        [confirmed.json()["confirmation_id"]],
    )["source_metadata_json"]
    if isinstance(stored, str):
        stored = json.loads(stored)
    assert stored["meta"]["revenue_base"]["source_type"] == "canonical_fact"
    assert stored["source_fact_ids"]["revenue_base"] == ["revenue-401"]

    reopened = client.get(
        "/api/v1/companies/AAPL/valuation/default",
        params={
            "security_id": "security-newco",
            "publication_id": publication.publication_id,
        },
    )
    assert reopened.status_code == 200, reopened.text
    revenue_meta = reopened.json()["assumptions"]["meta"]["revenue_base"]
    assert revenue_meta["source_type"] == "canonical_fact"
    assert revenue_meta["as_of"] == "FY2025"
    assert revenue_meta["source_ids"] == ["revenue-401"]


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("revenue_base", 1_001.0),
        ("shares", 11.0),
        ("net_cash", 101.0),
        ("tax_rate", 0.22),
        ("op_margin_start", 0.21),
        ("da_pct", 0.04),
        ("capex_pct", 0.06),
        ("nwc_pct", 0.02),
    ],
)
def test_confirmation_rejects_changed_immutable_facts_without_writing(
    db, monkeypatch, field, replacement
):
    publication = _install_company(db, complete_valuation_facts=True)
    client = _client(db, monkeypatch)
    draft = client.get(
        "/api/v1/companies/NEWCO/valuation-profile/draft",
        params={"security_id": "security-newco", "publication_id": publication.publication_id},
    ).json()
    assumptions = dict(draft["assumptions"]["inputs"])
    assumptions[field] = replacement
    before = db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"]
    response = client.put(
        "/api/v1/companies/NEWCO/valuation-profile",
        json={
            "security_id": "security-newco",
            "publication_id": publication.publication_id,
            "model_version": MODEL_VERSION,
            "assumptions": assumptions,
            "confirmed": True,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "VALUATION_FACT_BASELINE_CHANGED"
    assert response.json()["error"]["field"] == field
    assert db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"] == before


def test_confirmation_rejects_unknown_assumption_field_without_writing(db, monkeypatch):
    publication = _install_company(db, ticker="AAPL", complete_valuation_facts=True)
    client = _client(db, monkeypatch)
    draft = client.get(
        "/api/v1/companies/AAPL/valuation-profile/draft",
        params={"security_id": "security-newco", "publication_id": publication.publication_id},
    ).json()
    before = db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"]
    response = client.put(
        "/api/v1/companies/AAPL/valuation-profile",
        json={
            "security_id": "security-newco",
            "publication_id": publication.publication_id,
            "model_version": MODEL_VERSION,
            "assumptions": {**draft["assumptions"]["inputs"], "surprise": 1.0},
            "confirmed": True,
        },
    )
    assert response.status_code == 422, response.text
    assert db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"] == before


def test_confirmation_baseline_generation_failure_writes_nothing(db, monkeypatch):
    publication = _install_company(db, complete_valuation_facts=True)
    client = _client(db, monkeypatch)
    draft = client.get(
        "/api/v1/companies/NEWCO/valuation-profile/draft",
        params={"security_id": "security-newco", "publication_id": publication.publication_id},
    ).json()
    before = db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"]
    monkeypatch.setattr(
        "equitylens.valuation.service.default_valuation",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("baseline unavailable")),
    )
    response = client.put(
        "/api/v1/companies/NEWCO/valuation-profile",
        json={
            "security_id": "security-newco",
            "publication_id": publication.publication_id,
            "model_version": MODEL_VERSION,
            "assumptions": draft["assumptions"]["inputs"],
            "confirmed": True,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "VALUATION_DEFAULT_UNAVAILABLE"
    assert db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"] == before


@pytest.mark.parametrize("change", ["value", "source"])
def test_confirmation_requires_rereview_when_risk_free_metadata_changes(db, monkeypatch, change):
    publication = _install_company(db, ticker="AAPL", complete_valuation_facts=True)
    client = _client(db, monkeypatch)
    rate = {"value": 0.0425, "as_of": "2026-08-01", "source": "documented config fallback"}
    monkeypatch.setattr("equitylens.valuation.service.risk_free_rate", lambda: dict(rate))
    params = {"security_id": "security-newco", "publication_id": publication.publication_id}
    draft = client.get("/api/v1/companies/AAPL/valuation-profile/draft", params=params).json()
    assert isinstance(draft.get("risk_free_fingerprint"), str)
    body = {**params, "model_version": MODEL_VERSION, "assumptions": draft["assumptions"]["inputs"],
            "confirmed": True, "risk_free_fingerprint": draft["risk_free_fingerprint"]}
    before = db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"]
    rate[change] = 0.05 if change == "value" else "US Treasury daily yield curve (BC_10YEAR)"
    response = client.put("/api/v1/companies/AAPL/valuation-profile", json=body)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "VALUATION_RISK_FREE_CHANGED"
    assert db.query_one("SELECT count(*) AS n FROM valuation_assumption_set")["n"] == before
    renewed = client.get("/api/v1/companies/AAPL/valuation-profile/draft", params=params).json()
    body.update(assumptions=renewed["assumptions"]["inputs"], risk_free_fingerprint=renewed["risk_free_fingerprint"])
    response = client.put("/api/v1/companies/AAPL/valuation-profile", json=body)
    assert response.status_code == 200, response.text
    frozen = client.get("/api/v1/companies/AAPL/valuation/default", params=params).json()["assumptions"]["meta"]["risk_free"]
    assert frozen == renewed["assumptions"]["meta"]["risk_free"]
    rate["value"] = 0.099
    assert client.get("/api/v1/companies/AAPL/valuation/default", params=params).json()["assumptions"]["meta"]["risk_free"] == frozen


def test_rereviewed_rate_provenance_does_not_reuse_an_older_confirmation(db, monkeypatch):
    publication = _install_company(db, ticker="AAPL", complete_valuation_facts=True)
    client = _client(db, monkeypatch)
    rate = {"value": 0.0425, "as_of": "2026-08-01", "source": "documented config fallback"}
    monkeypatch.setattr("equitylens.valuation.service.risk_free_rate", lambda: dict(rate))
    params = {"security_id": "security-newco", "publication_id": publication.publication_id}
    def confirm_review():
        draft = client.get("/api/v1/companies/AAPL/valuation-profile/draft", params=params).json()
        response = client.put("/api/v1/companies/AAPL/valuation-profile", json={
            **params, "model_version": MODEL_VERSION, "assumptions": draft["assumptions"]["inputs"],
            "confirmed": True, "risk_free_fingerprint": draft["risk_free_fingerprint"],
        })
        assert response.status_code == 200, response.text
        return response.json(), draft
    first, _ = confirm_review()
    assert confirm_review()[0]["confirmation_id"] == first["confirmation_id"]
    rate.update(as_of="2026-09-01", source="US Treasury daily yield curve (BC_10YEAR)")
    second, reviewed = confirm_review()
    assert second["confirmation_id"] != first["confirmation_id"]
    assert confirm_review()[0]["confirmation_id"] == second["confirmation_id"]
    frozen = client.get("/api/v1/companies/AAPL/valuation/default", params=params).json()["assumptions"]["meta"]["risk_free"]
    assert frozen == reviewed["assumptions"]["meta"]["risk_free"]


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
    publication = _install_company(db, ticker="AAPL", complete_valuation_facts=True)
    client = _client(db, monkeypatch)
    confirmed = _confirm(client, publication, ticker="AAPL")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "READY"

    result = client.get(
        "/api/v1/companies/AAPL/valuation/default",
        params={"security_id": "security-newco"},
    )
    assert result.status_code == 200
    assert result.json()["security_id"] == "security-newco"
    assert result.json()["publication_id"] == publication.publication_id
    assert result.json()["assumptions"]["inputs"]["revenue_base"] == 1_000.0
    reverse = client.post(
        "/api/v1/companies/AAPL/valuation/reverse-dcf",
        params={"security_id": "security-newco"},
        json={"target_price": 100.0},
    )
    assert reverse.status_code == 200
    assert reverse.json()["security_id"] == "security-newco"

    newer = _install_new_publication(db, publication.company_id, version=402)
    stale = client.get(
        "/api/v1/companies/AAPL/valuation/default",
        params={"security_id": "security-newco", "publication_id": newer.publication_id},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VALUATION_NEEDS_CONFIGURATION"


def test_company_directory_requires_current_model_confirmation(db, monkeypatch):
    publication = _install_company(db, complete_valuation_facts=True)
    client = _client(db, monkeypatch)
    confirmed = _confirm(client, publication)
    assert confirmed.status_code == 200, confirmed.text
    db._conn.execute(
        "UPDATE valuation_assumption_set SET model_version='fcff_dcf.v1' "
        "WHERE assumption_set_id=?",
        [confirmed.json()["confirmation_id"]],
    )

    response = client.get("/api/v1/companies", params={"limit": 200})
    assert response.status_code == 200, response.text
    company = next(item for item in response.json()["items"] if item["ticker"] == "NEWCO")
    valuation = next(item for item in company["capabilities"] if item["module"] == "valuation")
    assert valuation["status"] == "NEEDS_CONFIGURATION"


def _confirmed_aapl_draft(db, monkeypatch):
    publication = _install_company(
        db,
        ticker="AAPL",
        complete_valuation_facts=True,
    )
    client = _client(db, monkeypatch)
    draft = client.get(
        "/api/v1/companies/AAPL/valuation-profile/draft",
        params={"security_id": "security-newco", "publication_id": publication.publication_id},
    ).json()
    confirmed = client.put(
        "/api/v1/companies/AAPL/valuation-profile",
        json={
            "security_id": draft["security_id"],
            "publication_id": draft["publication_id"],
            "model_version": draft["model_version"],
            "assumptions": draft["assumptions"]["inputs"],
            "confirmed": True,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return client, publication, draft


def test_personal_override_can_edit_approved_fields_and_retains_baseline_provenance(
    db, monkeypatch
):
    client, publication, draft = _confirmed_aapl_draft(db, monkeypatch)
    edited = dict(draft["assumptions"]["inputs"])
    edited["op_margin_end"] = edited["op_margin_end"] + 0.01

    response = client.post(
        "/api/v1/companies/AAPL/valuation/run",
        params={"security_id": "security-newco", "publication_id": publication.publication_id},
        json={"assumptions": edited, "persist": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assumptions"]["inputs"]["op_margin_end"] == edited["op_margin_end"]
    margin_meta = body["assumptions"]["meta"]["op_margin_end"]
    assert margin_meta["source_type"] == "user_override"
    assert margin_meta["baseline"]["source_type"] == "config_assumption"
    assert margin_meta["baseline"]["source_ids"] == [
        "operating_income-401",
        "revenue-401",
    ]

    stored = db.query_one(
        "SELECT fact_snapshot_json FROM valuation_run WHERE valuation_run_id=?",
        [body["valuation_run_id"]],
    )["fact_snapshot_json"]
    if isinstance(stored, str):
        stored = json.loads(stored)
    assert stored["meta"]["revenue_base"]["source_type"] == "canonical_fact"
    assert stored["meta"]["op_margin_end"]["source_type"] == "user_override"

    reverse = client.post(
        "/api/v1/companies/AAPL/valuation/reverse-dcf",
        params={"security_id": "security-newco", "publication_id": publication.publication_id},
        json={"target_price": 100.0, "assumptions": edited},
    )
    assert reverse.status_code == 200, reverse.text
    assert reverse.json()["fixed_assumptions"]["margin_end"] == edited["op_margin_end"]


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("revenue_base", 1_001.0),
        ("shares", 11.0),
        ("net_cash", 101.0),
        ("tax_rate", 0.22),
        ("op_margin_start", 0.21),
        ("da_pct", 0.04),
        ("capex_pct", 0.06),
        ("nwc_pct", 0.02),
    ],
)
def test_immutable_baseline_field_change_is_rejected(
    db, monkeypatch, field, replacement
):
    client, publication, draft = _confirmed_aapl_draft(db, monkeypatch)
    edited = dict(draft["assumptions"]["inputs"])
    edited[field] = replacement
    before_runs = db.query_one("SELECT count(*) AS n FROM valuation_run")["n"]

    response = client.post(
        "/api/v1/companies/AAPL/valuation/run",
        params={"security_id": "security-newco", "publication_id": publication.publication_id},
        json={"assumptions": edited, "persist": True},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"] == {
        "code": "VALUATION_FACT_BASELINE_CHANGED",
        "field": field,
        "message": f"{field} belongs to the reviewed fact baseline and cannot be edited",
    }
    assert db.query_one("SELECT count(*) AS n FROM valuation_run")["n"] == before_runs


def test_personal_override_invalid_model_input_never_persists(db, monkeypatch):
    client, publication, draft = _confirmed_aapl_draft(db, monkeypatch)
    edited = dict(draft["assumptions"]["inputs"])
    edited["wacc"] = 0.0
    before_runs = db.query_one("SELECT count(*) AS n FROM valuation_run")["n"]

    response = client.post(
        "/api/v1/companies/AAPL/valuation/run",
        params={"security_id": "security-newco", "publication_id": publication.publication_id},
        json={"assumptions": edited, "persist": True},
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_ASSUMPTION"
    assert response.json()["error"]["field"] == "wacc"
    assert db.query_one("SELECT count(*) AS n FROM valuation_run")["n"] == before_runs


def _ask_research_valuation(client, publication_id=None, *, ticker="NEWCO"):
    body = {
        "ticker": ticker,
        "security_id": "security-newco",
        "question": "估值怎么看？",
    }
    if publication_id is not None:
        body["publication_id"] = publication_id
    return client.post("/api/v1/research/ask", json=body)


def test_research_valuation_gate_blocks_unconfirmed_conclusion(db, monkeypatch):
    publication = _install_company(db)
    client = _client(db, monkeypatch)

    response = _ask_research_valuation(client, publication.publication_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intent"] == "valuation"
    assert body["status"] == "needs_review"
    assert body["claims"] == []
    assert body["valuation_identity"] == {
        "security_id": "security-newco",
        "publication_id": publication.publication_id,
        "model_version": MODEL_VERSION,
        "confirmation_id": None,
    }
    assert body["action"]["type"] == "open_valuation"
    assert "确认" in body["answer"]
    assert "Base $" not in body["answer"]
    assert "参考区间 $" not in body["answer"]


def test_research_valuation_gate_uses_bound_confirmation_and_evidence(db, monkeypatch):
    publication = _install_company(db, ticker="AAPL")
    client = _client(db, monkeypatch)
    confirmed = _confirm(client, publication, ticker="AAPL")
    assert confirmed.status_code == 200, confirmed.text

    response = _ask_research_valuation(client, publication.publication_id, ticker="AAPL")

    assert response.status_code == 200, response.text
    body = response.json()
    confirmation_id = confirmed.json()["confirmation_id"]
    assert body["status"] == "ready"
    assert body["valuation_identity"] == {
        "security_id": "security-newco",
        "publication_id": publication.publication_id,
        "model_version": MODEL_VERSION,
        "confirmation_id": confirmation_id,
    }
    assert body["evidence"] == [{
        "evidence_id": f"valuation_confirmation:{confirmation_id}",
        "kind": "valuation_confirmation",
        "confirmation_id": confirmation_id,
        "publication_id": publication.publication_id,
        "model_version": MODEL_VERSION,
    }]
    assert body["claims"]
    assert all(
        claim["evidence_ids"] == [f"valuation_confirmation:{confirmation_id}"]
        for claim in body["claims"][:2]
    )
    assert MODEL_VERSION in body["answer"]
    provenance = client.get(
        f"/api/v1/provenance/valuation_confirmation:{confirmation_id}",
        params={"publication_id": publication.publication_id},
    )
    assert provenance.status_code == 200, provenance.text
    assert provenance.json()["kind"] == "valuation_confirmation"
    assert provenance.json()["tree"]["fields"]["publication_id"] == publication.publication_id
    assert provenance.json()["tree"]["fields"]["model_version"] == MODEL_VERSION


def test_research_valuation_gate_does_not_compare_a_stale_quote(db, monkeypatch):
    publication = _install_company(db, ticker="AAPL")
    db.insert_market_quote({
        "quote_id": "quote-stale-newco",
        "company_id": publication.company_id,
        "security_id": "security-newco",
        "ticker": "AAPL",
        "provider": "fixture",
        "observed_at": "2020-01-02 00:00:00",
        "price": 42.0,
        "currency": "USD",
        "fetched_at": "2020-01-02 00:00:00",
    })
    client = _client(db, monkeypatch)
    assert _confirm(client, publication, ticker="AAPL").status_code == 200

    response = _ask_research_valuation(client, publication.publication_id, ticker="AAPL")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["market_state"] == "stale"
    assert "行情已过期" in body["answer"]
    assert "较公允价" not in body["answer"]
    assert all("较公允价" not in claim["claim"] for claim in body["claims"])


def test_research_valuation_gate_rechecks_changed_active_publication(db, monkeypatch):
    original = _install_company(db, ticker="AAPL")
    client = _client(db, monkeypatch)
    assert _confirm(client, original, ticker="AAPL").status_code == 200
    newer = _install_new_publication(db, original.company_id, version=402)

    active = _ask_research_valuation(client, ticker="AAPL")
    pinned = _ask_research_valuation(client, original.publication_id, ticker="AAPL")

    assert active.status_code == 200, active.text
    assert active.json()["publication_id"] == newer.publication_id
    assert active.json()["status"] == "needs_review"
    assert active.json()["valuation_identity"]["confirmation_id"] is None
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["publication_id"] == original.publication_id
    assert pinned.json()["status"] == "ready"


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


def test_currency_gate_normalizes_published_unit_case(db, monkeypatch):
    publication = _install_company(db, ticker="AAPL", fact_currency="usd")
    client = _client(db, monkeypatch)

    response = _confirm(client, publication, ticker="AAPL")

    assert response.status_code == 200, response.text


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
    publication = _install_company(db, ticker="AAPL")
    CompanyRegistry(db).register_security(
        SecurityIdentity(
            security_id="security-newco-b",
            company_id=publication.company_id,
            ticker="AAPL.B",
            exchange="NASDAQ",
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"verified": True},
        )
    )
    client = _client(db, monkeypatch)

    blocked = _confirm(client, publication, ticker="AAPL")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "VALUATION_SHARE_BASIS_UNVERIFIED"

    scoped = _confirm(
        client,
        publication,
        ticker="AAPL",
        assumptions={"share_basis_security_id": "security-newco"},
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
    plan_response = client.post(
        "/api/v1/companies/NEWCO/valuation/plans",
        json={
            "valuation_run_id": run["valuation_run_id"],
            "scenario_key": "base",
            "margin_of_safety": 0.2,
        },
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()

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
    assert copied["source_plan"]["review_status"] == "needs_review"
    assert copied["source_plan"]["publication_id"] == publication.publication_id
