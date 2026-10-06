"""Smoke preflight must not silently skip empty data or mask unrelated errors."""
import importlib.util
from pathlib import Path

import httpx
import pytest
import respx
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("desktop_smoke", Path(__file__).parents[1] / "e2e" / "smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


@respx.mock
def test_published_directory_paginates_and_excludes_unpublished():
    route = respx.get("http://smoke.test/api/v1/companies").mock(side_effect=[
        httpx.Response(200, json={"items": [{"ticker": "NVDA", "publication_id": "p1"}, {"ticker": "AMD"}], "next_cursor": "next"}),
        httpx.Response(200, json={"items": [{"ticker": "KO", "publication_id": "p2"}], "next_cursor": None}),
    ])
    assert [row["ticker"] for row in smoke.published_companies("http://smoke.test/api/v1")] == ["NVDA", "KO"]
    assert route.calls[1].request.url.params["cursor"] == "next"


@respx.mock
def test_empty_directory_is_not_a_zero_check_pass():
    respx.get("http://smoke.test/api/v1/companies").respond(200, json={"items": [{"ticker": "AMD"}], "next_cursor": None})
    with pytest.raises(ValueError, match="No published companies"):
        smoke.published_companies("http://smoke.test/api/v1")


@respx.mock
def test_repeated_cursor_does_not_loop_forever():
    respx.get("http://smoke.test/api/v1/companies").respond(200, json={"items": [], "next_cursor": "same"})
    with pytest.raises(ValueError, match="repeated pagination cursor"):
        smoke.published_companies("http://smoke.test/api/v1")


@respx.mock
def test_directory_http_failure_is_not_a_pass():
    respx.get("http://smoke.test/api/v1/companies").respond(503)
    with pytest.raises(httpx.HTTPStatusError):
        smoke.published_companies("http://smoke.test/api/v1")


@pytest.mark.parametrize("expected,status,url,body,limited", [
    (True, 409, "http://smoke.test/api/v1/companies/KO/valuation-profile/draft", {"error": {"code": "VALUATION_DEFAULT_UNAVAILABLE"}}, True),
    (False, 409, "http://smoke.test/api/v1/companies/KO/valuation-profile/draft", {"error": {"code": "VALUATION_DEFAULT_UNAVAILABLE"}}, False),
    (True, 409, "http://smoke.test/api/v1/companies/KO/valuation-profile/draft", {"error": {"code": "PUBLICATION_CHANGED"}}, False),
    (True, 500, "http://smoke.test/api/v1/companies/KO/valuation-profile/draft", {"error": {"code": "VALUATION_DEFAULT_UNAVAILABLE"}}, False),
    (True, 409, "http://smoke.test/api/v1/companies/KO/valuation/run", {"error": {"code": "VALUATION_DEFAULT_UNAVAILABLE"}}, False),
    (True, 409, "http://smoke.test/api/v1/companies/KO/valuation-profile/draft", {"error": "malformed"}, False),
])
def test_only_expected_missing_defaults_are_a_limitation(expected, status, url, body, limited):
    response = httpx.Response(status, json=body, request=httpx.Request("GET", url))
    observed = SimpleNamespace(status=status, url=url, json=response.json)
    assert smoke.is_expected_draft_block(observed, expected) is limited
