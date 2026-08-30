# Data Sources, Provenance and Anti-Hallucination Policy

## 1. Source hierarchy

### Tier A — regulator / primary filing source

**SEC EDGAR / data.sec.gov** is the default source of truth for U.S.-listed issuer filings and XBRL facts.

Official references:

- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC Developer Resources / fair access: https://www.sec.gov/about/developer-resources
- SEC Inline XBRL: https://www.sec.gov/data-research/structured-data/inline-xbrl
- SEC Forms Index: https://www.sec.gov/submit-filings/forms-index

Important SEC API properties (verified 2026-08-30):

- `data.sec.gov` public submissions/XBRL data APIs do not require an API key.
- Submissions and XBRL JSON are updated throughout the day as filings are disseminated.
- `companyfacts` aggregates standard taxonomy facts applying to the entire filing entity; company custom-taxonomy facts and dimensional segment details may require direct filing/iXBRL parsing.
- Bulk ZIP archives are available for scale.
- SEC fair-access guidelines cap automated access at no more than 10 requests/sec; EquityLens should default far lower (e.g. 2 req/sec) with caching/backoff and an identifying User-Agent.

Core endpoints:

```text
https://data.sec.gov/submissions/CIK##########.json
https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
https://data.sec.gov/api/xbrl/companyconcept/CIK##########/{taxonomy}/{concept}.json
https://data.sec.gov/api/xbrl/frames/{taxonomy}/{concept}/{unit}/{period}.json
```

### Tier B — company official Investor Relations

Use for earnings releases, prepared remarks, webcasts, supplemental segment tables and investor presentations.

Examples:

- Apple Investor Relations: https://investor.apple.com/
- Microsoft Investor Relations: https://www.microsoft.com/en-us/investor/
- Microsoft SEC filings: https://www.microsoft.com/en-us/investor/sec-filings

Company IR is important when an officially published KPI/table is not represented cleanly in SEC standard `companyfacts`.

### Tier C — official macro/government sources

- U.S. Treasury interest-rate statistics: https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics
- FRED API: https://fred.stlouisfed.org/docs/api/fred/series_observations.html

Use these for risk-free rates and macro context. Persist observation date and retrieval/vintage metadata.

### Tier D — configured market-data provider

SEC is not a price feed. Market data must come from a provider abstraction with:

- provider name
- exchange/instrument identifier
- timestamp/timezone
- adjusted/unadjusted flag
- corporate-action handling
- license/storage constraints

Do not silently use an unconfigured scraper in production. Development-only adapters must be visibly marked.

## 2. Form-to-feature mapping

| Form/source | Primary EquityLens use |
|---|---|
| 10-K | annual statements, business, segments, risks, MD&A |
| 10-Q | quarterly statements, YTD cash flow, segment updates, MD&A |
| 8-K | earnings releases/material events when furnished/filed |
| DEF 14A | executives, board, ownership, compensation, pay-vs-performance, governance |
| Forms 3/4/5 | insider beneficial ownership / changes |
| 13D/13G | significant ownership context |
| IR earnings release | official current-quarter tables/KPIs |
| IR prepared remarks/webcast | management narrative / Promise Tracker |

SEC describes Form 4 as the statement of changes in beneficial ownership. Proxy statements commonly contain Compensation Discussion & Analysis and executive compensation tables.

## 3. Data classification

Every returned datum must have a classification:

```text
DISCLOSED          raw fact directly from authoritative disclosure
NORMALIZED         disclosed fact mapped to canonical concept/period
CALCULATED         deterministic formula from sourced facts
MARKET_DATA        provider quote/history
ASSUMPTION         valuation/model input
ESTIMATED          explicit model estimate; never disguised as disclosed
NOT_DISCLOSED      source does not disclose it
UNAVAILABLE        technical/source unavailable
AMBIGUOUS          multiple plausible source contexts; human/rule review required
```

## 4. Provenance model

Minimum provenance for disclosed/normalized facts:

- source document id
- provider
- filing form
- accession number when SEC
- filing/published timestamp
- source URL
- concept/tag/table locator
- XBRL context/dimensions where applicable
- unit
- period start/end / instant date
- parser/mapping version
- fetched timestamp
- content hash

Calculated values additionally require:

- formula id/version
- IDs of every input fact
- calculation timestamp

Valuation outputs additionally require:

- source snapshot id
- market quote id
- assumption set id
- model version

## 5. Source snapshots and immutability

Store the original response/document before parsing. Compute SHA-256. Do not overwrite a raw source artifact; create a new fetched version.

Recommended path:

```text
data/raw/sec/{cik}/{accession}/primary-document.html
data/raw/sec/{cik}/{accession}/companyfacts-snapshot.json
data/raw/ir/{ticker}/{published_date}/{document}.html
```

## 6. Restatements and point-in-time data

Maintain two query semantics:

- `LATEST_RESTATED`: best current view of historical company results.
- `POINT_IN_TIME(as_of)`: facts available to an investor at a historical date.

Historical valuation/backtests should use point-in-time facts. Mixing a 2020 price with a fact restated or learned in 2026 creates look-ahead bias.

## 7. Segment disclosure policy

`companyfacts` is insufficient for many segment/product facts because it focuses on standard taxonomy, entity-wide facts. Segment extraction should try, in order:

1. dimensional facts in filing iXBRL/XBRL
2. structured official filing tables
3. official IR supplemental table
4. no value (`NOT_DISCLOSED`)

Never infer segment profit from total-company margins.

## 8. Earnings-call/transcript policy

Priority:

1. official written transcript/prepared remarks
2. official webcast/audio transcribed locally, labeled `TRANSCRIBED_FROM_OFFICIAL_AUDIO`
3. licensed third-party transcript, labeled with provider

Do not label an automatically transcribed webcast as an “official transcript.”

## 9. LLM policy

LLM may:

- explain a metric
- summarize evidence
- generate a research claim with cited evidence
- identify possible follow-up questions

LLM may not:

- create missing revenue/earnings/segment numbers
- silently choose between ambiguous XBRL contexts
- overwrite canonical facts
- fabricate a source citation

Structured LLM output must include evidence IDs and confidence; claims with no evidence cannot be promoted to the final research summary.
