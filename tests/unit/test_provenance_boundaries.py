from __future__ import annotations


def test_legacy_derived_identity_cannot_resolve_inside_reviewed_publication(monkeypatch):
    from equitylens.api import routes

    class Store:
        def query_one(self, query, _params):
            assert "dataset_version" in query
            return {"parser_version": "issuer-profile.v2"}

    def fail_live_recompute(*_args, **_kwargs):
        raise AssertionError("reviewed publication must not recompute from live tables")

    monkeypatch.setattr(routes, "MetricEngine", fail_live_recompute)

    node = routes._build_derived_node(
        Store(),
        "derived:0000320193:OPERATING_MARGIN:quarterly:2026-06-30",
        3,
        set(),
        "reviewed-dataset",
    )

    assert node is None
