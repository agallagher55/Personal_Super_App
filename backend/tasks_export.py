"""Export data/tasks.db back to the three JSON files.

    python3 backend/tasks_export.py            # rewrite the JSON files
    python3 backend/tasks_export.py --check    # report drift, write nothing

DATABASE-MIGRATION.md §5 kept data/sections.json, data/tasks.json and
data/tags.json committed to git as a readable fallback, but once the
database became the live store nothing wrote them any more, so they went
stale from migration day onward (§10). This is the other half: run it when
you want the committed snapshot to match reality again, then commit the
result.

It is the exact inverse of `tasks_db.py migrate`: export then re-migrate
into an empty database reproduces the same rows, and re-exporting produces
byte-identical files.

Rows come out in a deterministic order - sections by their position, tasks
by section and then position, tags by their task and then position - rather
than in whatever order they happen to sit in the table. The point is small,
readable git diffs: without it, unrelated rows would appear to move every
time. The first export after the migration will look like a large diff
because the old files were in insertion order; after that, only real
changes show up.

--check exits 1 when the files are out of date, which makes it usable from
a pre-commit hook or a scheduled job.
"""

import json
import os
import sys

import tasks_db

DATA_DIR = tasks_db.DATA_DIR

FILES = ('sections', 'tasks', 'tags')


def _ordered_rows(conn):
    """The three lists, each in a stable, human-meaningful order."""
    sections = tasks_db.load_sections(conn)
    tasks = tasks_db.load_tasks(conn)
    tags = tasks_db.load_tags(conn)

    section_order = {section['id']: i for i, section in enumerate(sections)}
    # Sections whose id somehow isn't in the table sort last rather than
    # crashing the export.
    tasks.sort(key=lambda t: (section_order.get(t['section_id'], len(section_order)), t['position']))

    task_order = {task['id']: i for i, task in enumerate(tasks)}
    tags.sort(key=lambda g: (task_order.get(g['task_id'], len(task_order)), g['position']))

    return {'sections': sections, 'tasks': tasks, 'tags': tags}


def _serialize(rows):
    """Same shape json.dump(..., indent=2) plus a trailing newline produced
    before the migration, so a no-change export is a no-change diff."""
    return json.dumps(rows, indent=2) + '\n'


def _path(data_dir, name):
    return os.path.join(data_dir or DATA_DIR, '%s.json' % name)


def _write_atomic(path, text):
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def export(db_path=None, data_dir=None, check_only=False):
    """Returns {name: (row_count, changed)} for each of the three files."""
    if not os.path.exists(db_path or tasks_db.DB_PATH):
        raise RuntimeError(
            'no database at %s - run `python3 backend/tasks_db.py migrate` first'
            % (db_path or tasks_db.DB_PATH)
        )

    conn = tasks_db.connect(db_path)

    try:
        by_name = _ordered_rows(conn)
    finally:
        conn.close()

    results = {}

    for name in FILES:
        path = _path(data_dir, name)
        text = _serialize(by_name[name])

        current = None
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                current = f.read()

        changed = current != text
        if changed and not check_only:
            _write_atomic(path, text)

        results[name] = (len(by_name[name]), changed)

    return results


def main():
    check_only = '--check' in sys.argv[1:]
    unknown = [a for a in sys.argv[1:] if a != '--check']

    if unknown:
        print('Unknown argument(s): %s' % ' '.join(unknown))
        print(__doc__)
        sys.exit(1)

    try:
        results = export(check_only=check_only)
    except RuntimeError as exc:
        print('Export failed: %s' % exc)
        sys.exit(1)

    stale = [name for name, (_, changed) in results.items() if changed]

    for name in FILES:
        count, changed = results[name]
        if check_only:
            state = 'STALE' if changed else 'up to date'
        else:
            state = 'rewritten' if changed else 'unchanged'
        print('  %-9s %3d row(s)  %s' % (name, count, state))

    if not stale:
        print('\nThe JSON files already match %s.' % tasks_db.DB_PATH)
        return

    if check_only:
        print('\nOut of date: %s. Run `python3 backend/tasks_export.py` to refresh.'
              % ', '.join('%s.json' % n for n in stale))
        sys.exit(1)

    print('\nRewrote %s from %s. Commit them to update the git-backed snapshot.'
          % (', '.join('%s.json' % n for n in stale), tasks_db.DB_PATH))


if __name__ == '__main__':
    main()
