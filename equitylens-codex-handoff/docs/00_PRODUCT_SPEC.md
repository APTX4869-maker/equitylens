# EquityLens Product Specification — V3 Freeze

## 1. Product position

EquityLens is a **company research operating system** for U.S. equities. The intended flow is not “read a generated report”; it is a repeatable research workflow that helps a beginner gradually learn how professional fundamental research is performed.

The system should answer three top-level questions:

1. Is this a good business?
2. Is this a good company / management team?
3. Is the current price a reasonable price for the quality and expected future cash flows?

## 2. Research model

Every supported company is analyzed through a stable framework:

- Business model and revenue composition
- Growth
- Profitability
- Financial quality / cash conversion
- Balance-sheet health
- Moat
- Management / governance / capital allocation
- Industry and long-term drivers
- Valuation
- Risks / thesis breakers

The framework is stable; sector-specific metrics and valuation methods can vary.

## 3. Core user journey

### Overview — “What is happening now?”

Show a dashboard containing:

- One-sentence business explanation
- Current quarter / fiscal-year highlights
- Key briefing cards
- Business mix visualization
- Recent operating trend charts
- Quality score summary
- Risk/watch summary
- Suggested next research questions

### Business mix — “Where does the money come from?”

- Segment/product revenue composition chart
- Click-to-drill-down segment detail
- Segment revenue and growth trend
- Segment-specific disclosure status
- Drivers and risks
- If segment profitability is not disclosed, display `Not disclosed` rather than inventing it

### Financial analysis — “Is the business improving or deteriorating?”

Default to the recent 8–12 quarters. Support annual and quarterly modes.

Core interactions:

- metric switcher
- 8/12 quarter range
- current quarter vs previous quarter vs year-ago quarter
- absolute value vs YoY growth vs margins when meaningful
- beginner explanation of each metric
- professional mode with definitions/formulas/source lineage

### Moat — “Why can the company sustain excess returns?”

Moat claims must have evidence and counter-evidence. Recommended categories:

- Network effects
- Switching costs
- Brand
- Cost advantage
- Scale economies
- Intangible assets / IP
- Distribution / ecosystem

### Management — “Should shareholders trust capital allocation and execution?”

See `05_MANAGEMENT_ANALYSIS.md`.

### Valuation — “What does the current price require?”

See `06_VALUATION_ENGINE.md`.

### Risks — “What could falsify the thesis?”

Separate:

- structural risks
- cyclical risks
- execution risks
- financial risks
- regulatory risks
- valuation risks

Each risk should contain severity, confidence, evidence and monitoring indicators where possible.

### AI Research Assistant — “Connect facts and evidence”

AI is an explanation/research layer. It must retrieve existing facts and evidence; it must not generate authoritative financial data.

## 4. Beginner vs professional reading mode

Beginner mode:

- question-first wording (“What does this tell me?”)
- one-sentence conclusion before details
- plain-language metric explanation
- limited metric density
- clear green/amber/red direction without hiding raw numbers

Professional mode:

- expanded metrics
- formulas
- units / periods
- comparison sets
- provenance and calculation metadata
- model parameters

Both modes must show the same underlying facts.

## 5. UX principles

1. **Conclusion -> evidence -> source**, in that order.
2. Every score is decomposable.
3. Every valuation range exposes assumptions.
4. Every number has a provenance route.
5. “Unknown/not disclosed” is a valid and preferable state.
6. Use trend direction and comparisons; do not make users infer everything from isolated values.
7. Avoid false precision.
8. Keep the interface research-oriented, not trading-terminal-oriented.

## 6. Product states that must be visually distinct

- Officially disclosed
- System calculated
- Third-party market data
- Model assumption
- Estimated (only when explicitly enabled)
- Not disclosed / unavailable
- Stale source
- Restated value

## 7. Scope for initial production release

Initial company coverage: AAPL and MSFT.

V0.x is successful when these two companies can be analyzed end-to-end with correct fiscal periods and full lineage. Broad ticker coverage is secondary to correctness.
