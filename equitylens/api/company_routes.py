"""Company registry, onboarding, review, and publication-version routes."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

import yaml
from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from equitylens.api.company_schemas import (
    CreateOnboardingRequest,
    DiscoverRequest,
    ProfileImportRequest,
    ProfileYamlImportRequest,
    ReviewRequest,
    RevisionRequest,
    ValuationProfileRequest,
)
from equitylens.companies.discovery import CompanyDiscovery, DiscoveryError
from equitylens.companies.registry import CompanyRegistry, CompanyRegistryError
from equitylens.issuers.profile import IssuerProfileService
from equitylens.issuers.review import ReviewConflict, ReviewService
from equitylens.onboarding.repository import OnboardingConflict, OnboardingRepository
from equitylens.onboarding.service import OnboardingService
from equitylens.publication.models import sha256_json
from equitylens.publication.repository import PublicationConflict, PublicationRepository
from equitylens.valuation.dcf import ValuationError
from equitylens.valuation.service import confirm_valuation_profile


router = APIRouter(prefix="/api/v1")


def _store():
    # Reuse the established test seam and the process-wide writer-backed store.
    from equitylens.api.routes import _store as routes_store

    return routes_store()


def _detail(
    code: str,
    message: str,
    *,
    remediation: str = "NONE",
    field_errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "remediation": remediation,
        "field_errors": field_errors or [],
    }


def _wake(request: Request) -> None:
    executor = getattr(request.app.state, "onboarding_executor", None)
    if executor is not None:
        executor.wake()


def _candidate_payload(candidate, *, current: bool) -> dict[str, Any]:
    return {
        "profile_candidate_id": candidate.profile_candidate_id,
        "onboarding_id": candidate.onboarding_id,
        "task_revision": candidate.task_revision,
        "fetch_bundle_id": candidate.fetch_bundle_id,
        "input_sha256": candidate.input_sha256,
        "content_sha256": candidate.content_sha256,
        "snapshot_manifest": candidate.snapshot_manifest,
        "profile": candidate.profile,
        "unresolved_fields": [item.model_dump(mode="json") for item in candidate.unresolved_fields],
        "review_status": candidate.review_status,
        "created_at": candidate.created_at.isoformat(),
        "current": current,
    }


def _raise_service_error(exc: Exception) -> None:
    code = getattr(exc, "code", "REQUEST_FAILED")
    if isinstance(exc, DiscoveryError):
        if code == "SEC_UNAVAILABLE":
            status_code = 503
        else:
            status_code = 422 if code in {"INVALID_TICKER", "UNSUPPORTED_INSTRUMENT"} else 409
    elif isinstance(exc, KeyError):
        status_code = 404
    elif code in {"PROFILE_CANDIDATE_NOT_FOUND", "PROFILE_NOT_IMPORTED"}:
        status_code = 404
    else:
        status_code = 409
    remediation = getattr(exc, "remediation", None)
    if remediation is None and code in {"FETCH_BUNDLE_INCOMPLETE", "FETCH_BUNDLE_CORRUPTED"}:
        remediation = "REFETCH"
    raise HTTPException(
        status_code,
        _detail(code, str(exc), remediation=remediation or "NONE"),
    ) from exc


def _task_payload(task, *, store=None, **extra) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    progress: dict[str, Any] = {}
    if store is not None:
        row = store.query_one(
            """
            SELECT a.ticker, c.legal_name AS company_name
            FROM company c
            LEFT JOIN security s ON s.company_id=c.company_id AND s.status='ACTIVE'
            LEFT JOIN security_ticker_alias a ON a.security_id=s.security_id
              AND a.valid_from <= CURRENT_DATE
              AND (a.valid_to IS NULL OR a.valid_to >= CURRENT_DATE)
            WHERE c.company_id=? ORDER BY a.ticker LIMIT 1
            """,
            [task.company_id],
        )
        if row:
            identity = {"ticker": row.get("ticker"), "company_name": row.get("company_name")}
        progress = {
            "progress": OnboardingRepository(store).progress(task).model_dump(mode="json")
        }
    return {**task.model_dump(mode="json"), **identity, **progress, **extra}


def _decode_company_cursor(cursor: str | None) -> tuple[str | None, str | None, str | None]:
    if cursor is None:
        return None, None, None
    if not cursor.startswith("v1:"):
        return cursor, "\uffff", "\uffff"
    try:
        token = cursor.removeprefix("v1:")
        padding = "=" * (-len(token) % 4)
        decoded = base64.b64decode(token + padding, altchars=b"-_", validate=True)
        values = json.loads(decoded)
        if (
            not isinstance(values, list)
            or len(values) != 3
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError("invalid company cursor payload")
        return values[0], values[1], values[2]
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, _detail("INVALID_CURSOR", "company cursor is invalid")) from exc


def _encode_company_cursor(security_id: str, ticker: str, alias_id: str) -> str:
    payload = json.dumps([security_id, ticker, alias_id], separators=(",", ":")).encode()
    return "v1:" + base64.urlsafe_b64encode(payload).decode().rstrip("=")


@router.get("/companies")
def companies(
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
):
    store = _store()
    cursor_security_id, cursor_ticker, cursor_alias_id = _decode_company_cursor(cursor)
    rows = store.query(
        """
        SELECT c.company_id, s.security_id, a.ticker, c.legal_name AS name,
               s.exchange, c.active_publication_id AS publication_id,
               CASE WHEN p.review_id IS NOT NULL AND q.result='PASS'
                    THEN 'VERIFIED' ELSE c.quality_status END AS quality_status,
               a.alias_id AS _cursor_alias_id
        FROM security s
        JOIN company c ON c.company_id=s.company_id
        JOIN security_ticker_alias a ON a.security_id=s.security_id
        LEFT JOIN publication p ON p.publication_id=c.active_publication_id
        LEFT JOIN quality_report q ON q.report_id=p.quality_report_id
        WHERE s.status='ACTIVE' AND c.active_publication_id IS NOT NULL
          AND a.valid_from <= CURRENT_DATE
          AND (a.valid_to IS NULL OR a.valid_to >= CURRENT_DATE)
          AND (
            ? IS NULL
            OR s.security_id > ?
            OR (s.security_id = ? AND a.ticker > ?)
            OR (s.security_id = ? AND a.ticker = ? AND a.alias_id > ?)
          )
        ORDER BY s.security_id, a.ticker, a.alias_id
        LIMIT ?
        """,
        [
            cursor_security_id,
            cursor_security_id,
            cursor_security_id,
            cursor_ticker,
            cursor_security_id,
            cursor_ticker,
            cursor_alias_id,
            limit + 1,
        ],
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = _encode_company_cursor(
        items[-1]["security_id"],
        items[-1]["ticker"],
        items[-1]["_cursor_alias_id"],
    ) if has_more else None
    for item in items:
        item.pop("_cursor_alias_id", None)
        capabilities = store.query(
            "SELECT module, status, reason, coverage_json FROM company_capability WHERE publication_id=? ORDER BY module",
            [item["publication_id"]],
        ) if item["publication_id"] else []
        for capability in capabilities:
            value = capability.get("coverage_json")
            capability["coverage"] = json.loads(value) if isinstance(value, str) else value
            capability.pop("coverage_json", None)
            if capability["module"] == "valuation":
                confirmation = store.query_one(
                    """
                    SELECT 1 FROM valuation_assumption_set
                    WHERE security_id=? AND publication_id=? AND status='CONFIRMED'
                    LIMIT 1
                    """,
                    [item["security_id"], item["publication_id"]],
                )
                if confirmation:
                    capability["status"] = "READY"
                    capability["reason"] = None
        item["capabilities"] = capabilities
    return {
        "items": items,
        "next_cursor": next_cursor,
    }


@router.post("/companies/discover")
def discover(body: DiscoverRequest):
    try:
        return CompanyDiscovery(_store()).discover(body.ticker).model_dump(mode="json")
    except DiscoveryError as exc:
        _raise_service_error(exc)


@router.post(
    "/company-onboardings",
    status_code=status.HTTP_202_ACCEPTED,
)
def create_onboarding(
    body: CreateOnboardingRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1),
):
    store = _store()
    request_hash = sha256_json(body.model_dump(mode="json"))
    prior = store.query_one(
        "SELECT request_hash FROM api_idempotency WHERE key=?", [idempotency_key]
    )
    existing = prior is not None and prior["request_hash"] == request_hash
    try:
        task = OnboardingService(
            CompanyDiscovery(store),
            CompanyRegistry(store),
            OnboardingRepository(store),
        ).create(**body.model_dump(), idempotency_key=idempotency_key)
        return _task_payload(task, store=store, existing=existing)
    except (DiscoveryError, OnboardingConflict, CompanyRegistryError) as exc:
        _raise_service_error(exc)


@router.get("/company-onboardings")
def onboarding_list(
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    attention_only: bool = False,
):
    store = _store()
    rows = store.query(
        """
        SELECT onboarding_id FROM company_onboarding
        WHERE (? IS NULL OR onboarding_id > ?)
          AND (NOT ? OR state NOT IN ('PUBLISHED','CANCELLED'))
        ORDER BY onboarding_id LIMIT ?
        """,
        [cursor, cursor, attention_only, limit + 1],
    )
    attention_count = store.query_one(
        """SELECT count(*) AS n FROM company_onboarding
           WHERE state NOT IN ('PUBLISHED','CANCELLED')"""
    )["n"]
    repository = OnboardingRepository(store)
    items = [repository.get(row["onboarding_id"]) for row in rows[:limit]]
    return {
        "items": [_task_payload(item, store=store) for item in items],
        "next_cursor": items[-1].onboarding_id if len(rows) > limit else None,
        "attention_count": attention_count,
    }


@router.get("/company-onboardings/{task_id}")
def onboarding_detail(task_id: str):
    store = _store()
    repository = OnboardingRepository(store)
    try:
        task = repository.get(task_id)
    except KeyError as exc:
        _raise_service_error(exc)
    attempts = store.query(
        "SELECT * FROM onboarding_step_attempt WHERE onboarding_id=? ORDER BY started_at",
        [task_id],
    )
    checks = store.query(
        "SELECT * FROM company_quality_check WHERE report_id=? ORDER BY check_id, scope_key",
        [task.quality_report_id],
    ) if task.quality_report_id else []
    blocking = [
        {"check_id": row["check_id"], "reason": row.get("reason")}
        for row in checks
        if row["status"] == "FAIL" and row["severity"] == "BLOCKER"
    ]
    return _task_payload(task, store=store, steps=attempts, checks=checks, blocking_reasons=blocking)


@router.post("/company-onboardings/{task_id}/retry")
def retry_onboarding(task_id: str, body: RevisionRequest):
    try:
        store = _store()
        task = OnboardingRepository(store).retry(
            task_id, expected_revision=body.expected_revision
        )
        return _task_payload(task, store=store)
    except (KeyError, OnboardingConflict) as exc:
        _raise_service_error(exc)


@router.post("/company-onboardings/{task_id}/cancel")
def cancel_onboarding(task_id: str, body: RevisionRequest):
    try:
        store = _store()
        task = OnboardingRepository(store).cancel(
            task_id, expected_revision=body.expected_revision
        )
        return _task_payload(task, store=store)
    except (KeyError, OnboardingConflict) as exc:
        _raise_service_error(exc)


@router.post("/company-onboardings/{task_id}/profile-candidate")
def generate_profile_candidate(task_id: str, body: RevisionRequest):
    store = _store()
    try:
        task, candidate = OnboardingService(
            CompanyDiscovery(store), CompanyRegistry(store), OnboardingRepository(store)
        ).generate_profile_candidate(task_id, body.expected_revision)
        return {
            "task": _task_payload(task, store=store),
            "candidate": _candidate_payload(candidate, current=True),
        }
    except (KeyError, OnboardingConflict, RuntimeError) as exc:
        _raise_service_error(exc)


@router.get("/company-onboardings/{task_id}/profile-candidate")
def profile_candidate(task_id: str):
    store = _store()
    repository = OnboardingRepository(store)
    try:
        task = repository.get(task_id)
        if not task.profile_candidate_id:
            raise OnboardingConflict("PROFILE_CANDIDATE_NOT_FOUND", "profile candidate is not available")
        candidate = repository.get_profile_candidate(task.profile_candidate_id)
        refetching = task.state.value == "FETCHING" or (task.error or {}).get("remediation") == "REFETCH"
        current = task.fetch_bundle_id == candidate.fetch_bundle_id and not refetching
        return _candidate_payload(candidate, current=current)
    except (KeyError, OnboardingConflict) as exc:
        _raise_service_error(exc)


@router.get("/company-onboardings/{task_id}/profile-candidate.yaml")
def profile_candidate_yaml(task_id: str):
    store = _store()
    repository = OnboardingRepository(store)
    try:
        task = repository.get(task_id)
        if not task.profile_candidate_id:
            raise OnboardingConflict("PROFILE_CANDIDATE_NOT_FOUND", "profile candidate is not available")
        candidate = repository.get_profile_candidate(task.profile_candidate_id)
    except (KeyError, OnboardingConflict) as exc:
        _raise_service_error(exc)
    return Response(
        candidate.yaml_text,
        media_type="application/yaml",
        headers={
            "Content-Disposition": f'attachment; filename="{task.company_id}-profile-candidate.yaml"',
            "ETag": f'"{candidate.yaml_sha256}"',
            "X-Content-SHA256": candidate.content_sha256,
        },
    )


@router.get("/company-onboardings/{task_id}/profile-current.yaml")
def profile_current_yaml(task_id: str):
    store = _store()
    try:
        task = OnboardingRepository(store).get(task_id)
        if not task.profile_id:
            raise OnboardingConflict("PROFILE_NOT_IMPORTED", "reviewed profile is not available")
        row = store.query_one(
            "SELECT version, content_json, content_sha256 FROM issuer_profile_version WHERE profile_id=?",
            [task.profile_id],
        )
        if row is None:
            raise OnboardingConflict("PROFILE_NOT_IMPORTED", "reviewed profile is not available")
    except (KeyError, OnboardingConflict) as exc:
        _raise_service_error(exc)
    content = json.loads(row["content_json"]) if isinstance(row["content_json"], str) else row["content_json"]
    return Response(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False),
        media_type="application/yaml",
        headers={
            "Content-Disposition": f'attachment; filename="{task.company_id}-profile-v{row["version"]}.yaml"',
            "X-Profile-Version": str(row["version"]),
            "X-Content-SHA256": row["content_sha256"],
        },
    )


@router.post("/company-onboardings/{task_id}/refetch")
def refetch_onboarding(task_id: str, body: RevisionRequest, request: Request):
    store = _store()
    try:
        task = OnboardingService(
            CompanyDiscovery(store), CompanyRegistry(store), OnboardingRepository(store),
            wake=lambda: _wake(request),
        ).refetch(task_id, body.expected_revision)
        return _task_payload(task, store=store)
    except (KeyError, OnboardingConflict) as exc:
        _raise_service_error(exc)


@router.get("/company-onboardings/{task_id}/review-package")
def review_package(task_id: str):
    store = _store()
    try:
        return ReviewService(
            store, OnboardingRepository(store), PublicationRepository(store)
        ).review_package(task_id)
    except (KeyError, ReviewConflict) as exc:
        _raise_service_error(exc)


@router.post("/company-onboardings/{task_id}/profile")
def import_profile(
    task_id: str,
    body: ProfileImportRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1),
):
    store = _store()
    try:
        task = IssuerProfileService(
            PublicationRepository(store), OnboardingRepository(store),
            wake=lambda: _wake(request),
        ).import_profile(
            task_id, body.expected_revision, body.profile,
            idempotency_key=idempotency_key,
        )
        return _task_payload(task, store=store)
    except KeyError as exc:
        _raise_service_error(exc)
    except OnboardingConflict as exc:
        _raise_service_error(exc)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, _detail("INVALID_PROFILE", str(exc))) from exc


@router.post("/company-onboardings/{task_id}/profile-yaml")
def import_profile_yaml(
    task_id: str,
    body: ProfileYamlImportRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1),
):
    store = _store()
    try:
        task = IssuerProfileService(
            PublicationRepository(store), OnboardingRepository(store),
            wake=lambda: _wake(request),
        ).import_profile_yaml(
            task_id, body.expected_revision, idempotency_key, body.yaml_text
        )
        return _task_payload(task, store=store)
    except KeyError as exc:
        _raise_service_error(exc)
    except OnboardingConflict as exc:
        _raise_service_error(exc)
    except ValidationError as exc:
        fields = [
            {"path": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in exc.errors()
        ]
        raise HTTPException(
            422,
            _detail(
                "INVALID_PROFILE_YAML",
                f"reviewed profile has {len(fields)} invalid fields",
                remediation="PROFILE_IMPORT",
                field_errors=fields,
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            422,
            _detail(
                "INVALID_PROFILE_YAML", str(exc), remediation="PROFILE_IMPORT"
            ),
        ) from exc


@router.post("/company-onboardings/{task_id}/review")
def review(task_id: str, body: ReviewRequest):
    store = _store()
    tasks = OnboardingRepository(store)
    try:
        record = ReviewService(
            store,
            tasks,
            PublicationRepository(store),
            publish_immediately=False,
        ).review(
            task_id, **body.model_dump()
        )
        return _task_payload(tasks.get(task_id), store=store, review=record.__dict__)
    except (KeyError, ReviewConflict) as exc:
        _raise_service_error(exc)


@router.get("/companies/{ticker}/quality-report")
def quality_report(
    ticker: str,
    security_id: str | None = None,
    publication_id: str | None = None,
):
    store = _store()
    try:
        security = CompanyRegistry(store).resolve(ticker, security_id)
        context = PublicationRepository(store).context(
            security.company_id, publication_id
        )
    except CompanyRegistryError as exc:
        _raise_service_error(exc)
    except PublicationConflict as exc:
        raise HTTPException(404, _detail(exc.code, str(exc))) from exc
    publication = store.query_one(
        "SELECT quality_report_id, review_id, published_at FROM publication WHERE publication_id=?",
        [context.publication_id],
    )
    report = None
    checks = []
    if publication["quality_report_id"]:
        report = store.query_one(
            "SELECT * FROM quality_report WHERE report_id=?",
            [publication["quality_report_id"]],
        )
        checks = store.query(
            "SELECT * FROM company_quality_check WHERE report_id=? ORDER BY check_id, scope_key",
            [publication["quality_report_id"]],
        )
    return {
        "company_id": security.company_id,
        "security_id": security.security_id,
        "publication_id": context.publication_id,
        "profile_id": context.profile_id,
        "published_at": publication["published_at"],
        "review_id": publication["review_id"],
        "report": report,
        "checks": checks,
    }


@router.put("/companies/{ticker}/valuation-profile")
def valuation_profile(ticker: str, body: ValuationProfileRequest):
    store = _store()
    try:
        security = CompanyRegistry(store).resolve(ticker, body.security_id)
        return confirm_valuation_profile(
            store,
            company_id=security.company_id,
            **body.model_dump(),
        )
    except CompanyRegistryError as exc:
        _raise_service_error(exc)
    except ValuationError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": exc.code,
                    "field": exc.field,
                    "message": exc.message,
                }
            },
        )
