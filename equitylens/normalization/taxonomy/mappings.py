"""Versioned canonical mapping registry.

Loads config/mappings/canonical_mappings.yaml. UI code must never depend on
raw SEC tags — everything flows through a MappingRule here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from equitylens.config import CONFIG_DIR, MAPPING_VERSION

DEFAULT_PATH = CONFIG_DIR / "mappings" / "canonical_mappings.yaml"


@dataclass(frozen=True)
class MappingRule:
    canonical_metric: str
    metric_type: str  # duration | instant
    unit_family: str  # currency | shares | currency_per_share
    concepts: tuple[str, ...]
    rule_id: str
    sign: str = "as_reported"  # as_reported | outflow_positive
    derive_standalone_quarter: bool = False

    def match(self, taxonomy: str, concept: str) -> bool:
        return f"{taxonomy}:{concept}" in self.concepts


class MappingRegistry:
    def __init__(self, path: Path = DEFAULT_PATH):
        raw = yaml.safe_load(Path(path).read_text())
        self.version = raw.get("version")
        self._rules: dict[str, MappingRule] = {}
        self._concept_index: dict[str, MappingRule] = {}
        derive_set = set(raw.get("derive_standalone_quarter", []) or [])
        for name, spec in raw["canonical_facts"].items():
            concepts = tuple(spec["concepts"])
            rule = MappingRule(
                canonical_metric=name,
                metric_type=spec["type"],
                unit_family=spec["unit_family"],
                concepts=concepts,
                rule_id=f"{name.lower()}.usgaap.v{self.version}",
                sign=spec.get("sign", "as_reported"),
                derive_standalone_quarter=name in derive_set,
            )
            self._rules[name] = rule
            for c in concepts:
                self._concept_index[c] = rule

    @property
    def mapping_version(self) -> str:
        return MAPPING_VERSION

    def find(self, taxonomy: str, concept: str) -> MappingRule | None:
        return self._concept_index.get(f"{taxonomy}:{concept}")

    def metric(self, name: str) -> MappingRule | None:
        return self._rules.get(name)

    def all_metrics(self) -> list[str]:
        return list(self._rules.keys())
