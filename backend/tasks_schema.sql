-- Schema for data/tasks.db (see DATABASE-MIGRATION.md §4).
--
-- A column-for-column translation of the fields backend/server.py already
-- reads and writes in data/sections.json / tasks.json / tags.json. Three
-- things are deliberately not a 1:1 copy of those files:
--
--   * `done` is GENERATED from `status` rather than stored, so the two can
--     never drift apart. Every write path stops setting it by hand.
--   * `position` exists on `sections` too. A JSON array has an order; a
--     table does not, and build_nested() renders categories in file order
--     today, so that order needs a column to survive the move.
--   * `parent_id` is NULL when a task has no parent, where the JSON files
--     use ''. An empty string is a real value to a foreign key, and there
--     is no task with id '', so '' would fail the constraint.
--
-- `desc` is quoted everywhere because DESC is a SQL keyword. SQLite can
-- usually disambiguate it by position, but relying on that is a subtle
-- thing to get wrong later.
--
-- `position` columns (sections, tasks, tags) are deliberately not declared
-- UNIQUE, even per-section/per-task. SQLite's UNIQUE constraints are
-- checked immediately, not deferred until commit, and reordering (see
-- tasks_db.set_task_positions/reposition_section) writes positions one
-- row at a time - a two-item swap has to pass through a state where both
-- rows briefly hold the same target position, which a UNIQUE constraint
-- would reject mid-transaction. Collision-safety instead comes from
-- tasks_db.next_task_position() computing MAX(position) + 1 (so a new row
-- can never land on an already-occupied position) and every read
-- ordering `position, id` (so two rows that do end up sharing a position,
-- e.g. from data that predates that fix, still render in a fixed,
-- deterministic order rather than whatever SQLite's scan happens to
-- return).
--
-- Dates are 'YYYY-MM-DD', timestamps 'YYYY-MM-DDTHH:MM:SSZ' (an instant,
-- always UTC) - server.py's now_iso() is the single place "right now"
-- gets formatted into the latter. due_date/completed use '' (their
-- DEFAULT) for "not set," matching every other optional text column
-- here, rather than NULL; created/modified are always populated. The
-- CHECK constraints below are shape-only (GLOB, not a real calendar
-- check - deliberately: rejecting a value that isn't even shaped like a
-- date is cheap, but a real calendar library buys little here). due_date
-- specifically is safe to enforce this way because both places that set
-- it are `<input type="date">` fields (html/tasks/task-detail.html,
-- static/js/script.js), which the browser itself only ever hands back as
-- '' or a well-formed YYYY-MM-DD - never free text.

CREATE TABLE IF NOT EXISTS sections (
  id       TEXT PRIMARY KEY,
  position INTEGER NOT NULL,
  label    TEXT NOT NULL,
  slug     TEXT NOT NULL UNIQUE,
  note     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tasks (
  id                TEXT PRIMARY KEY,
  section_id        TEXT NOT NULL REFERENCES sections(id),
  position          INTEGER NOT NULL,
  "desc"            TEXT NOT NULL,
  note              TEXT NOT NULL DEFAULT '',
  notes             TEXT NOT NULL DEFAULT '',
  -- CHECK constraints below mirror backend/server.py's STATUSES/
  -- PRIORITIES/WORK_TYPES tuples exactly - if those ever change, this file
  -- and tasks_db.py's migration 2 (_add_task_domain_constraints) both need
  -- the same update, or the database will reject values the app allows.
  status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'in-progress', 'pending', 'done', 'cancelled')),
  done              INTEGER GENERATED ALWAYS AS (status = 'done') VIRTUAL,
  priority          TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
  ticket_number     TEXT NOT NULL DEFAULT '',
  servicenow_sys_id TEXT,                           -- formalizes the field service_now/sync.py already writes
  assignment_group  TEXT NOT NULL DEFAULT '',
  requested_by      TEXT NOT NULL DEFAULT '',
  due_date          TEXT NOT NULL DEFAULT ''
    CHECK (due_date = '' OR due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  time_estimate     TEXT NOT NULL DEFAULT '',
  related_files     TEXT NOT NULL DEFAULT '',
  -- ON DELETE SET NULL, not the default RESTRICT: deleting a task that has
  -- subtasks succeeds today and leaves the children behind, so the children
  -- become top-level rather than the delete failing.
  parent_id         TEXT REFERENCES tasks(id) ON DELETE SET NULL,
  -- '' is the sentinel for "not a Work Tasks item" (or a Work Tasks item
  -- that hasn't picked one yet) - only own-tasks section rows ever get a
  -- non-empty value (server.py enforces that; the constraint only rules
  -- out a fourth, undocumented option string).
  work_type         TEXT NOT NULL DEFAULT '' CHECK (work_type IN ('', 'new-feature', 'schema-change')),
  env_dev           INTEGER NOT NULL DEFAULT 0 CHECK (env_dev IN (0, 1)),
  env_qa            INTEGER NOT NULL DEFAULT 0 CHECK (env_qa IN (0, 1)),
  env_prod          INTEGER NOT NULL DEFAULT 0 CHECK (env_prod IN (0, 1)),
  cmdb_updated      INTEGER NOT NULL DEFAULT 0 CHECK (cmdb_updated IN (0, 1)),
  created           TEXT NOT NULL
    CHECK (created GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
  modified          TEXT NOT NULL
    CHECK (modified GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'),
  completed         TEXT NOT NULL DEFAULT ''
    CHECK (completed = '' OR
           completed GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
);

CREATE INDEX IF NOT EXISTS idx_tasks_section ON tasks(section_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent  ON tasks(parent_id);

CREATE TABLE IF NOT EXISTS tags (
  id       TEXT PRIMARY KEY,
  -- ON DELETE CASCADE matches what handle_delete_task does by hand today:
  -- a task's tags go with it.
  task_id  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  text     TEXT NOT NULL,
  flag     INTEGER NOT NULL DEFAULT 0 CHECK (flag IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_tags_task ON tags(task_id);

-- The freeform "Today's List" notepad shown next to the task list on
-- /tasks, unrelated to any one task or section - always exactly one row.
CREATE TABLE IF NOT EXISTS scratchpad (
  id       INTEGER PRIMARY KEY CHECK (id = 1),
  text     TEXT NOT NULL DEFAULT '',
  modified TEXT NOT NULL DEFAULT ''
    CHECK (modified = '' OR
           modified GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
);
