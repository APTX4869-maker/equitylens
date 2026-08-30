# Financial Data Model and Period Semantics

## 1. Why a canonical layer is mandatory

Issuer XBRL tags vary by taxonomy version and company extensions. UI code must not depend directly on raw SEC tags.

Example flow:

```text
us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax
        -> mapping rule revenue.usgaap.v1
        -> REVENUE
```

A mapping rule must be versioned and testable.

## 2. Initial canonical facts

Income statement:

- REVENUE
- COST_OF_REVENUE
- GROSS_PROFIT
- OPERATING_INCOME
- PRETAX_INCOME
- INCOME_TAX_EXPENSE
- NET_INCOME
- BASIC_EPS
- DILUTED_EPS
- BASIC_WEIGHTED_AVG_SHARES
- DILUTED_WEIGHTED_AVG_SHARES

Balance sheet:

- CASH_AND_EQUIVALENTS
- SHORT_TERM_INVESTMENTS
- TOTAL_ASSETS
- CURRENT_ASSETS
- CURRENT_LIABILITIES
- SHORT_TERM_DEBT
- LONG_TERM_DEBT
- STOCKHOLDERS_EQUITY
- SHARES_OUTSTANDING

Cash flow:

- OPERATING_CASH_FLOW
- CAPITAL_EXPENDITURES
- DEPRECIATION_AMORTIZATION
- SHARE_BASED_COMPENSATION
- DIVIDENDS_PAID
- SHARE_REPURCHASES

## 3. Duration vs instant facts

Duration facts have start/end dates (revenue, net income, cash flow).

Instant facts have a single balance-sheet date (cash, debt, assets).

Never combine them using the same TTM/quarter logic.

## 4. Fiscal-period resolver

Do not trust `fp` alone. Use filing fiscal-year metadata plus start/end dates and duration.

Represent normalized period as:

```text
fiscal_year
fiscal_quarter: 1|2|3|4|null
period_type: Q_STANDALONE | YTD_6M | YTD_9M | FY | INSTANT
period_start
period_end
```

### Standalone quarter derivation

Cash-flow statements often report cumulative YTD values.

When concept, unit, dimensional context, fiscal year and continuity match:

```text
Q1 = Q1_YTD
Q2 = H1_YTD - Q1_YTD
Q3 = 9M_YTD - H1_YTD
Q4 = FY - 9M_YTD
```

Do not derive when:

- a context/dimension differs
- the fiscal calendar changed incompatibly
- one period is restated and another is not aligned
- units/scales differ unexpectedly
- filing data are missing

In those cases return `AMBIGUOUS` rather than guessing.

## 5. TTM rules

For duration facts:

```text
TTM = Q(t) + Q(t-1) + Q(t-2) + Q(t-3)
```

using standalone normalized quarters.

For instant facts use the latest valid instant value; never sum four balance-sheet quarters.

## 6. Derived metrics

All metrics use versioned formulas. Examples:

```text
GROSS_MARGIN = GROSS_PROFIT / REVENUE
OPERATING_MARGIN = OPERATING_INCOME / REVENUE
NET_MARGIN = NET_INCOME / REVENUE
FCF = OPERATING_CASH_FLOW - CAPITAL_EXPENDITURES
FCF_MARGIN = FCF / REVENUE
NET_DEBT = SHORT_TERM_DEBT + LONG_TERM_DEBT - CASH_AND_EQUIVALENTS - eligible_short_term_investments
ROE = NET_INCOME / average(STOCKHOLDERS_EQUITY)
```

ROIC requires an explicitly documented invested-capital definition; do not present it until the formula and mappings are tested against several issuers.

## 7. Sign conventions

Normalize economic meaning rather than blindly preserving XBRL signs.

Suggested canonical conventions:

- revenue/profit/cash inflow positive
- CapEx stored as positive “cash invested” amount for metric formulas, with raw sign retained separately
- debt positive outstanding balance
- repurchases/dividends positive cash-return amount, raw cash-flow sign retained separately

Store `raw_value` and `normalized_value` separately when sign transformation occurs.

## 8. Units and scales

Canonical facts should store full numeric magnitude in base unit (e.g. USD, shares). Formatting into `$94.0B` belongs to presentation.

Reject or flag facts when incompatible units are mixed.

## 9. Fact selection precedence

When multiple facts appear for the same canonical concept/period, rank with explicit rules such as:

1. same filing/accession relevant to requested view
2. correct fiscal context
3. non-dimensional whole-entity context for company totals
4. preferred standard concept mapping
5. latest restatement for `LATEST_RESTATED`

Persist why a fact was selected and which alternatives were rejected.

## 10. Golden-data verification

For AAPL and MSFT create fixture checks against official 10-K/10-Q statement tables. At minimum verify the selected annual and latest three quarters for revenue, operating income, net income, OCF and CapEx.

No new company should be considered supported until its canonical facts pass a similar smoke test.
