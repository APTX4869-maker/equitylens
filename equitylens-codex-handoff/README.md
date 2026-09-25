# EquityLens — Codex Development Handoff

> Version: Product/UX V3 freeze · 2026-08-30

EquityLens is a local-first U.S. equity research system designed for an investor who wants professional research depth but needs beginner-friendly explanations of financial statements and valuation concepts.

The product is **not** a “type a ticker and let an LLM write a report” application. Its core design principle is:

> **Facts come from authoritative data sources; calculations come from deterministic code; opinions come from evidence-backed research/LLM layers.**

## Start here

1. Read `CODEX_START_HERE.md`.
2. Open `reference/equitylens_demo_v3.html` in a browser. Treat its navigation and interactions as the approved V3 product reference.
3. Read the architecture/data docs in `docs/` before implementing backend code.
4. Implement the phases in `docs/08_IMPLEMENTATION_PLAN.md` in order.
5. Do not wire fake/mock values into production APIs. Mock data is allowed only in explicitly named fixtures/tests/demo mode.

## Package contents

- `reference/equitylens_demo_v3.html` — approved interactive front-end reference.
- `docs/00_PRODUCT_SPEC.md` — product goals and information architecture.
- `docs/01_FRONTEND_UX_SPEC.md` — front-end interaction rules and beginner/pro modes.
- `docs/02_SYSTEM_ARCHITECTURE.md` — target architecture and module boundaries.
- `docs/03_DATA_SOURCES_AND_PROVENANCE.md` — source hierarchy, lineage and anti-hallucination rules.
- `docs/04_FINANCIAL_DATA_MODEL.md` — canonical facts, fiscal-period resolver, TTM/restatement rules.
- `docs/05_MANAGEMENT_ANALYSIS.md` — management/governance research framework.
- `docs/06_VALUATION_ENGINE.md` — DCF, reverse DCF, relative valuation and confidence rules.
- `docs/07_API_CONTRACT.md` — proposed REST contracts and provenance payloads.
- `docs/08_IMPLEMENTATION_PLAN.md` — staged Codex implementation plan.
- `docs/09_ACCEPTANCE_CRITERIA.md` — acceptance tests and correctness gates.
- `spec/schema.sql` — initial DuckDB/SQLite logical schema.
- `spec/metric_catalog.yaml` — initial canonical metrics and formulas.
- `spec/source_registry.yaml` — authoritative source registry.
- `spec/management_rubric.yaml` — scoring rubric for management analysis.
- `spec/openapi_stub.yaml` — initial API surface.

## Recommended stack

- Frontend: Next.js + TypeScript + Tailwind + shadcn/ui + ECharts.
- Backend: Python + FastAPI + Pydantic + httpx.
- Analytics: Polars + DuckDB + Parquet.
- Metadata/local app state: SQLite is acceptable; a single DuckDB database is also acceptable for V0.x if responsibilities remain explicit.
- Parsing: lxml/BeautifulSoup for HTML, XBRL/iXBRL parser layer behind an interface.
- Tests: pytest + Playwright.
- Packaging: Docker Compose only after local development flow works.

## Non-negotiable constraints

- LLMs must never create or silently “repair” financial facts.
- Every displayed fact/derived metric must expose provenance.
- Every valuation price/range must expose assumptions and calculation version.
- Missing segment/profitability disclosure must be shown as **not disclosed**, not estimated unless the user explicitly enables an estimate and it is visibly labeled.
- Historical valuation must be point-in-time safe; do not use future-restated fundamentals against historical prices without a visible warning.
- SEC automated access must identify the application and respect the SEC fair-access policy.
