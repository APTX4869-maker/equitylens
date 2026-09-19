"""Production SEC-to-candidate handlers for durable onboarding tasks."""

from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Callable

import httpx

from equitylens.config import (
    CONFIG_DIR,
    PARSER_VERSION,
    RAW_DIR,
    SEC_ARCHIVES_URL,
    SEC_COMPANYFACTS_URL,
    SEC_SUBMISSIONS_URL,
)
from equitylens.ingestion.sec.client import SECClient
from equitylens.issuers.profile import IssuerProfile, load_profile_yaml
from equitylens.issuers.review import ReviewService
from equitylens.normalization.fiscal_periods import FiscalCalendar
from equitylens.normalization.normalize import normalize_companyfacts
from equitylens.normalization.taxonomy.mappings import MappingRegistry
from equitylens.onboarding.models import OnboardingStep, TaskState
from equitylens.onboarding.fetch_bundle import collect_submission_rows, select_required_filings
from equitylens.onboarding.repository import OnboardingRepository
from equitylens.onboarding.runner import OnboardingPause
from equitylens.publication.builder import DatasetBuilder
from equitylens.publication.repository import PublicationRepository
from equitylens.quality.engine import QualityEngine
from equitylens.quality.models import CheckStatus, Severity
from equitylens.storage.raw_store import load_snapshot_record, save_snapshot


Fetch = Callable[[str], tuple[bytes, dict]]


class OnboardingFetchError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ProfileMappingRegistry:
    """Restrict the reviewed global rule shapes to profile-approved concepts."""

    def __init__(self, profile: IssuerProfile) -> None:
        self.base = MappingRegistry()
        self.profile = profile
        self.allowed = {
            metric: set(spec.concepts) for metric, spec in profile.metrics.items()
        }

    @property
    def mapping_version(self) -> str:
        return f"{self.base.mapping_version}+profile.v{self.profile.version}"

    @property
    def profile_version(self) -> int:
        return self.profile.version

    def find(self, taxonomy: str, concept: str):
        rule = self.base.find(taxonomy, concept)
        if rule is None:
            return None
        concepts = self.allowed.get(rule.canonical_metric, set())
        return rule if f"{taxonomy}:{concept}" in concepts else None

    def metric(self, name: str):
        return self.base.metric(name) if name in self.allowed else None

    def all_metrics(self) -> list[str]:
        return [name for name in self.base.all_metrics() if name in self.allowed]


class OnboardingPipeline:
    def __init__(
        self,
        store,
        repository: OnboardingRepository,
        *,
        raw_dir: Path = RAW_DIR,
        profile_root: Path | None = None,
        fetcher: Fetch | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.raw_dir = Path(raw_dir)
        self.profile_root = Path(profile_root or CONFIG_DIR / "issuers")
        self._sec_client = None if fetcher is not None else SECClient(max_retries=1)
        self.fetcher = fetcher or self._fetch_url

    def _fetch_url(self, url: str) -> tuple[bytes, dict]:
        if self._sec_client is None:
            raise RuntimeError("SEC client is not configured")
        try:
            _, content, metadata = self._sec_client.get(url)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise OnboardingFetchError(
                "SEC_ACCESS_DENIED" if status_code in {401, 403} else "SEC_REQUEST_FAILED",
                f"SEC EDGAR returned HTTP {status_code}",
                retryable=status_code == 429 or status_code >= 500,
            ) from exc
        except RuntimeError as exc:
            raise OnboardingFetchError(
                "SEC_UNAVAILABLE", str(exc), retryable=True
            ) from exc
        return content, metadata

    def close(self) -> None:
        if self._sec_client is not None:
            self._sec_client.close()

    def handlers(self) -> dict[OnboardingStep, Callable]:
        return {
            OnboardingStep.FETCH: self.fetch,
            OnboardingStep.BUILD: self.build,
            OnboardingStep.VALIDATE: self.validate,
            OnboardingStep.PUBLISH: self.publish,
        }

    def fetch(self, task) -> dict:
        directory = self.raw_dir / "sec" / task.company_id
        fixed_documents: list[dict] = []
        payloads: dict[str, bytes] = {}
        for name, url in (
            ("submissions.json", SEC_SUBMISSIONS_URL + f"CIK{task.company_id}.json"),
            ("companyfacts.json", SEC_COMPANYFACTS_URL + f"CIK{task.company_id}.json"),
        ):
            content, metadata = self.fetcher(url)
            path, digest = save_snapshot(
                directory,
                name,
                content,
                metadata={"fetched_at": metadata["fetched_at"], "source_url": url},
            )
            payloads[name] = content
            fixed_documents.append(
                {
                    "document_id": f"{name}:{digest}",
                    "document_type": "SUBMISSIONS" if name == "submissions.json" else "COMPANYFACTS",
                    "fetched_at": metadata["fetched_at"],
                    "source_url": url,
                    "content_sha256": digest,
                    "raw_locator": path.relative_to(self.raw_dir).as_posix(),
                }
            )

        submissions = json.loads(payloads["submissions.json"])
        history_payloads: dict[str, dict] = {}
        for declared in (submissions.get("filings") or {}).get("files") or []:
            name = str(declared.get("name") or "")
            url = SEC_SUBMISSIONS_URL + name
            content, metadata = self.fetcher(url)
            path, digest = save_snapshot(
                directory,
                name,
                content,
                metadata={"fetched_at": metadata["fetched_at"], "source_url": url},
            )
            history_payloads[name] = json.loads(content)
            fixed_documents.append(
                {
                    "document_id": f"history:{name}:{digest}",
                    "document_type": "SUBMISSIONS_HISTORY",
                    "fetched_at": metadata["fetched_at"],
                    "source_url": url,
                    "content_sha256": digest,
                    "raw_locator": path.relative_to(self.raw_dir).as_posix(),
                }
            )

        attempt = self.store.query_one(
            """
            SELECT started_at FROM onboarding_step_attempt
            WHERE onboarding_id=? AND step='FETCH' AND state='RUNNING'
            ORDER BY attempt_no DESC LIMIT 1
            """,
            [task.onboarding_id],
        )
        as_of = attempt["started_at"]
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        selected = select_required_filings(
            collect_submission_rows(submissions, history_payloads), as_of=as_of
        )
        cik_without_padding = str(int(task.company_id))
        for filing in selected:
            accession_path = filing.accession_number.replace("-", "")
            url = (
                f"{SEC_ARCHIVES_URL}{cik_without_padding}/{accession_path}/"
                f"{filing.primary_document}"
            )
            content, metadata = self.fetcher(url)
            path, digest = save_snapshot(
                directory / "filing_docs" / filing.accession_number,
                "primary.html",
                content,
                metadata={"fetched_at": metadata["fetched_at"], "source_url": url},
            )
            fixed_documents.append(
                {
                    "document_id": f"filing:{filing.accession_number}:{digest}",
                    "document_type": "FILING_DOCUMENT",
                    "accession_number": filing.accession_number,
                    "form_type": filing.form_type,
                    "filed_at": filing.filing_date,
                    "report_date": filing.report_date,
                    "fetched_at": metadata["fetched_at"],
                    "source_url": url,
                    "content_sha256": digest,
                    "raw_locator": path.relative_to(self.raw_dir).as_posix(),
                }
            )
        bundle = self.repository.create_fetch_bundle(
            task.onboarding_id,
            expected_revision=task.revision,
            fetcher_version="sec-onboarding.v2",
            parser_version=PARSER_VERSION,
            documents=fixed_documents,
        )
        return {
            "fetch_bundle_id": bundle.fetch_bundle_id,
            "content_sha256": bundle.content_sha256,
            "document_count": len(bundle.documents),
        }

    def _profile(self, task) -> tuple[IssuerProfile, str]:
        publications = PublicationRepository(self.store)
        if task.profile_id:
            row = self.store.query_one(
                "SELECT content_json FROM issuer_profile_version WHERE profile_id=?",
                [task.profile_id],
            )
            profile = IssuerProfile.model_validate(json.loads(row["content_json"]))
            if profile.company_id != task.company_id:
                raise ValueError("profile company_id does not match onboarding company")
            return profile, task.profile_id
        directory = self.profile_root / task.company_id
        paths = sorted(
            directory.glob("*.yaml"),
            key=lambda path: int(path.stem) if path.stem.isdigit() else -1,
        ) if directory.exists() else []
        if not paths:
            raise OnboardingPause(
                TaskState.NEEDS_ADAPTATION,
                OnboardingStep.BUILD,
                "no reviewed issuer profile is installed; import a versioned profile",
            )
        profile = load_profile_yaml(paths[-1])
        if profile.company_id != task.company_id:
            raise ValueError("profile company_id does not match onboarding company")
        profile_id = publications.create_profile(
            task.company_id,
            version=profile.version,
            schema_version=profile.schema_version,
            content=profile.model_dump(mode="json", exclude={"content_sha256"}),
        )
        return profile, profile_id

    def build(self, task) -> dict:
        profile, profile_id = self._profile(task)
        directory = self.raw_dir / "sec" / task.company_id
        submissions = load_snapshot_record(directory, "submissions.json")
        companyfacts = load_snapshot_record(directory, "companyfacts.json")
        if submissions is None or companyfacts is None:
            raise RuntimeError("verified SEC snapshots are missing; rerun FETCH")
        raw, canonical, result = normalize_companyfacts(
            json.loads(companyfacts.content),
            self._profile_mappings(profile),
            FiscalCalendar.from_submissions(
                json.loads(submissions.content),
                fallback_mm_dd=profile.fiscal_calendar.year_end,
            ),
            source_document_id=f"SEC-companyfacts-CIK{task.company_id}",
            company_id=task.company_id,
        )
        companyfacts_document = {
            "source_document_id": f"SEC-companyfacts-CIK{task.company_id}",
            "company_id": task.company_id,
            "provider": "SEC",
            "document_type": "COMPANYFACTS_SNAPSHOT",
            "source_url": SEC_COMPANYFACTS_URL + f"CIK{task.company_id}.json",
            "fetched_at": companyfacts.fetched_at,
            "content_sha256": companyfacts.sha256,
            "local_path": str(companyfacts.path),
        }
        submissions_document = {
            "source_document_id": f"SEC-submissions-CIK{task.company_id}",
            "company_id": task.company_id,
            "provider": "SEC",
            "document_type": "SUBMISSIONS_SNAPSHOT",
            "source_url": SEC_SUBMISSIONS_URL + f"CIK{task.company_id}.json",
            "fetched_at": submissions.fetched_at,
            "content_sha256": submissions.sha256,
            "local_path": str(submissions.path),
        }
        documents = [submissions_document, companyfacts_document]
        rows = [
            ("source_document", document["source_document_id"], document)
            for document in documents
        ]
        rows.extend(("raw_fact", row["raw_fact_id"], row) for row in raw)
        rows.extend(("canonical_fact", row["canonical_fact_id"], row) for row in canonical)
        dataset_id = DatasetBuilder(self.store).seal_rows(
            company_id=task.company_id,
            profile_id=profile_id,
            source_manifest={
                "documents": documents,
                "submissions_sha256": submissions.sha256,
                "profile_version": profile.version,
            },
            rows=rows,
        )
        self.repository.set_candidate(
            task.onboarding_id,
            expected_revision=task.revision,
            profile_id=profile_id,
            dataset_id=dataset_id,
            state=TaskState.BUILDING,
            current_step=OnboardingStep.BUILD,
        )
        return {"dataset_id": dataset_id, "canonical_count": result.canonical_count}

    @staticmethod
    def _profile_mappings(profile: IssuerProfile) -> ProfileMappingRegistry:
        return ProfileMappingRegistry(profile)

    def validate(self, task) -> dict:
        if not task.dataset_id or not task.profile_id:
            raise RuntimeError("candidate dataset and profile are required")
        report = QualityEngine(self.store).validate(task.dataset_id)
        self.repository.set_candidate(
            task.onboarding_id,
            expected_revision=task.revision,
            profile_id=task.profile_id,
            dataset_id=task.dataset_id,
            quality_report_id=report.report_id,
            state=TaskState.VALIDATING,
            current_step=OnboardingStep.VALIDATE,
        )
        missing_segments = any(
            check.check_id == "SEGMENTS.reconciliation"
            and check.severity == Severity.BLOCKER
            and check.status in {CheckStatus.FAIL, CheckStatus.UNSUPPORTED}
            for check in report.checks
        )
        if missing_segments and profile_requires_segments(task, self.store):
            raise OnboardingPause(
                TaskState.NEEDS_ADAPTATION,
                OnboardingStep.BUILD,
                "reviewed iXBRL segment evidence and a named parser are required",
            )
        return {"quality_report_id": report.report_id, "result": report.result}

    def publish(self, task) -> dict:
        if not task.review_id:
            raise RuntimeError("approved review is required")
        publication = ReviewService(
            self.store,
            self.repository,
            PublicationRepository(self.store),
            publish_immediately=False,
        ).publish_approved(
            task.onboarding_id,
            expected_revision=task.revision,
            review_id=task.review_id,
        )
        return publication.model_dump(mode="json")


def profile_requires_segments(task, store) -> bool:
    row = store.query_one(
        "SELECT content_json FROM issuer_profile_version WHERE profile_id=?",
        [task.profile_id],
    )
    profile = json.loads(row["content_json"])
    return (profile.get("applicability") or {}).get("SEGMENTS") == "required"
