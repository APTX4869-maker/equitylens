# System Architecture

## 1. Architecture principles

- Local-first and single-user initially.
- Modular monolith before microservices.
- Deterministic financial computation.
- Immutable raw source capture.
- Reproducible normalized facts and valuation runs.
- LLM at the final research/explanation layer.

## 2. Logical architecture

```text
Authoritative Sources
  SEC EDGAR / data.sec.gov
  Company IR
  Configured market-data provider
  Treasury / FRED
          |
          v
Ingestion Adapters
          |
          v
Immutable Raw Store (JSON/HTML/XBRL + hash)
          |
          v
Parsing / Normalization
  fiscal-period resolver
  taxonomy mapping
  segment parser
          |
          v
Canonical Fact Store
          |
          +----------------------+
          |                      |
          v                      v
Financial Metric Engine     Document/Evidence Engine
          |                      |
          +-----------+----------+
                      v
             Valuation / Research
                      |
                      v
                  FastAPI
                      |
                      v
               Next.js Frontend
                      |
                      v
          Evidence-backed AI layer
```

## 3. Recommended repository layout

```text
equitylens/
  apps/
    web/                       # Next.js
  services/
    api/                       # FastAPI entrypoint
  equitylens/
    domain/
      companies/
      filings/
      facts/
      metrics/
      segments/
      management/
      valuation/
      evidence/
    ingestion/
      sec/
      ir/
      market/
      macro/
    normalization/
      taxonomy/
      fiscal_periods/
    storage/
      raw_store.py
      repositories.py
    research/
      retrieval/
      llm/
  config/
    metrics/
    mappings/
    sources/
    management/
    valuation/
  data/
    raw/
    parquet/
    equitylens.duckdb
  tests/
    fixtures/
    unit/
    integration/
    golden/
  docs/
```

## 4. Component boundaries

### SEC ingestion

Responsibilities:

- ticker -> CIK lookup
- submissions retrieval
- companyfacts retrieval
- filing document retrieval
- SEC rate limiting / retries / identification header

Must not calculate financial metrics.

### Raw store

Persist source bytes/text plus metadata before parsing. Source documents must be content-addressable or hash-verified.

### Normalization

Transforms raw facts to canonical concepts. This layer owns mapping versions and fiscal-period semantics.

### Metric engine

Pure deterministic calculations from canonical facts. Prefer functions with explicit inputs and versioned formulas.

### Evidence engine

Stores document chunks/spans and precise source links. Financial source lineage and narrative evidence are related but not the same entity.

### Valuation engine

Takes a versioned snapshot of facts, market data and assumptions, then produces reproducible valuation outputs.

### Research/LLM layer

Reads facts + evidence and produces structured claims. It is not permitted to write canonical financial facts.

## 5. Persistence approach

V0.x:

- raw files under `data/raw/{provider}/{cik}/{accession_or_date}/`
- Parquet for large fact/evidence datasets
- DuckDB for analytical queries
- SQLite only if needed for application state/notes/jobs; avoid duplicating authoritative data without reason

## 6. Background jobs

Initial jobs can be simple CLI/scheduler tasks:

- sync company submissions
- fetch new filings
- normalize facts
- recompute metrics
- refresh market history
- recompute valuation snapshot

Do not add Kafka/Celery unless the local workflow actually needs them.

## 7. Observability

Every ingestion run should capture:

- provider
- URL/request identifier
- HTTP status
- started/finished timestamps
- bytes/hash
- parser version
- number of facts accepted/rejected
- warnings

Expose a developer diagnostics page or CLI command for source/data problems.
