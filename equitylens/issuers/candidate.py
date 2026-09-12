"""Generate evidence-limited profile suggestions without approving them."""

from __future__ import annotations

from typing import Any


def observed_concepts(companyfacts: dict[str, Any]) -> set[str]:
    concepts: set[str] = set()
    for taxonomy, facts in (companyfacts.get("facts") or {}).items():
        for name in facts:
            concepts.add(f"{taxonomy}:{name}")
    return concepts


def build_candidate_profile(
    *, company_id: str, companyfacts: dict[str, Any], common_mapping: dict[str, Any]
) -> dict[str, Any]:
    """Return suggestions only for concepts present in the fixed raw snapshot."""
    available = observed_concepts(companyfacts)
    metrics = {}
    unresolved = []
    for metric, rule in (common_mapping.get("canonical_facts") or {}).items():
        matches = [concept for concept in rule.get("concepts") or [] if concept in available]
        if matches:
            metrics[metric] = {"concepts": matches, "candidate_only": True}
        else:
            unresolved.append(metric)
    return {
        "company_id": company_id,
        "metrics": metrics,
        "unresolved_metrics": unresolved,
        "review_status": "NEEDS_ADAPTATION",
    }
