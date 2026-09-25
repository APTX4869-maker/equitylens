"""Strict, bounded YAML loading for reviewed issuer Profile v2 imports."""

from __future__ import annotations

from typing import Any

import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken

from equitylens.issuers.profile import IssuerProfileV2


MAX_YAML_BYTES = 512 * 1024
MAX_DEPTH = 20
MAX_NODES = 20_000
MAX_SCALAR_BYTES = 64 * 1024


class StrictProfileLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: StrictProfileLoader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError("profile mapping keys must be strings")
        if key == "<<":
            raise ValueError("YAML merge keys are not allowed")
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictProfileLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _check_shape(value: Any, *, depth: int = 1, count: list[int] | None = None) -> None:
    count = count if count is not None else [0]
    count[0] += 1
    if count[0] > MAX_NODES:
        raise ValueError(f"profile YAML exceeds {MAX_NODES} nodes")
    if depth > MAX_DEPTH:
        raise ValueError(f"profile YAML exceeds maximum depth {MAX_DEPTH}")
    if isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_SCALAR_BYTES:
            raise ValueError(f"profile YAML scalar exceeds {MAX_SCALAR_BYTES} bytes")
        if "__REVIEW_REQUIRED__" in value:
            raise ValueError("profile YAML still contains a review-required placeholder")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_shape(key, depth=depth + 1, count=count)
            _check_shape(item, depth=depth + 1, count=count)
    elif isinstance(value, list):
        for item in value:
            _check_shape(item, depth=depth + 1, count=count)


def load_strict_profile_yaml(text: str) -> IssuerProfileV2:
    if not isinstance(text, str):
        raise ValueError("profile YAML must be UTF-8 text")
    if len(text.encode("utf-8")) > MAX_YAML_BYTES:
        raise ValueError(f"profile YAML exceeds {MAX_YAML_BYTES} bytes")
    try:
        for token in yaml.scan(text):
            if isinstance(token, (AnchorToken, AliasToken, TagToken)):
                raise ValueError("YAML anchors, aliases, and explicit tags are not allowed")
        documents = list(yaml.load_all(text, Loader=StrictProfileLoader))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid profile YAML: {exc}") from exc
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise ValueError("profile YAML must contain exactly one mapping document")
    data = documents[0]
    _check_shape(data)
    if data.get("schema_version") != 2:
        raise ValueError("new profile imports require schema_version 2")
    return IssuerProfileV2.model_validate(data)
