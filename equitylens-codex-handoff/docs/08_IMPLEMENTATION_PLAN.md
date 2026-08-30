# EquityLens Implementation Plan for Codex

## Goal

Replace the V3 mock-data prototype with a local-first, evidence-first research application, starting with AAPL/MSFT and authoritative SEC data.

## Phase 0 — Repository + golden fixtures

Deliverables:

- monorepo structure
- FastAPI health endpoint
- Next.js shell matching V3 navigation
- pytest/Playwright setup
- saved official SEC fixtures for a small number of AAPL/MSFT filings

Acceptance: tests run locally with one command for backend and frontend.

## Phase 1 — SEC company/filer ingestion

Implement:

- ticker/CIK registry
- SEC HTTP client with identifying User-Agent, rate limiter, cache and retry/backoff
- Submissions API adapter
- Company Facts adapter
- source_document/raw-file persistence + SHA-256
- ingestion_run logging

Acceptance:

- syncing AAPL/MSFT persists source snapshots
- second sync avoids unnecessary downloads
- source metadata are queryable

## Phase 2 — Canonical facts + fiscal-period resolver

Implement:

- raw XBRL fact parser
- canonical mapping rules
- duration vs instant types
- fiscal-year / quarter resolution
- YTD -> standalone quarter derivation
- restatement selection semantics
- rejection/ambiguity reasons

Golden tests:

- AAPL/MSFT annual revenue/net income match official statement
- latest Q1/Q2/Q3 standalone revenue/profit match official statement
- Q2/Q3 OCF are correctly derived from cumulative YTD values where necessary

Do not proceed until these pass.

## Phase 3 — Metric engine + real Financial UI

Implement metrics:

- growth
- gross/operating/net margins
- FCF / FCF margin
- debt/net cash measures
- ROE
- other V3 metrics only when definitions are locked

Implement provenance endpoint and source drawer.

Wire V3:

- overview KPI cards
- 8-quarter financial trends
- beginner metric drawer
- annual/quarterly/TTM switching

Acceptance: no mock financial values remain in production AAPL/MSFT financial pages.

## Phase 4 — Segment/business mix

Implement direct filing/iXBRL parsing for dimensional facts and official tables.

Requirements:

- distinguish reported segment vs product category
- mapping configuration per issuer when necessary
- quarterly/annual segment trend
- explicit `NOT_DISCLOSED` for missing segment profit

Wire V3 business mix drilldown.

## Phase 5 — Market data + valuation

Implement provider interface first; configure one real provider separately.

Implement:

- price history and current/stale quote semantics
- split/corporate-action handling
- historical point-in-time multiple calculations
- Treasury risk-free rate adapter
- versioned valuation assumption store
- FCFF DCF engine
- Bear/Base/Bull
- sensitivity matrix
- reverse DCF
- valuation-run persistence

Wire V3 valuation page.

Acceptance: every valuation output is reproducible from stored snapshot and assumptions.

## Phase 6 — Management / governance

Implement parsers/research records for:

- 10-K/10-Q management/strategy evidence
- DEF 14A leaders/compensation/governance
- Form 4 insider transactions
- capital allocation time series
- management rubric score with evidence coverage

Wire V3 management scorecard, capital allocation and shareholder alignment.

## Phase 7 — Earnings evidence + Promise Tracker

Implement:

- official prepared remarks/webcast metadata
- evidence spans/timestamps
- candidate promise extraction
- validation workflow
- future verification records

Do not compute a historical promise-delivery percentage until there is a meaningful sample and all items have source evidence.

## Phase 8 — Risks, moat and AI Research Assistant

Add evidence retrieval and structured claims.

Rules:

- AI reads canonical facts/evidence only
- answer includes evidence IDs
- unsupported claim is dropped or clearly labeled hypothesis
- AI has no permission to write canonical facts

## Phase 9 — Hardening

- data freshness UI
- offline cache behavior
- source parsing diagnostics
- more golden companies before broad ticker expansion
- backup/export of notes/research state
- Docker Compose if useful

## Suggested first coding milestone

Codex should target this demonstration before any broader feature work:

```text
Search AAPL -> Overview -> Financial Analysis -> click Revenue -> View Source
```

The source drawer must show the exact SEC filing/accession/concept/period that produced the displayed value.
