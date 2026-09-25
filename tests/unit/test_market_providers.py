"""Unit tests: market provider adapters parse real captured payloads (M8).

Payloads under tests/fixtures/market/ are verbatim provider responses captured
2026-09-03. Parsing is pure, so these tests never touch the network (Nasdaq
requests are respx-mocked; Tencent parsing is a pure function on the body).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from equitylens.market.model import ProviderError
from equitylens.market.providers import (
    NasdaqProvider, parse_nasdaq_snapshot, parse_tencent_body, snapshot_bytes,
)
from equitylens.market.service import _REPLAY
from equitylens.market.sources import get_config

_FX = Path(__file__).parent.parent / "fixtures" / "market"


def _nasdaq_payloads() -> tuple[dict, dict]:
    return (
        json.loads((_FX / "nasdaq" / "aapl_info.json").read_text()),
        json.loads((_FX / "nasdaq" / "aapl_summary.json").read_text()),
    )


@respx.mock
def test_nasdaq_provider_parses_real_payload():
    info, summary = _nasdaq_payloads()
    base = get_config().providers["nasdaq"].endpoint
    info_url = f"{base}/api/quote/AAPL/info?assetclass=stocks"
    sum_url = f"{base}/api/quote/AAPL/summary?assetclass=stocks"
    respx.get(url=info_url).mock(return_value=httpx.Response(200, json=info))
    respx.get(url=sum_url).mock(return_value=httpx.Response(200, json=summary))

    quote = NasdaqProvider().fetch("AAPL", "AAPL")
    p = info["data"]["primaryData"]
    s = summary["data"]["summaryData"]
    assert quote.price == pytest.approx(float(p["lastSalePrice"].replace("$", "")))
    assert quote.observed_at == p["lastTradeTimestamp"]
    assert quote.market_cap == pytest.approx(float(s["MarketCap"]["value"].replace(",", "")))
    assert quote.prev_close == pytest.approx(float(s["PreviousClose"]["value"].replace("$", "")))
    assert quote.source_label == "Nasdaq"
    assert quote.raw_payload["info"] == info


def test_nasdaq_snapshot_replay_roundtrip():
    info, summary = _nasdaq_payloads()
    snapshot = {"request_url": "https://api.nasdaq.com/api/quote/AAPL/info?assetclass=stocks",
                "info": info, "summary": summary}
    quote = parse_nasdaq_snapshot(snapshot, "AAPL")
    assert quote.price > 0
    assert quote.market_cap > 0
    assert quote.provider == "nasdaq"


def test_tencent_parser_real_body():
    body = (_FX / "tencent" / "aapl.txt").read_text()
    quote = parse_tencent_body(body, "AAPL")
    f = body.split("~")
    assert quote.price == pytest.approx(float(f[3]))
    assert quote.prev_close == pytest.approx(float(f[4]))
    assert quote.observed_at == f[30]
    assert quote.market_cap == pytest.approx(float(f[44]) * 1e8)
    assert quote.name == f[46]
    assert quote.source_label == "腾讯行情"


def test_tencent_snapshot_replay_roundtrip():
    body = (_FX / "tencent" / "aapl.txt").read_text()
    raw = {"request_url": "https://qt.gtimg.cn/q=usAAPL", "body": body}
    replay = _REPLAY["tencent"]
    quote = replay(raw, "AAPL")
    assert quote.price == pytest.approx(float(body.split("~")[3]))
    # snapshot_bytes round-trip keeps the verbatim body
    snap = json.loads(snapshot_bytes(quote).decode("utf-8"))
    assert snap["body"] == body


def test_tencent_missing_payload_raises():
    with pytest.raises(ProviderError):
        parse_tencent_body('v_usAAPL="";', "AAPL")


@respx.mock
def test_nasdaq_missing_price_raises():
    base = get_config().providers["nasdaq"].endpoint
    info_url = f"{base}/api/quote/AAPL/info?assetclass=stocks"
    sum_url = f"{base}/api/quote/AAPL/summary?assetclass=stocks"
    respx.get(url=info_url).mock(return_value=httpx.Response(
        200, json={"data": {"primaryData": {"lastSalePrice": "--"}}}))
    respx.get(url=sum_url).mock(return_value=httpx.Response(200, json={"data": {}}))
    with pytest.raises(ProviderError):
        NasdaqProvider().fetch("AAPL", "AAPL")
