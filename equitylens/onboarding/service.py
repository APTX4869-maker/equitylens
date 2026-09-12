"""Application service for verified company onboarding requests."""

from __future__ import annotations

import json

from equitylens.companies.discovery import CompanyDiscovery, DiscoveryError
from equitylens.companies.models import CompanyIdentity, DiscoveryResult, SecurityIdentity
from equitylens.companies.registry import CompanyRegistry, seed_security_id
from equitylens.onboarding.repository import OnboardingConflict, OnboardingRepository
from equitylens.publication.models import canonical_json, sha256_json
from equitylens.storage.writer import writer_for


class OnboardingService:
    def __init__(
        self,
        discovery: CompanyDiscovery,
        registry: CompanyRegistry,
        tasks: OnboardingRepository,
    ) -> None:
        self.discovery = discovery
        self.registry = registry
        self.tasks = tasks
        self.store = tasks.store

    def create(
        self,
        discovery_id: str,
        identity_hash: str,
        candidate_id: str,
        idempotency_key: str,
    ):
        request = {
            "discovery_id": discovery_id,
            "identity_hash": identity_hash,
            "candidate_id": candidate_id,
        }
        request_hash = sha256_json(request)
        prior = self.store.query_one(
            "SELECT request_hash, response_json FROM api_idempotency WHERE key=?",
            [idempotency_key],
        )
        if prior:
            if prior["request_hash"] != request_hash:
                raise OnboardingConflict(
                    "IDEMPOTENCY_CONFLICT", "idempotency key was used for another request"
                )
            response = json.loads(prior["response_json"])
            return self.tasks.get(response["onboarding_id"])

        stored_row = self.store.query_one(
            "SELECT payload_json FROM company_discovery WHERE discovery_id=?",
            [discovery_id],
        )
        if stored_row is None:
            raise DiscoveryError("DISCOVERY_EXPIRED", "discovery does not exist")
        stored = DiscoveryResult.model_validate_json(stored_row["payload_json"])
        if stored.eligibility.status == "REJECTED":
            raise DiscoveryError(
                stored.eligibility.reason_code or "UNSUPPORTED_INSTRUMENT",
                stored.eligibility.reason or "security is not eligible for onboarding",
            )
        candidate = self.discovery.verify(
            discovery_id,
            identity_hash=identity_hash,
            candidate_id=candidate_id,
        )
        security_id = seed_security_id(
            candidate.company_id, candidate.ticker, candidate.exchange
        )
        with writer_for(self.store).transaction(self.store):
            self.registry.register_company(
                CompanyIdentity(
                    company_id=candidate.company_id,
                    cik=candidate.company_id,
                    legal_name=candidate.legal_name,
                    reporting_template=stored.eligibility.template,
                    quality_status="PENDING",
                ),
                legacy_ticker=candidate.ticker,
            )
            if self.store._conn.execute(
                "SELECT 1 FROM security WHERE security_id=?", [security_id]
            ).fetchone() is None:
                self.registry.register_security(
                    SecurityIdentity(
                        security_id=security_id,
                        company_id=candidate.company_id,
                        ticker=candidate.ticker,
                        class_label=candidate.class_label,
                        exchange=candidate.exchange,
                        currency=candidate.currency,
                        instrument_type=candidate.instrument_type,
                        identity_evidence={
                            "discovery_id": discovery_id,
                            "identity_hash": identity_hash,
                            "evidence": candidate.evidence,
                        },
                    )
                )
            task = self.tasks.create_task(
                company_id=candidate.company_id,
                security_id=security_id,
                input_fingerprint=sha256_json(
                    {**request, "security_id": security_id}
                ),
            )
            self.store._conn.execute(
                "UPDATE company_onboarding SET discovery_id=? WHERE onboarding_id=?",
                [discovery_id, task.onboarding_id],
            )
            self.store._conn.execute(
                "INSERT INTO api_idempotency VALUES (?, ?, ?, now())",
                [
                    idempotency_key,
                    request_hash,
                    canonical_json({"onboarding_id": task.onboarding_id}),
                ],
            )
        return self.tasks.get(task.onboarding_id)

    def retry(self, task_id: str, expected_revision: int):
        return self.tasks.retry(task_id, expected_revision=expected_revision)

    def cancel(self, task_id: str, expected_revision: int):
        return self.tasks.cancel(task_id, expected_revision=expected_revision)
