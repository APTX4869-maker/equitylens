from __future__ import annotations

from datetime import date

import pytest

from equitylens.companies.models import CompanyIdentity, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry, CompanyRegistryError


@pytest.fixture()
def registry_with_two_classes(db):
    registry = CompanyRegistry(db)
    company = CompanyIdentity(
        company_id="0000000001",
        cik="0000000001",
        legal_name="Example Holdings Inc.",
        reporting_template="us_gaap_operating_v1",
    )
    registry.register_company(company, legacy_ticker="EXAMPLE.A")
    registry.register_security(
        SecurityIdentity(
            security_id="11111111-1111-4111-8111-111111111111",
            company_id=company.company_id,
            ticker="EXAMPLE.A",
            class_label="Class A",
            exchange="NYSE",
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"source": "fixture", "class": "A"},
        )
    )
    registry.register_security(
        SecurityIdentity(
            security_id="22222222-2222-4222-8222-222222222222",
            company_id=company.company_id,
            ticker="EXAMPLE.B",
            class_label="Class B",
            exchange="NYSE",
            currency="USD",
            instrument_type="COMMON_STOCK",
            identity_evidence={"source": "fixture", "class": "B"},
        )
    )
    return registry


def test_share_classes_keep_separate_identity(registry_with_two_classes):
    a = registry_with_two_classes.resolve("EXAMPLE.A")
    b = registry_with_two_classes.resolve("EXAMPLE.B")

    assert a.company_id == b.company_id
    assert a.security_id != b.security_id


def test_ambiguous_ticker_requires_security_id(db):
    registry = CompanyRegistry(db)
    for cik, security_id, exchange in (
        ("0000000001", "11111111-1111-4111-8111-111111111111", "NYSE"),
        ("0000000002", "22222222-2222-4222-8222-222222222222", "NASDAQ"),
    ):
        registry.register_company(
            CompanyIdentity(company_id=cik, cik=cik, legal_name=f"Issuer {cik}"),
            legacy_ticker="DUP",
        )
        registry.register_security(
            SecurityIdentity(
                security_id=security_id,
                company_id=cik,
                ticker="DUP",
                exchange=exchange,
                currency="USD",
                instrument_type="COMMON_STOCK",
                identity_evidence={"source": "fixture"},
            )
        )

    with pytest.raises(CompanyRegistryError) as exc:
        registry.resolve("dup")
    assert exc.value.code == "AMBIGUOUS_SECURITY"
    assert {item.security_id for item in exc.value.candidates} == {
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    }

    selected = registry.resolve(
        "DUP", security_id="22222222-2222-4222-8222-222222222222"
    )
    assert selected.exchange == "NASDAQ"


def test_alias_validity_ranges_cannot_overlap(db):
    registry = CompanyRegistry(db)
    registry.register_company(
        CompanyIdentity(
            company_id="0000000001", cik="0000000001", legal_name="Issuer"
        ),
        legacy_ticker="OLD",
    )
    security = SecurityIdentity(
        security_id="11111111-1111-4111-8111-111111111111",
        company_id="0000000001",
        ticker="OLD",
        exchange="NYSE",
        currency="USD",
        instrument_type="COMMON_STOCK",
        identity_evidence={"source": "fixture"},
    )
    registry.register_security(
        security, valid_from=date(2020, 1, 1), valid_to=date(2022, 12, 31)
    )

    with pytest.raises(CompanyRegistryError) as exc:
        registry.add_ticker_alias(
            security.security_id,
            ticker="OLD",
            exchange="NYSE",
            valid_from=date(2022, 1, 1),
        )
    assert exc.value.code == "TICKER_ALIAS_OVERLAP"

