# T02 immutable publication rehearsal

The migration was rehearsed against a fresh copy of the 34 MB production-like local database. The source database remained read-only.

- Rehearsal copy: `/tmp/equitylens-t02.fViCIl/rehearsal.duckdb`
- Migration duration: 34.11 seconds
- First application: versions `[1, 2]`
- Second application: no pending versions
- Existing-table digest changes: only the intentionally seeded `company` table (0 → 2 rows)
- Apple legacy dataset: 31,044 sealed rows
- Microsoft legacy dataset: 38,633 sealed rows
- Each issuer received one immutable legacy dataset/publication and an atomic active pointer
- Both publications remain explicitly `LEGACY_UNREVIEWED`; no quality approval was inferred

The initial row-at-a-time implementation was stopped on a disposable copy after it proved too slow. The migration now seals dataset rows in bounded batches; no source or real database was modified during that correction.
