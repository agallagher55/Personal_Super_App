"""SQLite storage for the tasks tracker (see DATABASE-MIGRATION.md).

Replaces the data/sections.json + tasks.json + tags.json trio that
backend/server.py used to whole-file rewrite on every save. The point is
not speed - a personal task list is tiny - but that a crash mid-write can
no longer truncate the store, and that a task and its tags now change in
one transaction instead of two independent file writes that can disagree
if the process dies between them.

The dicts this module hands back have exactly the shape server.py's
load_tasks()/load_sections()/load_tags() used to return, key order
included, so build_nested() and every handler's logic carry over
unchanged. Three conversions make that true (see tasks_schema.sql):

    done                 generated in SQL, returned as a bool
    env_*/cmdb_updated   INTEGER on disk, returned as bools
    parent_id            NULL on disk when unset, returned as ''
    servicenow_sys_id    NULL on disk when unset, omitted from the dict,
                         matching the JSON files where the key was simply
                         absent on tasks ServiceNow had never touched

Each request opens its own short-lived connection: sqlite3 connections are
not shareable across threads, and server.py is a ThreadingHTTPServer.
WAL mode is set once at schema-init time (it is a persistent property of
the database file, not a per-connection one) so readers never block on a
writer.
"""

import json
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'tasks.db')
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tasks_schema.sql')

SECTIONS_FILE = os.path.join(DATA_DIR, 'sections.json')
TASKS_FILE = os.path.join(DATA_DIR, 'tasks.json')
TAGS_FILE = os.path.join(DATA_DIR, 'tags.json')

# GENERATED ALWAYS AS ... VIRTUAL landed in SQLite 3.31 (2020-01). Checking
# once with a clear message beats a bare "near GENERATED: syntax error" out
# of executescript() on an old system library.
MIN_SQLITE_VERSION = (3, 31, 0)

# Bumped whenever a one-time migration is added below; tracked per database
# in PRAGMA user_version so each migration runs exactly once. Mirrors
# finance/db.py's SCHEMA_VERSION/migrate() pattern.
#
# To add the next migration: bump this constant, add an
# `if version < N: _your_migration(conn)` line to migrate() below (in
# order, one per version - see migration 2, _add_task_domain_constraints,
# for a worked example of the table-rebuild case), and write
# `_your_migration` the way
# finance/db.py's migrations do - check what's actually there with
# PRAGMA table_info() rather than assuming a database's starting state,
# since CREATE TABLE IF NOT EXISTS is a no-op against a table that already
# exists but says nothing about its columns. If the change needs more than
# ALTER TABLE ADD COLUMN (SQLite can't ALTER TABLE to add a CHECK
# constraint, drop a column's constraint, etc.), rebuild the table: create
# a new one with the desired shape, copy the data across, drop the old
# one, rename, then recreate any indexes the drop took with it. Add a test
# in test_tasks_db.py that stages a database at the previous version (see
# TestSchemaMigrations below) and asserts the upgrade preserves data and
# is idempotent.
SCHEMA_VERSION = 3

# Order matters: the dicts built from these are serialized straight into
# GET /tasks.json, and keeping the old JSON files' key order means the
# response stays byte-for-byte what it was before the migration.
TASK_COLUMNS = (
    'id', 'section_id', 'position', 'desc', 'note', 'notes', 'status', 'done',
    'created', 'modified', 'completed', 'priority', 'ticket_number',
    'assignment_group', 'requested_by', 'due_date', 'time_estimate',
    'related_files', 'parent_id', 'work_type', 'env_dev', 'env_qa', 'env_prod',
    'cmdb_updated', 'servicenow_sys_id',
)

# Everything in TASK_COLUMNS except `done`, which is generated and so has no
# column to write to.
TASK_WRITE_COLUMNS = tuple(c for c in TASK_COLUMNS if c != 'done')

TASK_BOOL_COLUMNS = ('env_dev', 'env_qa', 'env_prod', 'cmdb_updated')

SECTION_COLUMNS = ('id', 'label', 'slug', 'note')


def connect(path=None):
    """A connection for one unit of work. Callers close it when done."""
    path = path or DB_PATH
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_schema(conn):
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            'SQLite %s is too old for this schema (need %s or newer, for the '
            'generated `done` column). sqlite3.sqlite_version reports the '
            'library Python is linked against, not the pysqlite version.'
            % (sqlite3.sqlite_version, '.'.join(str(n) for n in MIN_SQLITE_VERSION))
        )

    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())

    # A property of the file itself, so this sticks for every later
    # connection rather than needing to be re-set per request.
    conn.execute('PRAGMA journal_mode = WAL')
    conn.commit()
    migrate(conn)


def migrate(conn):
    """Applies the migrations this database is behind on, in order. Every
    setup path goes through init_schema (server startup, the JSON import,
    tests), so no caller can end up on a database whose schema is current
    but whose recorded version isn't - same pattern as finance/db.py.

    Migration 1 has no DDL of its own: `CREATE TABLE IF NOT EXISTS` already
    brought every tasks.db, old or new, to today's table shapes before this
    module tracked a schema version at all. It exists purely to start that
    tracking, so the *next* real migration (adding or changing a column)
    has a version number to check against instead of probing
    PRAGMA table_info() to guess whether it already ran.
    """
    version = conn.execute('PRAGMA user_version').fetchone()[0]

    if version < 2:
        _add_task_domain_constraints(conn)

    if version < 3:
        _add_date_format_constraints(conn)

    if version < SCHEMA_VERSION:
        # No bind parameters allowed in a PRAGMA, and SCHEMA_VERSION is our
        # own int constant, never user input.
        conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        conn.commit()


def _normalize_task_domain_values(conn):
    """Best-effort repair pass ahead of the CHECK-constrained rebuild below:
    coerces any status/priority/work_type/boolean value that predates
    server.py's STATUSES/PRIORITIES/WORK_TYPES validation (or arrived by
    direct SQL, bypassing it) into something the new constraints accept,
    so the rebuild's INSERT can't fail on old data no live code path would
    ever have written on purpose."""
    conn.execute('''
        UPDATE tasks SET status = 'open'
        WHERE status NOT IN ('open', 'in-progress', 'pending', 'done', 'cancelled')
    ''')
    conn.execute('''
        UPDATE tasks SET priority = 'medium' WHERE priority NOT IN ('low', 'medium', 'high')
    ''')
    conn.execute('''
        UPDATE tasks SET work_type = '' WHERE work_type NOT IN ('', 'new-feature', 'schema-change')
    ''')
    for column in ('env_dev', 'env_qa', 'env_prod', 'cmdb_updated'):
        conn.execute('UPDATE tasks SET "%s" = 0 WHERE "%s" NOT IN (0, 1)' % (column, column))
    conn.execute('UPDATE tags SET flag = 0 WHERE flag NOT IN (0, 1)')


def _add_task_domain_constraints(conn):
    """Migration 2: adds CHECK constraints for tasks.status/priority/
    work_type and every integer boolean column (tasks.env_dev/env_qa/
    env_prod/cmdb_updated, tags.flag) - see tasks_schema.sql, which already
    has them for a brand new database. SQLite can't ALTER TABLE to add a
    CHECK constraint to an existing table, so this rebuilds both: create
    the constrained shape under a temporary name, copy the (normalized)
    data across, drop the original, rename the new one into place. This is
    SQLite's own documented procedure for a schema change ALTER TABLE
    can't express (https://www.sqlite.org/lang_altertable.html, "Making
    Other Kinds Of Table Schema Changes").

    Foreign keys are turned off for the duration: tags.task_id and
    tasks.parent_id/section_id all reference a table this function drops
    and recreates by name, and SQLite enforces those references against
    whatever table currently has that name - so a mid-rebuild DROP TABLE
    tasks would fail against tags' still-live reference to it otherwise.
    tasks_new's own parent_id is declared REFERENCES tasks_new(id) while
    that's still its name; SQLite rewrites that to REFERENCES tasks(id)
    automatically when it's renamed (has done so since 3.25.0, comfortably
    below MIN_SQLITE_VERSION), the same as it would for a view or trigger
    referencing the old name.

    Everything here runs in one transaction: PRAGMA foreign_key_check is
    read before COMMIT, and finding any violation rolls back the whole
    rebuild rather than leaving a half-migrated database - the version
    number is only bumped by the caller (migrate()) after this returns
    without raising, so a failure here leaves user_version exactly where
    it was and the same migration re-attempts next time.
    """
    _normalize_task_domain_values(conn)
    conn.commit()

    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.execute('BEGIN')

        conn.execute('''
            CREATE TABLE tasks_new (
              id                TEXT PRIMARY KEY,
              section_id        TEXT NOT NULL REFERENCES sections(id),
              position          INTEGER NOT NULL,
              "desc"            TEXT NOT NULL,
              note              TEXT NOT NULL DEFAULT '',
              notes             TEXT NOT NULL DEFAULT '',
              status            TEXT NOT NULL DEFAULT 'open'
                                  CHECK (status IN ('open', 'in-progress', 'pending', 'done', 'cancelled')),
              done              INTEGER GENERATED ALWAYS AS (status = 'done') VIRTUAL,
              priority          TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
              ticket_number     TEXT NOT NULL DEFAULT '',
              servicenow_sys_id TEXT,
              assignment_group  TEXT NOT NULL DEFAULT '',
              requested_by      TEXT NOT NULL DEFAULT '',
              due_date          TEXT NOT NULL DEFAULT '',
              time_estimate     TEXT NOT NULL DEFAULT '',
              related_files     TEXT NOT NULL DEFAULT '',
              parent_id         TEXT REFERENCES tasks_new(id) ON DELETE SET NULL,
              work_type         TEXT NOT NULL DEFAULT '' CHECK (work_type IN ('', 'new-feature', 'schema-change')),
              env_dev           INTEGER NOT NULL DEFAULT 0 CHECK (env_dev IN (0, 1)),
              env_qa            INTEGER NOT NULL DEFAULT 0 CHECK (env_qa IN (0, 1)),
              env_prod          INTEGER NOT NULL DEFAULT 0 CHECK (env_prod IN (0, 1)),
              cmdb_updated      INTEGER NOT NULL DEFAULT 0 CHECK (cmdb_updated IN (0, 1)),
              created           TEXT NOT NULL,
              modified          TEXT NOT NULL,
              completed         TEXT NOT NULL DEFAULT ''
            )
        ''')
        conn.execute('''
            INSERT INTO tasks_new (
              id, section_id, position, "desc", note, notes, status, priority, ticket_number,
              servicenow_sys_id, assignment_group, requested_by, due_date, time_estimate,
              related_files, parent_id, work_type, env_dev, env_qa, env_prod, cmdb_updated,
              created, modified, completed
            )
            SELECT
              id, section_id, position, "desc", note, notes, status, priority, ticket_number,
              servicenow_sys_id, assignment_group, requested_by, due_date, time_estimate,
              related_files, parent_id, work_type, env_dev, env_qa, env_prod, cmdb_updated,
              created, modified, completed
            FROM tasks
        ''')
        conn.execute('DROP TABLE tasks')
        conn.execute('ALTER TABLE tasks_new RENAME TO tasks')
        conn.execute('CREATE INDEX idx_tasks_section ON tasks(section_id)')
        conn.execute('CREATE INDEX idx_tasks_parent ON tasks(parent_id)')

        conn.execute('''
            CREATE TABLE tags_new (
              id       TEXT PRIMARY KEY,
              task_id  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              position INTEGER NOT NULL,
              text     TEXT NOT NULL,
              flag     INTEGER NOT NULL DEFAULT 0 CHECK (flag IN (0, 1))
            )
        ''')
        conn.execute('''
            INSERT INTO tags_new (id, task_id, position, text, flag)
            SELECT id, task_id, position, text, flag FROM tags
        ''')
        conn.execute('DROP TABLE tags')
        conn.execute('ALTER TABLE tags_new RENAME TO tags')
        conn.execute('CREATE INDEX idx_tags_task ON tags(task_id)')

        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            conn.execute('ROLLBACK')
            raise RuntimeError('foreign key violations after tasks/tags rebuild: %r' % (violations,))

        conn.execute('COMMIT')
    finally:
        conn.execute('PRAGMA foreign_keys = ON')


_DATE_GLOB = "GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
_TIMESTAMP_GLOB = "GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'"


def _add_date_format_constraints(conn):
    """Migration 3: adds shape-only CHECK constraints (see tasks_schema.sql's
    date/timestamp comment) for tasks.due_date/created/modified/completed
    and scratchpad.modified. Same table-rebuild procedure as migration 2;
    no normalization pass, for the same reason - a malformed date/
    timestamp can't be safely reinterpreted without knowing what it was
    supposed to be, so this refuses rather than guessing.
    """
    bad = conn.execute(
        f"SELECT DISTINCT due_date AS value, 'due_date' AS column_name FROM tasks "
        f"WHERE due_date != '' AND due_date NOT {_DATE_GLOB} "
        f"UNION SELECT DISTINCT created, 'created' FROM tasks WHERE created NOT {_TIMESTAMP_GLOB} "
        f"UNION SELECT DISTINCT modified, 'modified' FROM tasks WHERE modified NOT {_TIMESTAMP_GLOB} "
        f"UNION SELECT DISTINCT completed, 'completed' FROM tasks "
        f"WHERE completed != '' AND completed NOT {_TIMESTAMP_GLOB} "
        f"UNION SELECT DISTINCT modified, 'scratchpad.modified' FROM scratchpad "
        f"WHERE modified != '' AND modified NOT {_TIMESTAMP_GLOB}"
    ).fetchall()
    if bad:
        raise RuntimeError(
            'refusing to add the date/timestamp format constraints: malformed value(s) already stored '
            '- %s - fix or remove those rows by hand first, since this migration cannot safely guess '
            'what a malformed date or timestamp was supposed to be.'
            % ', '.join('%s=%r' % (row['column_name'], row['value']) for row in bad)
        )

    conn.execute('PRAGMA foreign_keys = OFF')
    try:
        conn.execute('BEGIN')

        conn.execute('''
            CREATE TABLE tasks_new (
              id                TEXT PRIMARY KEY,
              section_id        TEXT NOT NULL REFERENCES sections(id),
              position          INTEGER NOT NULL,
              "desc"            TEXT NOT NULL,
              note              TEXT NOT NULL DEFAULT '',
              notes             TEXT NOT NULL DEFAULT '',
              status            TEXT NOT NULL DEFAULT 'open'
                                  CHECK (status IN ('open', 'in-progress', 'pending', 'done', 'cancelled')),
              done              INTEGER GENERATED ALWAYS AS (status = 'done') VIRTUAL,
              priority          TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
              ticket_number     TEXT NOT NULL DEFAULT '',
              servicenow_sys_id TEXT,
              assignment_group  TEXT NOT NULL DEFAULT '',
              requested_by      TEXT NOT NULL DEFAULT '',
              due_date          TEXT NOT NULL DEFAULT ''
                CHECK (due_date = '' OR due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
              time_estimate     TEXT NOT NULL DEFAULT '',
              related_files     TEXT NOT NULL DEFAULT '',
              parent_id         TEXT REFERENCES tasks_new(id) ON DELETE SET NULL,
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
            )
        ''')
        conn.execute('''
            INSERT INTO tasks_new (
              id, section_id, position, "desc", note, notes, status, priority, ticket_number,
              servicenow_sys_id, assignment_group, requested_by, due_date, time_estimate,
              related_files, parent_id, work_type, env_dev, env_qa, env_prod, cmdb_updated,
              created, modified, completed
            )
            SELECT
              id, section_id, position, "desc", note, notes, status, priority, ticket_number,
              servicenow_sys_id, assignment_group, requested_by, due_date, time_estimate,
              related_files, parent_id, work_type, env_dev, env_qa, env_prod, cmdb_updated,
              created, modified, completed
            FROM tasks
        ''')
        conn.execute('DROP TABLE tasks')
        conn.execute('ALTER TABLE tasks_new RENAME TO tasks')
        conn.execute('CREATE INDEX idx_tasks_section ON tasks(section_id)')
        conn.execute('CREATE INDEX idx_tasks_parent ON tasks(parent_id)')

        conn.execute('''
            CREATE TABLE scratchpad_new (
              id       INTEGER PRIMARY KEY CHECK (id = 1),
              text     TEXT NOT NULL DEFAULT '',
              modified TEXT NOT NULL DEFAULT ''
                CHECK (modified = '' OR
                       modified GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
            )
        ''')
        conn.execute('INSERT INTO scratchpad_new (id, text, modified) SELECT id, text, modified FROM scratchpad')
        conn.execute('DROP TABLE scratchpad')
        conn.execute('ALTER TABLE scratchpad_new RENAME TO scratchpad')

        violations = conn.execute('PRAGMA foreign_key_check').fetchall()
        if violations:
            conn.execute('ROLLBACK')
            raise RuntimeError('foreign key violations after tasks/scratchpad rebuild: %r' % (violations,))

        conn.execute('COMMIT')
    finally:
        conn.execute('PRAGMA foreign_keys = ON')


def ensure_database(path=None):
    """Create the database and its schema if they don't exist yet. Called
    once at server startup so a fresh clone serves an empty task list
    instead of failing on `no such table`."""
    conn = connect(path)

    try:
        init_schema(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Row <-> dict
# ---------------------------------------------------------------------------

def _task_from_row(row):
    task = {}

    for column in TASK_COLUMNS:
        value = row[column]
        if column == 'done' or column in TASK_BOOL_COLUMNS:
            task[column] = bool(value)
        elif column == 'parent_id':
            task[column] = value or ''
        elif column == 'servicenow_sys_id':
            # Absent rather than None: the JSON files had no such key on
            # tasks ServiceNow never touched, and GET /tasks.json should
            # keep looking the same.
            if value:
                task[column] = value
        else:
            task[column] = value

    return task


def _task_to_params(task):
    params = {}

    for column in TASK_WRITE_COLUMNS:
        value = task.get(column)
        if column in TASK_BOOL_COLUMNS:
            params[column] = 1 if value else 0
        elif column in ('parent_id', 'servicenow_sys_id'):
            # '' is a real value to a foreign key and would fail the
            # constraint, since no task has id ''.
            params[column] = value or None
        elif column == 'position':
            params[column] = int(value or 0)
        else:
            params[column] = '' if value is None else value

    return params


def _section_from_row(row):
    return {column: row[column] for column in SECTION_COLUMNS}


def _tag_from_row(row):
    return {
        'id': row['id'],
        'task_id': row['task_id'],
        'position': row['position'],
        'text': row['text'],
        'flag': bool(row['flag']),
    }


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def load_sections(conn):
    rows = conn.execute('SELECT * FROM sections ORDER BY position, id').fetchall()
    return [_section_from_row(row) for row in rows]


def load_tasks(conn):
    rows = conn.execute('SELECT * FROM tasks ORDER BY section_id, position, id').fetchall()
    return [_task_from_row(row) for row in rows]


def load_tags(conn):
    rows = conn.execute('SELECT * FROM tags ORDER BY task_id, position, id').fetchall()
    return [_tag_from_row(row) for row in rows]


def load_scratchpad(conn):
    """The scratchpad's freeform text, or '' if nothing has been saved yet
    (no row exists until the first save)."""
    row = conn.execute('SELECT text FROM scratchpad WHERE id = 1').fetchone()
    return row['text'] if row is not None else ''


def find_task(conn, task_id):
    row = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    return _task_from_row(row) if row is not None else None


def find_section(conn, section_id):
    row = conn.execute('SELECT * FROM sections WHERE id = ?', (section_id,)).fetchone()
    return _section_from_row(row) if row is not None else None


def section_slug_exists(conn, slug):
    """Whether a section is reachable at /tasks/<slug>. Slug only, matching
    what the JSON-era routing check did."""
    return conn.execute('SELECT 1 FROM sections WHERE slug = ?', (slug,)).fetchone() is not None


def section_name_taken(conn, slug):
    """Whether a new category called this would collide with an existing
    one. Checks id as well as slug, because handle_new_category derives the
    new section's id from the same slug."""
    row = conn.execute('SELECT 1 FROM sections WHERE slug = ? OR id = ?', (slug, slug)).fetchone()
    return row is not None


def task_exists(conn, task_id):
    return conn.execute('SELECT 1 FROM tasks WHERE id = ?', (task_id,)).fetchone() is not None


def next_task_position(conn, section_id):
    """One past the section's highest current position, not a row count:
    COUNT(*) returns an already-occupied position the moment a section has
    a gap (e.g. positions 0 and 2 after a delete that skipped
    reposition_section) - MAX(position) + 1 cannot collide with anything
    already there. COALESCE covers the empty-section case, where MAX is
    NULL rather than 0."""
    row = conn.execute(
        'SELECT COALESCE(MAX(position) + 1, 0) AS n FROM tasks WHERE section_id = ?', (section_id,)
    ).fetchone()
    return row['n']


def next_section_position(conn):
    row = conn.execute('SELECT COALESCE(MAX(position) + 1, 0) AS n FROM sections').fetchone()
    return row['n']


def tags_for_task(conn, task_id):
    rows = conn.execute(
        'SELECT * FROM tags WHERE task_id = ? ORDER BY position, id', (task_id,)
    ).fetchall()
    return [_tag_from_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Writes. Callers wrap these in `with conn:` when more than one has to land
# together.
# ---------------------------------------------------------------------------

def insert_section(conn, section):
    conn.execute(
        'INSERT INTO sections (id, position, label, slug, note) VALUES (?, ?, ?, ?, ?)',
        (
            section['id'],
            section.get('position', next_section_position(conn)),
            section['label'],
            section['slug'],
            section.get('note', '') or '',
        ),
    )


def insert_task(conn, task):
    params = _task_to_params(task)
    columns = ', '.join('"%s"' % c for c in TASK_WRITE_COLUMNS)
    placeholders = ', '.join(':%s' % c for c in TASK_WRITE_COLUMNS)
    conn.execute('INSERT INTO tasks (%s) VALUES (%s)' % (columns, placeholders), params)


def update_task(conn, task):
    """Write every writable column of `task` back to its row. The handlers
    mutate a loaded dict and hand the whole thing back, same as they did
    when the store was a JSON array."""
    params = _task_to_params(task)
    assignments = ', '.join(
        '"%s" = :%s' % (c, c) for c in TASK_WRITE_COLUMNS if c != 'id'
    )
    conn.execute('UPDATE tasks SET %s WHERE id = :id' % assignments, params)


def replace_task_tags(conn, task_id, tags):
    """Drop this task's tags and write the given list in order. `tags` is a
    list of {'id', 'text', 'flag'} dicts."""
    conn.execute('DELETE FROM tags WHERE task_id = ?', (task_id,))

    for position, tag in enumerate(tags):
        conn.execute(
            'INSERT INTO tags (id, task_id, position, text, flag) VALUES (?, ?, ?, ?, ?)',
            (tag['id'], task_id, position, tag['text'], 1 if tag.get('flag') else 0),
        )


def set_task_positions(conn, positions):
    """positions is an iterable of (task_id, position) pairs."""
    conn.executemany(
        'UPDATE tasks SET position = ? WHERE id = ?',
        [(position, task_id) for task_id, position in positions],
    )


def delete_task(conn, task_id):
    """Tags cascade; subtasks have their parent_id set to NULL. Both are
    declared in tasks_schema.sql rather than done by hand here."""
    conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))


def reposition_section(conn, section_id):
    """Renumber a section's tasks to 0..n-1, keeping their current relative
    order. The JSON-era function of the same name did this to an in-memory
    list; this one writes it."""
    rows = conn.execute(
        'SELECT id FROM tasks WHERE section_id = ? ORDER BY position, id', (section_id,)
    ).fetchall()
    set_task_positions(conn, [(row['id'], i) for i, row in enumerate(rows)])


def save_scratchpad(conn, text, modified):
    """Upserts the single scratchpad row - there is never a second one to
    insert, only ever the first save or a later overwrite."""
    conn.execute(
        'INSERT INTO scratchpad (id, text, modified) VALUES (1, ?, ?) '
        'ON CONFLICT(id) DO UPDATE SET text = excluded.text, modified = excluded.modified',
        (text, modified),
    )


# ---------------------------------------------------------------------------
# One-time migration from the JSON files (DATABASE-MIGRATION.md §5)
# ---------------------------------------------------------------------------

def _read_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except OSError:
        return default


def migrate_from_json(db_path=None, sections_file=None, tasks_file=None, tags_file=None):
    """Import the three JSON files into a fresh database. Returns a
    {table: row count} dict. Refuses to run against a database that already
    holds rows rather than importing a second copy."""
    conn = connect(db_path)

    try:
        init_schema(conn)

        existing = conn.execute('SELECT COUNT(*) AS n FROM tasks').fetchone()['n']
        existing += conn.execute('SELECT COUNT(*) AS n FROM sections').fetchone()['n']
        if existing:
            raise RuntimeError(
                'refusing to migrate: %s already has rows. Delete it first if '
                'you really mean to re-import from the JSON files.'
                % (db_path or DB_PATH)
            )

        sections = _read_json(sections_file or SECTIONS_FILE, [])
        tasks = _read_json(tasks_file or TASKS_FILE, [])
        tags = _read_json(tags_file or TAGS_FILE, [])

        # Sections and tasks first, in one transaction, so a tag can never
        # be committed pointing at a task that isn't there.
        with conn:
            for position, section in enumerate(sections):
                insert_section(conn, dict(section, position=position))

            for task in tasks:
                insert_task(conn, task)

            for tag in sorted(tags, key=lambda t: (t.get('task_id', ''), t.get('position', 0))):
                conn.execute(
                    'INSERT INTO tags (id, task_id, position, text, flag) VALUES (?, ?, ?, ?, ?)',
                    (
                        tag['id'],
                        tag['task_id'],
                        tag.get('position', 0),
                        tag.get('text', ''),
                        1 if tag.get('flag') else 0,
                    ),
                )

        return {
            'sections': len(sections),
            'tasks': len(tasks),
            'tags': len(tags),
        }
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2 or sys.argv[1] != 'migrate':
        print(__doc__)
        print('Usage: python3 backend/tasks_db.py migrate')
        sys.exit(1)

    try:
        counts = migrate_from_json()
    except RuntimeError as exc:
        print('Migration aborted: %s' % exc)
        sys.exit(1)

    print('Migrated into %s:' % DB_PATH)

    for table, count in counts.items():
        print('  %-9s %d row(s)' % (table, count))

    print('\nThe JSON files were not modified. Verify /tasks, /tasks/categories,')
    print('and a category page before relying on the database.')


if __name__ == '__main__':
    main()
