# Database review: GitHub issue handoff

## Purpose

This file is a ready-to-use handoff for creating the GitHub issues identified
during the September 2026 review of the application's active SQLite schemas.
The active schemas are:

- `backend/tasks_schema.sql` for `data/tasks.db`.
- `backend/finance/csv_schema.sql` for `data/finance/finance.db`.

`finance/schema.sql` is the unused, deferred Plaid schema and is outside this
handoff's scope.

## Instructions for the receiving agent

1. Confirm that a GitHub remote and `gh` authentication are available:

   ```bash
   git remote -v
   gh auth status
   gh repo view --json nameWithOwner,url
   ```

2. Search open **and closed** issues for duplicates before creating anything:

   ```bash
   gh issue list --state all --limit 200
   gh issue list --state all --search "database migration tasks"
   gh issue list --state all --search "integer cents finance"
   ```

3. Create one issue for each non-duplicate draft below. Preserve the acceptance
   criteria, but adapt wording to the repository's issue conventions if needed.
4. Add existing labels where appropriate. Suggested labels are included, but do
   not create a new label taxonomy solely for this handoff.
5. Record the resulting issue number and URL in the completion report. If an
   issue is skipped as a duplicate, record the existing issue instead.
6. Do not implement these issues as part of the issue-creation task.

---

## Issue 1: Add versioned migrations for the tasks database

**Suggested title:** `Add versioned schema migrations for tasks.db`

**Suggested labels:** `database`, `tasks`, `technical-debt`

**Priority:** High; complete before the next tasks schema change.

### Background

`backend/tasks_db.py:init_schema()` currently reruns
`backend/tasks_schema.sql`, whose tables use `CREATE TABLE IF NOT EXISTS`.
That initializes a fresh database but cannot add, remove, or alter columns in
an existing `data/tasks.db`. The finance database already provides the desired
pattern with `PRAGMA user_version`, an explicit schema version, ordered
migrations, and migration tests.

### Proposed work

- Add a tasks schema-version constant.
- Read and update `PRAGMA user_version`.
- Run ordered, idempotent migrations after base-schema initialization.
- Ensure a migration and its version update are safely committed.
- Document the process for adding the next migration.
- Add tests for fresh, old, current, and repeatedly initialized databases.

### Acceptance criteria

- A fresh tasks database initializes at the current schema version.
- An existing older database is upgraded without losing task data.
- Running initialization repeatedly is idempotent.
- A failed migration does not falsely record the new version.
- Tests demonstrate an upgrade from at least one representative old schema.

---

## Issue 2: Define an exact-storage strategy for financial values

**Suggested title:** `Replace or contain REAL storage for exact financial values`

**Suggested labels:** `database`, `finance`, `data-integrity`

**Priority:** Medium.

### Background

The live finance schema stores transaction amounts, CAD balances, credit
limits, interest rates, and Bitcoin quantities as SQLite `REAL`. Binary
floating point cannot exactly represent many decimal currency values. This can
affect reconciliation, equality, aggregation, and identifiers derived from
formatted amounts.

Different quantities require different precision policies: CAD can use integer
cents, while Bitcoin can use integer satoshis. Interest rates may use a
documented fixed-scale representation or remain approximate if that is an
explicit decision.

### Proposed work

- Audit every finance `REAL` column and all calculations that consume it.
- Decide the canonical unit and precision for each quantity.
- Prefer integer cents for CAD and integer satoshis for Bitcoin.
- Define a backward-compatible migration for existing data, or explicitly
  document a containment strategy if immediate migration is too disruptive.
- Normalize amounts before transaction-ID generation.
- Add round-trip, aggregate, and migration tests using precision edge cases.

### Acceptance criteria

- The canonical representation and rounding policy for every financial value
  is documented.
- Exact currency calculations do not depend on binary-float equality.
- Existing imported data remains readable and produces equivalent displayed
  totals after any migration.
- Transaction IDs remain stable or overrides/exclusions are migrated safely.
- Tests cover values such as `0.01`, repeated fractional additions, refunds,
  large balances, and eight-decimal-place Bitcoin quantities.

---

## Issue 3: Make task, section, and tag ordering collision-safe

**Suggested title:** `Enforce deterministic and collision-safe position ordering`

**Suggested labels:** `database`, `tasks`, `bug`

**Priority:** Medium.

### Background

Sections, tasks, and tags use integer `position` columns, but duplicate and
negative positions are currently permitted. `next_task_position()` uses
`COUNT(*)`, which can return an already occupied position when a section has a
gap (for example, positions `0` and `2`). Reads order only by `position`, so a
collision also produces nondeterministic ordering.

### Proposed work

- Change new-task positioning to `COALESCE(MAX(position) + 1, 0)` within the
  target section.
- Add deterministic tie-breakers such as `ORDER BY position, id` to reads.
- Decide whether to enforce non-negative and unique positions in the schema.
- If uniqueness is added, make reordering collision-safe within a transaction.
- Repair duplicate/gapped positions during migration if necessary.

### Acceptance criteria

- Adding a task to a section with gapped positions cannot reuse an occupied
  position.
- Equal legacy positions render deterministically.
- Reordering remains atomic and does not fail due to transient collisions.
- Tests cover gaps, duplicates, deletion, reordering, and concurrent-looking
  sequential inserts.
- Any new constraints have a migration path for existing databases.

---

## Issue 4: Add database constraints for stable task domain values

**Suggested title:** `Add CHECK constraints for task enums and booleans`

**Suggested labels:** `database`, `tasks`, `data-integrity`

**Priority:** Medium.

### Background

The tasks schema documents allowed values for `status`, `priority`, and
`work_type`, but SQLite accepts any text. Boolean fields are integers without
an `IN (0, 1)` constraint. Invalid status values are particularly risky because
the generated `done` column is true only when `status = 'done'`.

### Proposed work

- Add `CHECK` constraints for status, priority, work type, and integer boolean
  fields.
- Audit existing JSON migration sources and representative databases for values
  that would violate the constraints.
- Add a versioned tasks migration, rebuilding the table if SQLite requires it.
- Keep application-side validation for useful user-facing errors.

### Acceptance criteria

- The database rejects undocumented task statuses and priorities.
- `work_type` accepts only the supported values and the empty sentinel.
- Boolean columns accept only `0` and `1`.
- Existing valid task data migrates without behavioral or API-shape changes.
- Tests cover every accepted value and representative rejected values.

---

## Issue 5: Enforce or explicitly validate finance domain values

**Suggested title:** `Define integrity rules for finance account and source types`

**Suggested labels:** `database`, `finance`, `data-integrity`

**Priority:** Medium.

### Background

Net-worth calculations assume every account `kind` belongs to a known asset or
liability set, but the database accepts arbitrary text. Other apparently stable
domains include balance snapshot `source` and import batch `kind`. In contrast,
bank-provided transaction activity types may need to remain extensible.

### Proposed work

- Classify finance text domains as closed, application-extensible, or
  externally supplied.
- Add database `CHECK` constraints for genuinely closed domains, especially
  account kinds.
- Retain application validation with clear errors.
- Do not constrain externally supplied values unless unknown values have a
  deliberate fallback.
- Add a safe schema migration and tests.

### Acceptance criteria

- The repository documents which finance domains are closed versus extensible.
- Unknown account kinds cannot silently enter data used for net-worth math.
- All current importers and seeds continue to work.
- Tests cover all known account kinds and reject unknown closed-domain values.
- No constraint prevents ingestion of legitimate new bank activity text.

---

## Issue 6: Clarify and enforce transaction currency semantics

**Suggested title:** `Define CAD and multi-currency semantics in the finance schema`

**Suggested labels:** `database`, `finance`, `design`

**Priority:** Medium; resolve before adding non-CAD accounts.

### Background

Accounts have a `currency` column, while `transactions.amount` is documented as
CAD and balance snapshots explicitly use `balance_cad`. The schema therefore
appears capable of representing non-CAD accounts without retaining a
transaction's original currency, original amount, exchange rate, or conversion
provenance.

### Proposed work

- Decide whether the application is CAD-only or supports source currencies.
- For CAD-only operation, validate or constrain account currency accordingly.
- For multi-currency operation, model original amount/currency plus normalized
  CAD value and conversion metadata.
- Document how refunds, transfers, and account totals are converted.
- Add migration and reporting tests before accepting non-CAD imports.

### Acceptance criteria

- Transaction amount semantics are unambiguous in schema comments and
  application documentation.
- The database cannot imply multi-currency support that calculations do not
  actually provide.
- If conversion is supported, original values and conversion provenance are
  retained.
- Summary and cash-flow tests cover the chosen currency policy.

---

## Issue 7: Centralize validation for stored dates and timestamps

**Suggested title:** `Validate canonical date and timestamp formats before persistence`

**Suggested labels:** `database`, `data-integrity`, `technical-debt`

**Priority:** Medium/low.

### Background

SQLite text dates are appropriate for this application when consistently
serialized as ISO-8601. Several queries depend on lexical ordering of date and
timestamp text, especially the latest-balance view. The schema currently
accepts arbitrary strings for these fields.

### Proposed work

- Inventory task and finance date/timestamp columns.
- Define canonical formats, including timezone behavior and whether empty
  strings or `NULL` represent missing values.
- Centralize parsing and serialization at write boundaries.
- Add lightweight schema checks where they improve safety without pretending
  to provide full calendar validation.
- Validate imported dates before a range-replace operation begins.

### Acceptance criteria

- Canonical date and timestamp formats are documented.
- Every application write path uses shared validation/serialization helpers.
- Invalid values fail before partial data is written.
- Lexical ordering remains chronologically correct for stored values.
- Tests cover valid values, malformed dates, timezone handling, and missing
  optional dates.

---

## Issue 8: Decide whether balance snapshots require enforced immutability

**Suggested title:** `Define and enforce the append-only policy for balance history`

**Suggested labels:** `database`, `finance`, `design`

**Priority:** Low.

### Background

Documentation and application code describe balance snapshots as append-only,
but SQLite permits updates and deletes. That may be acceptable for a personal
application, or it may conflict with the intended audit-history guarantee.

### Proposed work

- Decide whether “append-only” is a coding convention or a database invariant.
- If it is an invariant, design update/delete prevention and an explicit
  correction or administrative-repair workflow.
- If it remains a convention, document the limitation and ensure ordinary code
  exposes no update/delete path.
- Add tests appropriate to the chosen policy.

### Acceptance criteria

- The append-only guarantee is stated precisely.
- Normal application operations cannot accidentally rewrite history.
- Same-day corrections continue to create a new snapshot and resolve
  deterministically as latest.
- An intentional recovery procedure exists if database-level immutability is
  introduced.

---

## Issue 9: Link transaction imports to import batch audit records

**Suggested title:** `Unify transaction and balance import auditing with batch IDs`

**Suggested labels:** `database`, `finance`, `enhancement`

**Priority:** Low.

### Background

Balance snapshots reference `import_batches`, while imported transactions only
store `source_file` and `imported_at`. This creates two parallel audit models
and makes it harder to identify exactly which transaction rows came from one
upload or verify expected versus stored row counts.

### Proposed work

- Add a nullable transaction `batch_id` referencing `import_batches`.
- Create one batch per successful CSV/PDF import.
- Store source filename, hash, date range, row count, importer kind, and notes
  at batch level.
- Preserve the range-replace behavior and deliberate override persistence.
- Define batch behavior for failed or partially parsed imports.
- Migrate legacy transactions without inventing misleading provenance.

### Acceptance criteria

- Every new successful transaction import has one identifiable batch.
- Batch row count and date range agree with inserted data.
- Re-import and range replacement preserve category overrides and cash-flow
  exclusions.
- Legacy transactions remain usable with a documented null/legacy batch state.
- Tests cover CSV, PDF, duplicate, replacement, and failed imports.

---

## Issue 10: Add database integrity and migration checks to the test suite

**Suggested title:** `Add cross-schema integrity checks and migration fixtures`

**Suggested labels:** `database`, `testing`, `technical-debt`

**Priority:** Medium.

### Background

Both schemas initialize successfully in memory, and the existing task and
finance suites provide strong behavior coverage. A dedicated integrity suite
would make schema guarantees explicit and catch drift as migrations and
constraints are added.

### Proposed work

- Initialize both current schemas from scratch in temporary databases.
- Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` in tests.
- Assert expected tables, views, indexes, foreign keys, and schema versions.
- Maintain representative old-schema fixtures for every supported migration
  path.
- Verify initialization and migrations are idempotent.
- Add checks that application connections always enable foreign keys.

### Acceptance criteria

- CI checks integrity and foreign keys for fresh databases.
- CI migrates representative older databases to the current version.
- Schema-object assertions detect accidentally missing indexes or views.
- Repeated initialization succeeds without changing data.
- Test documentation explains how to add a fixture for a new migration.

---

## Suggested issue creation order

Create all non-duplicate issues, then recommend implementation in this order:

1. Versioned tasks migrations.
2. Cross-schema integrity and migration tests.
3. Collision-safe task ordering.
4. Task domain constraints.
5. Finance domain constraints.
6. Exact financial-value storage strategy.
7. Currency semantics.
8. Date and timestamp validation.
9. Unified import batches.
10. Append-only balance-history decision.

Issues that change an existing schema must include an upgrade path; editing a
`CREATE TABLE IF NOT EXISTS` statement alone is not an upgrade strategy.
