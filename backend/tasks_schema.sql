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
  -- ON DELETE SET NULL, not the default RESTRICT: deleting a task that has
  -- subtasks succeeds today and leaves the children behind, so the children
  -- become top-level rather than the delete failing.
  parent_id         TEXT REFERENCES tasks(id) ON DELETE SET NULL,
  work_type         TEXT NOT NULL DEFAULT '',       -- new-feature|schema-change (Work Tasks section only)
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
  -- ON DELETE CASCADE matches what handle_delete_task does by hand today:
  -- a task's tags go with it.
  task_id  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  text     TEXT NOT NULL,
  flag     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tags_task ON tags(task_id);
