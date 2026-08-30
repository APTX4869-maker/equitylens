# CODEX START HERE

You are implementing EquityLens from an approved V3 product prototype.

## 1. Product authority

`reference/equitylens_demo_v3.html` is the **UI/interaction specification**, not production code. Rebuild it using the target stack; do not redesign the information architecture unless a requirement is technically impossible.

Approved primary navigation:

1. Company Overview
2. Business / Segment Mix
3. Financial Analysis
4. Moat
5. Management
6. Valuation
7. Risks
8. AI Research Assistant

The redundant horizontal page navigation was intentionally removed. The horizontal area is a research toolbar (period, reading mode, comparison, latest filing, etc.).

## 2. Build order — do not start with AI

Implement in this order:

1. Company identity + SEC ingestion.
2. Immutable raw source storage + provenance.
3. Canonical financial facts.
4. Fiscal-period resolver and standalone quarterly data.
5. Derived metrics and trend APIs.
6. Frontend overview/business/financial pages with real AAPL and MSFT data.
7. Segment extraction.
8. Market data + valuation engine.
9. Proxy/Form 4 management data.
10. Earnings-call evidence / Promise Tracker.
11. AI Research Assistant last.

## 3. Anti-hallucination rule

The following is forbidden:

```text
LLM reads a filing -> returns a number -> number is persisted as a financial fact
```

The allowed pattern is:

```text
SEC/IR source -> parser -> raw fact -> normalized canonical fact -> deterministic metric -> UI
                                                           \
                                                            -> evidence-backed LLM explanation
```

If a value cannot be obtained with sufficient confidence, return `null` plus a reason such as `NOT_DISCLOSED`, `AMBIGUOUS_XBRL_CONTEXT`, or `SOURCE_UNAVAILABLE`.

## 4. Provenance requirement

A numeric API response is incomplete unless it can ultimately answer:

- Which provider/source supplied it?
- Which filing/document?
- Which accession number / URL?
- Which XBRL concept or table/line?
- What reporting period/context?
- Was it raw, normalized, calculated, estimated, or assumed?
- Which formula/model version produced it?
- When was the source fetched?

## 5. V0.1 definition of done

For AAPL and MSFT, the backend must return verified annual and standalone quarterly values for at least:

- Revenue
- Gross profit
- Operating income
- Net income
- Cash / cash equivalents
- Total assets
- Total debt (when available with unambiguous mapping)
- Stockholders' equity
- Operating cash flow
- Capital expenditures
- Free cash flow
- Basic/diluted EPS
- Basic/diluted weighted-average shares

Each must link back to a filing/source. Quarterly cash-flow values must not accidentally use YTD figures as standalone quarter values.

Only after these checks pass should you connect more V3 UI modules.
