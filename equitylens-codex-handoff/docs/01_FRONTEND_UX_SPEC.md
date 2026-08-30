# Frontend / UX Specification

## 1. Reference

Open `reference/equitylens_demo_v3.html`. Reproduce the information architecture and interaction semantics, not necessarily the exact CSS.

## 2. Layout

### Left sidebar

Single primary navigation. It is the only page-level navigation.

### Top header

- Global company/ticker/research search
- Company name + ticker + sector/industry
- Market cap / current price when market provider is configured
- Quality/status badges

### Research toolbar

Do **not** repeat the left navigation. Toolbar controls should include appropriate combinations of:

- fiscal period selector
- annual/quarterly
- 5Y/10Y/8Q/12Q
- beginner/professional mode
- comparison company / peer set
- latest filing shortcut
- source freshness status

## 3. Overview page

Recommended vertical order:

1. Quarter/year highlights
2. Key briefing KPI cards
3. Revenue/profit/cash-flow trend chart
4. Business mix donut + segment quick summary
5. Operating signals / quarter-over-quarter direction
6. Cash conversion view
7. Quality score breakdown
8. Risks / watch items

A single viewport should contain enough high-level information to decide what to investigate next.

## 4. Business mix interaction

Clicking a donut segment or legend row selects a segment and updates a detail panel.

Detail panel should display:

- segment name
- TTM or fiscal-year revenue
- revenue share
- YoY growth
- profitability status/value if officially disclosed
- 8-quarter trend where available
- growth drivers
- risks
- source status

Always distinguish between a company-reported segment, product category and an internally mapped analytical grouping.

## 5. Financial trend interaction

Default period = last 8 quarters.

A metric card/chart should support:

- selected metric
- current quarter
- previous quarter
- year-ago quarter
- YoY direction
- one-sentence beginner interpretation
- source/provenance affordance

The user must never see a YTD 6-month or 9-month cash-flow number labeled as a standalone quarter.

## 6. Metric explanation drawer

Clicking a metric opens:

- Chinese name / English name
- What question does it answer?
- Definition
- Formula
- Plain-language example
- Common misuse / warning
- Current company value
- Data status (`DISCLOSED`, `CALCULATED`, etc.)
- “View source” action

## 7. Source drawer

Clicking “View source” should expose the full lineage, e.g.:

```text
ROIC 42.1% — CALCULATED
Formula: NOPAT / Avg Invested Capital
Formula version: roic.v1
Inputs:
  NOPAT ... -> source fact A
  Invested capital ... -> source facts B/C/D
Filing: FY2026 Q3 10-Q
SEC accession: ...
Filed at: ...
Source URL: ...
Fetched at: ...
```

## 8. Management page

Use the V3 management information architecture. All scores are expandable into rubric + evidence.

## 9. Valuation page

Must show:

- current market price and timestamp/provider
- reference value range (not a single target price)
- scenario assumptions
- relative valuation
- DCF model
- sensitivity matrix
- reverse DCF
- confidence/limitations

User-adjustable assumptions must trigger a deterministic recomputation.

## 10. Loading/error states

Provide explicit states:

- source fetch pending
- source fetch failed
- data not disclosed
- data ambiguous
- market provider unavailable
- stale market quote
- valuation unavailable because mandatory inputs are missing

Never replace an error with a fabricated placeholder in production mode.
