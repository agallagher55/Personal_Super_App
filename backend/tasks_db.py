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
    rows = conn.execute('SELECT * FROM sections ORDER BY position').fetchall()
    return [_section_from_row(row) for row in rows]


def load_tasks(conn):
    rows = conn.execute('SELECT * FROM tasks ORDER BY section_id, position').fetchall()
    return [_task_from_row(row) for row in rows]


def load_tags(conn):
    rows = conn.execute('SELECT * FROM tags ORDER BY task_id, position').fetchall()
    return [_tag_from_row(row) for row in rows]


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
    row = conn.execute('SELECT COUNT(*) AS n FROM tasks WHERE section_id = ?', (section_id,)).fetchone()
    return row['n']


def next_section_position(conn):
    row = conn.execute('SELECT COALESCE(MAX(position) + 1, 0) AS n FROM sections').fetchone()
    return row['n']


def tags_for_task(conn, task_id):
    rows = conn.execute(
        'SELECT * FROM tags WHERE task_id = ? ORDER BY position', (task_id,)
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
        'SELECT id FROM tasks WHERE section_id = ? ORDER BY position', (section_id,)
    ).fetchall()
    set_task_positions(conn, [(row['id'], i) for i, row in enumerate(rows)])


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
