"""Central configuration and path helpers for EquityLens."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("EQUITYLENS_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.environ.get("EQUITYLENS_DB_PATH", DATA_DIR / "equitylens.duckdb"))
CONFIG_DIR = ROOT / "config"
SPEC_DIR = ROOT / "spec"
FIXTURES_DIR = ROOT / "tests" / "fixtures"

# Versioned pipeline components (provenance metadata)
PARSER_VERSION = "sec-companyfacts.v1"
MAPPING_VERSION = "canonical-mappings.v4"
METRIC_ENGINE_VERSION = "metric-engine.v2"
MARKET_SOURCES_VERSION = "market-sources.v1"

# SEC EDGAR public data APIs
SEC_HTTP = "https://data.sec.gov"
SEC_SUBMISSIONS_URL = SEC_HTTP + "/submissions/"
SEC_COMPANYFACTS_URL = SEC_HTTP + "/api/xbrl/companyfacts/"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/"
SEC_MAX_RPS = 2.0  # SEC fair-access cap is 10/s; we stay far below it.


def user_agent() -> str:
    """Identifying User-Agent required by SEC fair-access policy."""
    return os.environ.get(
        "EQUITYLENS_USER_AGENT",
        "EquityLens/0.1 (local research tool; contact@example.com)",
    )
