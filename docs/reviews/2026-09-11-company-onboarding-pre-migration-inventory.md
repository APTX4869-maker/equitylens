# Company onboarding pre-migration inventory

Source database: `/Users/vincent/workspace/equitylens/data/equitylens.duckdb` (read-only inspection on 2026-09-11).

| Table | Rows | Identity linkage observed |
|---|---:|---|
| company | 0 | No registry rows; seed identities must be inferred only from curated AAPL/MSFT metadata. |
| source_document | 42 | `company_id` uses zero-padded CIK for AAPL/MSFT; paths, SHA-256 and fetched timestamps are populated. |
| canonical_fact | 11,301 | `company_id` uses zero-padded CIK. |
| segment_fact | 528 | `company_id` uses zero-padded CIK. |
| market_observation | 0 | No legacy observations to backfill. |
| market_quote | 2 | AAPL and MSFT link by zero-padded CIK and retain ticker/currency/provider. |
| valuation_assumption_set | 0 | No rows to backfill. |
| valuation_run | 11 | All runs link by zero-padded CIK; preserve unchanged. |
| valuation_plan | 0 | No rows to backfill. |

Migration constraints derived from the inventory:

- Seed Apple (`0000320193` / AAPL) and Microsoft (`0000789019` / MSFT) as distinct issuer and security records without rewriting fact, source, quote, or valuation history.
- Keep legacy rows byte/logically stable; add nullable identity/version columns in later migrations.
- Mark seed companies `LEGACY_UNREVIEWED`; this inventory is not quality approval.
- Rehearse against a copy and compare row counts and deterministic row digests before touching the real database.

## T01 rehearsal result

- Rehearsal copy: `/tmp/equitylens-t01.ZTwTpD/rehearsal.duckdb` (source database was never opened for writing).
- Existing tables compared: 18.
- First migration application: version `[1]`; second application: no pending versions.
- Existing-table digest changes: only `company`, from 0 rows to the two required curated seed rows.
- All pre-existing source, fact, segment, market and valuation table row digests were unchanged.
- Seed state: AAPL and MSFT each have one security and one active ticker alias; both companies are `LEGACY_UNREVIEWED`.
