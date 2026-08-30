# Acceptance Criteria and Correctness Gates

## A. Source integrity

- [ ] Raw fetched documents are persisted before normalization.
- [ ] SHA-256 and fetched timestamp are stored.
- [ ] SEC source requests identify the application and respect rate limits.
- [ ] A source URL is available for every SEC fact shown to the user.
- [ ] Production mode never silently falls back to demo/mock values.

## B. Financial correctness

For AAPL and MSFT golden periods:

- [ ] annual revenue matches official 10-K
- [ ] annual operating income matches official 10-K
- [ ] annual net income matches official 10-K
- [ ] annual OCF and CapEx match official cash-flow statement
- [ ] quarterly income-statement values match official 10-Q/earnings tables
- [ ] Q2/Q3/Q4 cash-flow standalone values are not confused with YTD figures
- [ ] TTM duration metrics equal the sum of four standalone quarters
- [ ] instant balance-sheet metrics use latest quarter-end value and are never summed
- [ ] units/signs are normalized consistently

Any mismatch blocks release of the affected metric.

## C. Provenance

- [ ] raw fact -> normalized fact mapping is inspectable
- [ ] calculated metric -> all input facts are inspectable
- [ ] formula/version are shown
- [ ] restatement view is explicit
- [ ] point-in-time query is tested for at least one historical date

## D. Segment data

- [ ] business mix labels accurately reflect issuer disclosure hierarchy
- [ ] segment/product revenue source is inspectable
- [ ] missing profitability shows `NOT_DISCLOSED`
- [ ] no total-company margin is copied into a segment without disclosure

## E. Management

- [ ] executive/board data have proxy/filing sources
- [ ] Form 4 transactions link to filing
- [ ] management numeric score decomposes into rubric subcriteria
- [ ] score is unavailable when evidence coverage is insufficient
- [ ] Promise Tracker item has source span/timestamp and verification metric

## F. Valuation

- [ ] changing DCF assumptions reruns the full formula
- [ ] WACC > terminal growth validation exists
- [ ] fair value can be reproduced from persisted run inputs
- [ ] sensitivity matrix recalculates, not scales, the base output
- [ ] reverse DCF uses root solving and exposes fixed assumptions
- [ ] current market price includes provider and timestamp
- [ ] reference price range is labeled research reference, not target price
- [ ] historical multiples use point-in-time-safe fundamentals or display a bias warning

## G. AI

- [ ] AI cannot write canonical facts
- [ ] factual claims contain resolvable evidence IDs
- [ ] unsupported claims are removed/labeled
- [ ] AI explanation never changes the underlying displayed financial value

## H. Frontend regression

- [ ] all eight left-nav tabs function
- [ ] beginner/pro mode uses same data
- [ ] segment donut drilldown works
- [ ] financial metric switching works
- [ ] source drawer works
- [ ] DCF controls update deterministically
- [ ] no uncaught browser errors in Playwright smoke tests
