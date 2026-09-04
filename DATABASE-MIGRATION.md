# Database migration: tasks (and finance) onto SQLite

Plan for replacing `data/sections.json` / `data/tasks.json` / `data/tags.json`
with a real SQLite database, using the exact same engine `finance/ARCHITECTURE.md`
already committed to for the Plaid work.

**Status: built** (2026-09-04). Everything below is implemented for tasks;
finance is untouched and still waiting on its own Phase 1. §11 records the
four places the build deviated from this plan and why. Where this text and
the code disagree, the code wins; `backend/tasks_schema.sql` is the
authoritative schema.

## Scope, confirmed with the user 2026-09-04

| Decision | Choice | Why |
|---|---|---|
| Engine | SQLite (stdlib `sqlite3`, no new dependency) | Already available in every Python distribution, ArcGIS Pro's bundled one included — nothing to install. Single file, drops onto the same Render persistent disk as today's JSON. First-class default backend for both Django (zero config) and Flask (via `sqlite3` directly or SQLAlchemy) — this migration doesn't lock in a framework choice, see §7. |
| Scope | `tasks`/`sections`/`tags` now. `finance` reuses the same pattern when its own Phase 1 starts (unchanged from `finance/ARCHITECTURE.md` — not merged into this). `fitness` stays on JSON. | `fitness/ARCHITECTURE.md` §6 is explicit that raw-JSON storage there is deliberate — several metrics' field shapes are still being reverse-engineered against live API responses. Forcing that into rigid tables now would fight a documented, reasoned decision; revisit once those shapes are confirmed. |

---

## 1. Why this, why now

Three things converge:

1. **`finance/ARCHITECTURE.md` already decided SQLite** for its own data, and
   `finance/schema.sql` already exists. Standing up the *pattern* on the
   simpler, lower-stakes tasks data first is a safe place to prove it out
   before real bank data lands on the same technology.
2. **`architecture_Review.md` §2 flagged this exact JSON store** as the
   source of several real risks, and one of its stated assumptions has
   already quietly become false: it says `socketserver.TCPServer`
   serving one request at a time "happens to avoid races today... an
   accident of the current server class." `backend/server.py` already runs
   `TaskServer(http.server.ThreadingHTTPServer)` (added for the finance
   price-quote fetch not blocking other requests) — so the race the review
   called a future risk is a **live** one today, not hypothetical.
   This migration is the fix, not a nice-to-have:
   - No atomic writes today — a crash mid-`json.dump()` can truncate
     `tasks.json`. SQLite's own file format is crash-safe by design.
   - No locking across the three files — `handle_update_tasks` writes
     `tasks.json` then `tags.json` as two separate `save_json()` calls; a
     crash between them leaves them inconsistent. A single SQLite
     transaction spanning both tables closes this for real, not just in
     theory.
   - `done` (bool) and `status` (`open`/`in-progress`/`pending`/`done`/
     `cancelled`) are parallel fields three independent write paths
     (`handle_new_task`, `handle_update_tasks`, `service_now/sync.py`) each
     keep in sync by hand — exactly the "bug waiting to happen" the review
     names. A generated column removes the redundancy outright (§4).
   - `servicenow_sys_id` is today an undocumented field that rides along
     silently through `handle_update_tasks`'s allow-listing only because
     that handler doesn't touch it — formalizing it as a real column in §4
     makes it a first-class, documented part of the schema.
3. **The Flask/Django decision is still open** (`finance/ARCHITECTURE.md`
   §1). Nothing here forces that choice — see §7 for why plain `sqlite3`
   keeps both options fully open.

---

## 2. Target shape

Two independent SQLite files, not one merged database:

```
data/tasks.db      <- this plan
data/finance.db    <- finance/ARCHITECTURE.md §3, unchanged, still not built
```

Kept separate rather than merged into one `data/app.db`, because:
- `finance/ARCHITECTURE.md` already named the file and wrote `schema.sql`
  around it — no reason to re-litigate a decision already confirmed with
  the user 2026-08-23.
- The two domains never need to `JOIN` across each other. Nothing is lost
  by them being separate files, and each stays independently backupable/
  inspectable.

No shared `db.py`/connection-helper module between the two. Each domain
gets its own small (~15 line) connect-and-init-schema function. That's
duplication, but not enough of it to justify an abstraction two call sites
don't need yet — `finance/db.py` can copy the pattern from this migration's
`backend/tasks_db.py` when its own Phase 1 starts, and diverge later if the
two domains ever need different pragmas.

---

## 3. New and changed files

| File | Change |
|---|---|
| `backend/tasks_schema.sql` (new) | DDL for `sections`, `tasks`, `tags` — see §4 |
| `backend/tasks_db.py` (new) | Connection helper (WAL mode, foreign keys on), one function per current `load_*`/`save_*` in `server.py`, plus `migrate_from_json()` (§5) |
| `backend/server.py` | `build_nested()`, `section_slug_exists()`, `find_task()`, `handle_new_task()`, `handle_new_category()`, `handle_update_tasks()`, `handle_delete_task()` swap their `load_json`/`save_json` calls for `tasks_db.*` calls. Route dispatch, request parsing, and response shapes are unchanged — see §6. |
| `.gitignore` | Add `data/tasks.db` (and `data/tasks.db-wal`/`-shm`, WAL mode's sidecar files) |
| `data/sections.json`, `data/tasks.json`, `data/tags.json` | Stay committed, untouched, as the one-time migration source and a manual-recovery fallback — not deleted (§5) |
| `README.md` | "Editing tasks" section rewritten — see §8, this is a real UX change, not just a docs update |
| `DEPLOYMENT.md` | New "Tasks database" section: one-time migration step on the persistent disk (§5) |
| `routes.md` | Opening paragraph ("Data lives in three normalized files...") updated |
| `roadmap.html` | "Real database" flips from "Planned, not built" once implemented |

---

## 4. Schema

```sql
-- backend/tasks_schema.sql

CREATE TABLE IF NOT EXISTS sections (
  id    TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  slug  TEXT NOT NULL UNIQUE,
  note  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
  id                TEXT PRIMARY KEY,
  section_id        TEXT NOT NULL REFERENCES sections(id),
  position          INTEGER NOT NULL,
  "desc"            TEXT NOT NULL,
  note              TEXT NOT NULL DEFAULT '',
  notes             TEXT NOT NULL DEFAULT '',
  status            TEXT NOT NULL DEFAULT 'open',   -- open|in-progress|pending|done|cancelled
  done              INTEGER GENERATED ALWAYS AS (status = 'done') VIRTUAL,
  priority          TEXT NOT NULL DEFAULT 'medium', -- low|medium|high
  ticket_number     TEXT NOT NULL DEFAULT '',
  servicenow_sys_id TEXT,                           -- formalizes the field service_now/sync.py already writes
  assignment_group  TEXT NOT NULL DEFAULT '',
  requested_by      TEXT NOT NULL DEFAULT '',
  due_date          TEXT NOT NULL DEFAULT '',
  time_estimate     TEXT NOT NULL DEFAULT '',
  related_files     TEXT NOT NULL DEFAULT '',
  parent_id         TEXT REFERENCES tasks(id),
  work_type         TEXT NOT NULL DEFAULT '',        -- new-feature|schema-change|'' (Work Tasks section only)
  env_dev           INTEGER NOT NULL DEFAULT 0,
  env_qa            INTEGER NOT NULL DEFAULT 0,
  env_prod          INTEGER NOT NULL DEFAULT 0,
  cmdb_updated      INTEGER NOT NULL DEFAULT 0,
  created           TEXT NOT NULL,
  modified          TEXT NOT NULL,
  completed         TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tasks_section ON tasks(section_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent  ON tasks(parent_id);

CREATE TABLE IF NOT EXISTS tags (
  id       TEXT PRIMARY KEY,
  task_id  TEXT NOT NULL REFERENCES tasks(id),
  position INTEGER NOT NULL,
  text     TEXT NOT NULL,
  flag     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tags_task ON tags(task_id);
```

This is a direct, column-for-column translation of the fields
`backend/server.py` already reads/writes today (more fields than
`README.md` currently documents — worth a separate, smaller doc fix, not
part of this plan). Two deliberate departures from a pure 1:1 copy:

- **`done` is a generated column**, not stored. It's computed from
  `status` on every read (`VIRTUAL`, not `STORED` — no extra disk write,
  since `tasks` is small) and can never drift from it, which removes the
  "three write paths keep two fields in sync by hand" risk outright rather
  than relocating it. `GET /tasks.json`'s response still includes a `done`
  boolean exactly as before — this is invisible to the frontend. Every
  write path stops setting `done` explicitly (there's no column to write
  to); `service_now/sync.py`'s own `done ⇔ status` sync logic gets deleted
  along with it, not just left dormant.
- **`servicenow_sys_id` is a real column**, not an implicit passenger
  field. `handle_update_tasks`'s field-by-field allow-listing already
  doesn't touch it (that's *why* it survives today), so this is a
  clarification of existing behavior, not a behavior change.
- **`"desc"` needs quoting.** `DESC` is a SQL keyword (`ORDER BY ... DESC`).
  SQLite tolerates it as a column name in most positions, but every
  reference in `tasks_db.py` and `tasks_schema.sql` quotes it
  (`"desc"`) rather than relying on the parser disambiguating by context —
  cheap to get right up front, easy to get subtly wrong later.

---

## 5. Migration path

**One-time, not dual-write.** This is a single personal-scale service with
no multi-instance deployment, so there's no need for a zero-downtime
gradual cutover — stop the server, migrate, deploy the new code, verify,
done.

`backend/tasks_db.py` gets a `migrate_from_json()` function, runnable as
`python3 backend/tasks_db.py migrate`:

1. Refuses to run if `data/tasks.db` already exists and has any rows (no
   silent double-import — same guard shape as `fitness/cli.py migrate`).
2. Creates the schema (`CREATE TABLE IF NOT EXISTS`, from
   `tasks_schema.sql`) if the file doesn't exist yet.
3. Reads `data/sections.json` → `INSERT INTO sections`.
4. Reads `data/tasks.json` → `INSERT INTO tasks`, one transaction.
5. Reads `data/tags.json` → `INSERT INTO tags`, same transaction.
6. Prints a row count per table so the migration is verifiable by eye
   before the old files are touched.

The three JSON files are **not deleted**. They stay committed to git
exactly as today — both as the migration's own source of truth and as a
manual-recovery fallback (consistent with this repo's existing posture:
`architecture_Review.md` calls out "no recovery path other than the last
git commit" as a real gap, so removing the last git commit's readable
backup at the same moment we remove JSON-file editability would make that
gap worse, not better).

**Render deployment sequence** (`DEPLOYMENT.md` gets this as a new
section): `data/tasks.db` is git-ignored, so it does not exist on a fresh
persistent disk the way the seed JSON files do today. After deploying the
code that expects `data/tasks.db`:

1. Open a Render Shell session against the running service (or a one-off
   job) and run `python3 backend/tasks_db.py migrate` once, against the
   already-seeded `data/*.json` sitting on the persistent disk.
2. Verify `/tasks`, `/tasks/categories`, and a category page load
   correctly.
3. From then on, the disk's `data/tasks.db` is the live store, same as
   `data/tasks.json` is today — it survives redeploys because it's on the
   persistent disk, not because it's in git.

---

## 6. What does *not* change

- **`GET /tasks.json`'s response shape.** `build_nested()` keeps its exact
  current structure and field names; only its internal `load_sections()` /
  `load_tasks()` / `load_tags()` calls change from JSON reads to
  `SELECT * FROM ...` (via `sqlite3.Row` → `dict`). No frontend JS changes
  at all.
- **Every `handle_*` method's request parsing, validation, and response
  codes/bodies.** The diff is narrowly the storage calls in the middle of
  each handler — `save_tasks(tasks)` becomes a parameterized
  `INSERT`/`UPDATE`, `load_tasks()` becomes a `SELECT`. Reordering logic
  (`reposition_section`, the drag-and-drop position renumbering in
  `handle_update_tasks`) stays exactly the same Python — sort in memory,
  then write positions back row by row inside one transaction. A personal
  task list is small enough that there's no reason to push this into SQL
  window functions; keeping it as recognizable Python minimizes the diff
  against working, tested-by-use logic.
- **Concurrency model beyond what §1 already fixes.** Each request opens
  its own short-lived `sqlite3.connect()` (the standard pattern for a
  multi-threaded server — connections aren't shared across threads),
  `PRAGMA journal_mode=WAL` is set once so readers don't block on a
  writer, and multi-statement handlers (`handle_update_tasks`,
  `handle_delete_task`) wrap their writes in one `with conn:` transaction.
  No new lock file, no queueing layer — SQLite's own transaction isolation
  does this for free once the JSON whole-file-rewrite pattern is gone.
- **`fitness/`, `finance/`.** Untouched by this plan (see Scope above).

---

## 7. Framework compatibility (Flask / Django)

This is written to keep both options fully open, per the still-undecided
question in `finance/ARCHITECTURE.md` §1:

- **Flask**: `tasks_db.py`'s raw `sqlite3` functions carry over essentially
  unchanged — Flask doesn't require an ORM, and its view functions map
  onto the current `handle_*` methods about as directly as
  `finance/ARCHITECTURE.md` §1 already says they would for
  `finance/routes.py`.
- **Django**: the schema in §4 is plain, boring SQL — no SQLite-specific
  trick beyond the one `GENERATED ALWAYS AS` column, which Django's
  `inspectdb` can reverse-engineer into a model (or a hand-written model
  can match it directly) with `managed = False` against the existing file,
  so a future migration to Django's ORM does not require re-migrating the
  data a second time.

Either way, `data/tasks.db` itself is the artifact that survives a
framework decision — this plan is deliberately not coupled to one.

---

## 8. What changes for the user, directly

One real, honest tradeoff worth naming rather than glossing over:
`README.md` currently advertises hand-editing the JSON files as a feature
("no HTML knowledge needed to edit any of them directly"). SQLite removes
that specific path — you can't open `data/tasks.db` in a text editor. The
replacement is the `sqlite3` CLI (`sqlite3 data/tasks.db "SELECT ...`) or a
GUI browser (e.g. DB Browser for SQLite), which is less approachable for a
quick one-off edit than opening a JSON array. In exchange: no more
hand-editing risk of producing invalid JSON that silently breaks
`load_json`'s bare `except OSError` fallback (which today would silently
reset to `[]` on a malformed file, not just a missing one — a sharper edge
than it looks). `README.md`'s "Editing tasks" section gets rewritten to
document the new path rather than the old one.

---

## 9. Suggested build order

1. `backend/tasks_schema.sql` + `backend/tasks_db.py` (connection helper,
   schema init, `migrate_from_json()`) — no `server.py` changes yet,
   reviewable and testable in isolation.
2. `backend/tests/test_tasks_db.py` (stdlib `unittest`, same convention as
   `backend/fitness/tests/`) — schema creation, CRUD round-trips, the
   generated `done` column, `migrate_from_json()` against fixture JSON.
   This is also the "basic test suite" item already sitting on
   `roadmap.html`'s Watch list — this migration clears it as a side effect
   for the tasks backend specifically.
3. Swap `server.py`'s storage calls over, one handler at a time
   (`build_nested`/read path first, then `handle_new_task`,
   `handle_new_category`, `handle_update_tasks`, `handle_delete_task`),
   verified against a local `data/tasks.db` migrated from real data.
4. `.gitignore`, `README.md`, `DEPLOYMENT.md`, `routes.md`.
5. Deploy, run the one-time migration on Render (§5), verify, then update
   `roadmap.html`.

---

## 10. Open questions

- **`service_now/sync.py`** currently reads/writes `data/tasks.json`
  directly, outside the running server (`service_now/README.md`: "nothing
  in `backend/server.py` calls it automatically"). It needs the same
  `tasks_db.py` functions swapped in — small, but it's a second call site
  to update in step 3 above, not just `server.py`.
- **Committed JSON files going stale.** Once `data/tasks.db` is the live
  store, the committed `data/*.json` files stop being updated by normal
  use — they become a frozen snapshot from migration day, not a live
  backup. Worth a periodic manual export (`sqlite3 data/tasks.db
  ".dump"` or a small export script) if an up-to-date git-backed
  fallback still matters to you, or explicitly accepting that the
  persistent disk becomes the only copy of current data (same trust model
  `data/fitness/` already has).

---

## 11. Build notes: where this deviated

Four things this plan did not account for, found while building it against
the real `data/*.json`. All four are in `backend/tasks_schema.sql` with
comments; this is the reasoning.

### `sections` needed a `position` column

§4's `sections` table has no ordering column, but `build_nested()` renders
categories in `data/sections.json`'s **array order**, and a table has no
inherent order: `SELECT * FROM sections` would have returned them
arbitrarily. Categories would have silently reshuffled on the first page
load. Added `position INTEGER NOT NULL`, set from the array index at
migration time and from `MAX(position) + 1` for new categories. It is not
exposed in `GET /tasks.json`, so nothing downstream changed.

### `parent_id` had to become NULL, not `''`

§4 declares `parent_id TEXT REFERENCES tasks(id)`, and all 47 tasks in
`data/tasks.json` carry `"parent_id": ""`. An empty string is a real value
to a foreign key, and no task has id `''`, so every single row would have
failed the constraint. `parent_id` is now NULL on disk when unset and read
back as `''`, keeping the API response identical.

### The foreign keys needed explicit delete rules

With `PRAGMA foreign_keys = ON` and the default RESTRICT, deleting a task
that has subtasks would have **failed**, where before the migration it
succeeded and left the children behind. `parent_id` is now
`ON DELETE SET NULL` (children survive, orphaned, as they did) and
`tags.task_id` is `ON DELETE CASCADE` (which is what `handle_delete_task`
was doing by hand anyway).

### The slug check was two different checks

§6 says handler logic is unchanged, but `section_slug_exists()` used for
routing matched on `slug` only, while `handle_new_category`'s collision
check matched `slug` **or** `id`. Collapsing them into one helper would
have quietly changed which URLs 404. They are two functions:
`section_slug_exists()` and `section_name_taken()`.

### Verification

- `GET /tasks.json` from the migrated database is **byte-for-byte
  identical** to the pre-migration response, diffed against the live
  server on the real 6 sections / 47 tasks / 33 tags. That is the whole
  read path, including `done` and the `env_*` flags coming back as JSON
  booleans rather than SQLite's 0/1.
- Every write path exercised against a running server: new category,
  duplicate category rejected, new task with tags and a flag tag, unknown
  section rejected, status change, notes, tag replacement, drag-and-drop
  reordering, delete, and delete of a missing id.
- `backend/tests/test_tasks_db.py`, 25 tests, covering the schema, the
  generated `done` column (including that a contradictory `done` cannot be
  written), round-tripping, tags, deletes, and `migrate_from_json()`.
- `service_now/sync.py`'s upsert exercised directly: create, idempotent
  re-run, and an upstream status flip to done.

### §10's second point, resolved

`data/sections.json`, `data/tasks.json` and `data/tags.json` stopped being
written the moment the database went live, so they were a frozen snapshot
from migration day rather than a backup. `backend/tasks_export.py`
regenerates them from `data/tasks.db`:

```
python3 backend/tasks_export.py          # rewrite the JSON files
python3 backend/tasks_export.py --check  # report drift, write nothing
```

It is the exact inverse of `tasks_db.py migrate` (verified both ways: the
files it writes re-import to identical rows, and exporting those rows again
is byte-identical), writes with the same `indent=2` plus trailing newline
`save_json()` used, and orders rows deterministically so git diffs show
only real changes. `--check` exits 1 on drift, for a pre-commit hook or a
cron job.

Deliberately manual rather than wired into every write: the JSON files are
a fallback, and having each `POST /tasks/update` rewrite three files would
put back exactly the whole-file-rewrite cost and crash-window this
migration removed.

Verified on the real store: exporting the migrated database changed **zero
fields** across all 86 rows, only their order.
