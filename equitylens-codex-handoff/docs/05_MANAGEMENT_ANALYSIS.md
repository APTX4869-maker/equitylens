# Management and Governance Analysis

## 1. Research question

The management tab should answer:

> Is this team strategically competent, disciplined in capital allocation, aligned with long-term shareholders, credible in its promises, and governed well enough to sustain performance?

It is not a biography page.

## 2. Six dimensions

1. **Strategy & execution**
2. **Capital allocation**
3. **Shareholder alignment**
4. **Promise delivery / credibility**
5. **Operating discipline**
6. **Governance / succession**

A 0–100 summary score is allowed only as a compressed UI representation of a deterministic rubric with evidence coverage.

## 3. Primary data sources

### 10-K / 10-Q / 8-K

Use for strategy narrative, operating execution, material acquisitions, risk changes and financial consequences.

### DEF 14A proxy statement

Use for:

- named executive officers
- board composition
- executive ownership
- Compensation Discussion & Analysis
- Summary Compensation Table
- equity awards
- pay-versus-performance
- incentive metrics
- governance/succession disclosures where available

### Forms 3/4/5

Use for beneficial-ownership changes/insider transactions. Form 4 is officially described by the SEC as the statement of changes in beneficial ownership.

### Earnings calls / prepared remarks

Use for Promise Tracker and management explanations. Every promise item requires a source span or timestamp.

## 4. Strategy Track Record

Represent an important decision as:

```text
strategy_event_id
decision_date
title
management_claim
evidence_ids
expected_outcome
measurement_metrics
review_date
observed_outcome
status: SUCCESS | MIXED | FAILURE | PENDING
```

Examples of decision types:

- major acquisition
- cloud/AI infrastructure investment
- major product/platform shift
- distribution change
- restructuring
- capital-return policy change

## 5. Capital Allocation Quality

First answer “where did cash go?”

- R&D
- CapEx
- M&A
- buybacks
- dividends
- debt reduction/issuance

Then answer “did it work?” using trends such as:

- revenue CAGR
- FCF CAGR
- ROIC / incremental return metrics when reliable
- share count reduction
- acquisition impairment / write-off evidence
- margin trend

Avoid a simplistic rule that high CapEx is bad. Judge spending in relation to subsequent economics.

## 6. Shareholder Alignment

Important metrics:

- gross repurchases
- SBC
- diluted share count trend
- net share-count reduction/dilution
- executive ownership
- incentive metrics
- buyback price discipline when data are available

Do not equate “large repurchases” with shareholder value if share count does not meaningfully decline.

## 7. Promise Tracker

Create promises only when they are reasonably testable.

Required fields:

```text
promise_id
company_id
source_document_id
source_span_id
speaker
statement_date
promise_text
normalized_claim
verification_metrics[]
verification_deadline
status: PENDING | DELIVERED | PARTIAL | MISSED | NOT_VERIFIABLE
review_evidence_ids[]
```

The LLM may propose candidate promises; a rules/validation step must confirm that the claim is testable and tied to evidence before persistence.

“Historical delivery rate” should exclude `NOT_VERIFIABLE` items and show sample size.

## 8. Scoring rules

See `spec/management_rubric.yaml`.

Rules:

- scoring uses documented subcriteria and weights
- score unavailable if evidence coverage is below a minimum threshold
- each subscore displays evidence count and freshness
- qualitative LLM text can explain a score but not determine the numeric score directly

## 9. Current watch items

Management page should end with 2–5 forward-looking items derived from unresolved strategic promises, capital-allocation questions, succession issues or governance risks.

Each watch item must contain a future observable signal so it can be revisited next quarter.
