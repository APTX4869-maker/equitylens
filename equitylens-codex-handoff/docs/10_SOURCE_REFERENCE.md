# Authoritative Source Reference

Checked on 2026-08-30 for the design handoff.

## SEC

- EDGAR Application Programming Interfaces: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
  - documents public `data.sec.gov` submissions and XBRL APIs
  - states no authentication/API key is needed for these public data APIs
  - documents companyfacts/companyconcept/frames and bulk ZIPs
  - notes standard taxonomy/entity-wide scope for aggregated XBRL APIs

- SEC Developer Resources: https://www.sec.gov/about/developer-resources
  - public EDGAR data access and fair access
  - current guideline: no more than 10 requests/second; EquityLens should use a lower internal cap

- Inline XBRL: https://www.sec.gov/data-research/structured-data/inline-xbrl
  - describes Inline XBRL as both human- and machine-readable and explains contextual metadata

- SEC Forms Index: https://www.sec.gov/submit-filings/forms-index
  - official form descriptions; Form 4 = changes in beneficial ownership

## Company official IR

- Apple Investor Relations: https://investor.apple.com/
- Apple IR FAQ: https://investor.apple.com/investor-relations/faq/default.aspx
- Microsoft Investor Relations: https://www.microsoft.com/en-us/investor/
- Microsoft SEC Filings: https://www.microsoft.com/en-us/investor/sec-filings
- Microsoft Investor Information: https://www.microsoft.com/en-us/investor/investor-information

## Macro / rates

- U.S. Treasury interest-rate statistics: https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics
- FRED series observations API: https://fred.stlouisfed.org/docs/api/fred/series_observations.html

## Implementation note

These URLs are source-registry inputs, not hardcoded proof that a value exists. Each actual fetched item must persist its own concrete filing/document URL, publication/filing time, fetch time and hash.
