"""Source document model — every raw artifact EquityLens captures.

A source_document row is written BEFORE any parsing so that provenance always
resolves to an immutable, hash-verified snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class SourceDocument:
    provider: str
    document_type: str  # SUBMISSIONS_SNAPSHOT | COMPANYFACTS_SNAPSHOT | FILING_DOCUMENT
    source_url: str
    content_sha256: str
    local_path: str
    company_id: str | None = None
    form_type: str | None = None
    accession_number: str | None = None
    published_at: str | None = None
    filed_at: str | None = None
    fetched_at: str = field(default_factory=utcnow_iso)
    parser_version: str | None = None
    metadata_json: dict = field(default_factory=dict)

    @property
    def source_document_id(self) -> str:
        sha = self.content_sha256[:10]
        kind = self.document_type.lower().replace("_snapshot", "")
        return f"src_{self.provider.lower()}_{self.company_id}_{kind}_{sha}"

    def to_row(self) -> dict:
        import json

        return {
            "source_document_id": self.source_document_id,
            "company_id": self.company_id,
            "provider": self.provider,
            "document_type": self.document_type,
            "form_type": self.form_type,
            "accession_number": self.accession_number,
            "published_at": self.published_at,
            "filed_at": self.filed_at,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "content_sha256": self.content_sha256,
            "local_path": str(self.local_path),
            "parser_version": self.parser_version,
            "metadata_json": json.dumps(self.metadata_json, ensure_ascii=False),
        }
