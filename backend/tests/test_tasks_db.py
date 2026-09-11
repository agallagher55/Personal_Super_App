import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tasks_db  # noqa: E402


def a_task(task_id='t1', **overrides):
    task = {
        'id': task_id,
        'section_id': 's1',
        'position': 0,
        'desc': 'Do the thing.',
        'note': '',
        'notes': '',
        'status': 'open',
        'done': False,
        'created': '2026-01-01T00:00:00Z',
        'modified': '2026-01-01T00:00:00Z',
        'completed': '',
        'priority': 'medium',
        'ticket_number': '',
        'assignment_group': '',
        'requested_by': '',
        'due_date': '',
        'focus_today': False,
        'follow_up_date': '',
        'time_estimate': '',
        'related_files': '',
        'parent_id': '',
        'work_type': '',
        'env_dev': False,
        'env_qa': False,
        'env_prod': False,
        'cmdb_updated': False,
        'source_opened_at': '',
        'source_updated_at': '',
        'last_seen_at': '',
        'source_missing': False,
    }
    task.update(overrides)
    return task


class DatabaseTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'tasks.db')
        self.conn = tasks_db.connect(self.db_path)
        tasks_db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def given_section(self, section_id='s1', position=0, label='Section', slug=None):
        tasks_db.insert_section(self.conn, {
            'id': section_id,
            'position': position,
            'label': label,
            'slug': slug or section_id,
            'note': '',
        })
        self.conn.commit()


class TestSchema(DatabaseTestCase):

    def test_creates_all_three_tables(self):
        names = {
            row['name']
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        self.assertTrue({'sections', 'tasks', 'tags', 'sync_runs'} <= names)

    def test_init_schema_is_idempotent(self):
        self.given_section()
        tasks_db.init_schema(self.conn)
        self.assertEqual(len(tasks_db.load_sections(self.conn)), 1)

    def test_foreign_keys_are_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task(section_id='no-such-section'))

    def test_sections_keep_their_order(self):
        self.given_section('c', position=0, label='C')
        self.given_section('a', position=1, label='A')
        self.given_section('b', position=2, label='B')
        # Insertion order, not alphabetical: a JSON array had an order and
        # the table has to reproduce it.
        self.assertEqual([s['id'] for s in tasks_db.load_sections(self.conn)], ['c', 'a', 'b'])


class TestSchemaMigrations(DatabaseTestCase):
    """Issue: versioned schema migrations for tasks.db - PRAGMA user_version
    tracking so a future column/constraint change has an upgrade path,
    mirroring backend/finance/db.py's SCHEMA_VERSION/migrate() pattern."""

    def test_fresh_database_starts_at_current_version(self):
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        self.assertEqual(version, tasks_db.SCHEMA_VERSION)

    def test_running_init_schema_repeatedly_is_idempotent(self):
        self.given_section()
        tasks_db.insert_task(self.conn, a_task())

        tasks_db.init_schema(self.conn)
        tasks_db.init_schema(self.conn)

        self.assertEqual(len(tasks_db.load_tasks(self.conn)), 1)
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        self.assertEqual(version, tasks_db.SCHEMA_VERSION)

    def test_an_older_database_is_upgraded_without_losing_data(self):
        """Stages a database the way one created before this module tracked
        a schema version would look: tables already at today's shape (the
        only shape tasks_schema.sql has ever had), but user_version still
        at 0. migrate() must bring it up to date without touching the rows
        already there."""
        self.given_section()
        tasks_db.insert_task(self.conn, a_task())
        self.conn.execute('PRAGMA user_version = 0')
        self.conn.commit()

        tasks_db.migrate(self.conn)

        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], tasks_db.SCHEMA_VERSION)
        self.assertEqual(len(tasks_db.load_sections(self.conn)), 1)
        self.assertEqual(len(tasks_db.load_tasks(self.conn)), 1)

    def test_migrate_is_idempotent(self):
        self.conn.execute('PRAGMA user_version = 0')
        self.conn.commit()

        tasks_db.migrate(self.conn)
        after_first = self.conn.execute('PRAGMA user_version').fetchone()[0]

        tasks_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], after_first)


class TestPositionCollisionSafety(DatabaseTestCase):
    """Issue: collision-safe and deterministic position ordering.
    next_task_position() must never hand out an already-occupied position,
    and reads must resolve equal positions the same way every time."""

    def setUp(self):
        super().setUp()
        self.given_section()

    def test_next_position_skips_a_gap_instead_of_reusing_it(self):
        """A section with positions 0 and 2 (e.g. after a delete that
        skipped reposition_section) must not hand out 1 by counting rows -
        1 belongs to nothing, but a COUNT(*) of 2 rows would suggest it's
        free next-in-line, when in fact 2 is already occupied."""
        tasks_db.insert_task(self.conn, a_task('t0', position=0))
        tasks_db.insert_task(self.conn, a_task('t2', position=2))
        self.assertEqual(tasks_db.next_task_position(self.conn, 's1'), 3)

    def test_next_position_is_zero_for_an_empty_section(self):
        self.assertEqual(tasks_db.next_task_position(self.conn, 's1'), 0)

    def test_next_position_ignores_other_sections(self):
        self.given_section('s2', position=1, label='Other')
        tasks_db.insert_task(self.conn, a_task('t1', section_id='s2', position=0))
        self.assertEqual(tasks_db.next_task_position(self.conn, 's1'), 0)

    def test_inserting_into_a_gapped_section_repeatedly_never_collides(self):
        tasks_db.insert_task(self.conn, a_task('t0', position=0))
        tasks_db.insert_task(self.conn, a_task('t2', position=2))

        for i in range(3, 6):
            new_id = 't%d' % i
            tasks_db.insert_task(self.conn, a_task(new_id, position=tasks_db.next_task_position(self.conn, 's1')))

        positions = [t['position'] for t in tasks_db.load_tasks(self.conn)]
        self.assertEqual(len(positions), len(set(positions)), 'positions collided: %r' % positions)

    def test_equal_positions_render_in_a_deterministic_order(self):
        """Legacy data predating the MAX+1 fix could still share a
        position; reads must not depend on SQLite's unspecified scan order
        for ties."""
        tasks_db.insert_task(self.conn, a_task('t-z', position=0))
        tasks_db.insert_task(self.conn, a_task('t-a', position=0))

        first = [t['id'] for t in tasks_db.load_tasks(self.conn)]
        second = [t['id'] for t in tasks_db.load_tasks(self.conn)]
        self.assertEqual(first, second)
        self.assertEqual(first, ['t-a', 't-z'])  # tie-break is `id`, ascending

    def test_swapping_two_positions_succeeds_without_a_transient_collision_error(self):
        """set_task_positions writes one row at a time, so a swap passes
        through a moment where both rows would share a position under a
        naive read - it must not raise, since positions aren't declared
        UNIQUE (see tasks_schema.sql)."""
        tasks_db.insert_task(self.conn, a_task('t0', position=0))
        tasks_db.insert_task(self.conn, a_task('t1', position=1))

        with self.conn:
            tasks_db.set_task_positions(self.conn, [('t0', 1), ('t1', 0)])

        self.assertEqual(tasks_db.find_task(self.conn, 't0')['position'], 1)
        self.assertEqual(tasks_db.find_task(self.conn, 't1')['position'], 0)

    def test_tags_with_equal_positions_render_deterministically(self):
        tasks_db.insert_task(self.conn, a_task())
        self.conn.executemany(
            'INSERT INTO tags (id, task_id, position, text, flag) VALUES (?, ?, 0, ?, 0)',
            [('g-z', 't1', 'zebra'), ('g-a', 't1', 'apple')],
        )
        self.assertEqual([t['id'] for t in tasks_db.tags_for_task(self.conn, 't1')], ['g-a', 'g-z'])


class TestTaskDomainConstraints(DatabaseTestCase):
    """Issue: CHECK constraints for task enums and booleans. A fresh
    database (tasks_schema.sql) rejects undocumented status/priority/
    work_type values and non-0/1 booleans directly - no migration involved
    here, that's TestTaskDomainConstraintsMigration below."""

    def setUp(self):
        super().setUp()
        self.given_section()

    def test_accepts_every_documented_status(self):
        for i, status in enumerate(('open', 'in-progress', 'pending', 'done', 'cancelled')):
            tasks_db.insert_task(self.conn, a_task('t%d' % i, position=i, status=status))

    def test_rejects_an_undocumented_status(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task(status='archived'))

    def test_accepts_every_documented_priority(self):
        for i, priority in enumerate(('low', 'medium', 'high')):
            tasks_db.insert_task(self.conn, a_task('t%d' % i, position=i, priority=priority))

    def test_rejects_an_undocumented_priority(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task(priority='urgent'))

    def test_accepts_every_documented_work_type_and_the_empty_sentinel(self):
        for i, work_type in enumerate(('', 'new-feature', 'schema-change')):
            tasks_db.insert_task(self.conn, a_task('t%d' % i, position=i, work_type=work_type))

    def test_rejects_an_undocumented_work_type(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task(work_type='bugfix'))

    def test_rejects_a_non_01_boolean_column(self):
        tasks_db.insert_task(self.conn, a_task())
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE tasks SET env_dev = 2 WHERE id = 't1'")

    def test_rejects_a_non_01_tag_flag(self):
        tasks_db.insert_task(self.conn, a_task())
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO tags (id, task_id, position, text, flag) VALUES ('g1', 't1', 0, 'x', 2)"
            )


class TestTaskDomainConstraintsMigration(unittest.TestCase):
    """Migration 2 (tasks_db._add_task_domain_constraints): rebuilds tasks
    and tags with the CHECK constraints above, staged here as the
    unconstrained shape every tasks.db had before this migration - a
    parent/child pair and a tag, so the rebuild's foreign keys (parent_id,
    tags.task_id) have something real to preserve, plus one
    already-invalid value per column to prove the pre-rebuild
    normalization pass, not just the constraint itself."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = tasks_db.connect(os.path.join(self.tmp_dir.name, 'tasks.db'))
        self.conn.executescript('''
            CREATE TABLE sections (
              id TEXT PRIMARY KEY, position INTEGER NOT NULL, label TEXT NOT NULL,
              slug TEXT NOT NULL UNIQUE, note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE tasks (
              id TEXT PRIMARY KEY, section_id TEXT NOT NULL REFERENCES sections(id),
              position INTEGER NOT NULL, "desc" TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
              done INTEGER GENERATED ALWAYS AS (status = 'done') VIRTUAL,
              priority TEXT NOT NULL DEFAULT 'medium', ticket_number TEXT NOT NULL DEFAULT '',
              servicenow_sys_id TEXT, assignment_group TEXT NOT NULL DEFAULT '',
              requested_by TEXT NOT NULL DEFAULT '', due_date TEXT NOT NULL DEFAULT '',
              time_estimate TEXT NOT NULL DEFAULT '', related_files TEXT NOT NULL DEFAULT '',
              parent_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
              work_type TEXT NOT NULL DEFAULT '', env_dev INTEGER NOT NULL DEFAULT 0,
              env_qa INTEGER NOT NULL DEFAULT 0, env_prod INTEGER NOT NULL DEFAULT 0,
              cmdb_updated INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
              modified TEXT NOT NULL, completed TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE tags (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              position INTEGER NOT NULL, text TEXT NOT NULL, flag INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE scratchpad (
              id INTEGER PRIMARY KEY CHECK (id = 1), text TEXT NOT NULL DEFAULT '',
              modified TEXT NOT NULL DEFAULT ''
            );
        ''')
        self.conn.execute("INSERT INTO sections VALUES ('s1', 0, 'Sec', 's1', '')")
        self.conn.execute(
            '''INSERT INTO tasks (id, section_id, position, "desc", status, priority, work_type,
                                   env_dev, created, modified)
               VALUES ('parent', 's1', 0, 'Parent', 'bogus-status', 'medium', '', 0,
                       '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')'''
        )
        self.conn.execute(
            '''INSERT INTO tasks (id, section_id, position, "desc", status, priority, parent_id,
                                   env_qa, created, modified)
               VALUES ('child', 's1', 1, 'Child', 'done', 'super-high', 'parent', 5,
                       '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')'''
        )
        self.conn.execute(
            "INSERT INTO tags (id, task_id, position, text, flag) VALUES ('g1', 'child', 0, 'x', 7)"
        )
        self.conn.execute('PRAGMA user_version = 1')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_normalizes_an_undocumented_status_to_open(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(tasks_db.find_task(self.conn, 'parent')['status'], 'open')

    def test_normalizes_an_undocumented_priority_to_medium(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(tasks_db.find_task(self.conn, 'child')['priority'], 'medium')

    def test_normalizes_a_non_01_boolean_to_zero(self):
        tasks_db.migrate(self.conn)
        self.assertIs(tasks_db.find_task(self.conn, 'child')['env_qa'], False)

    def test_normalizes_a_non_01_tag_flag_to_zero(self):
        tasks_db.migrate(self.conn)
        self.assertIs(tasks_db.tags_for_task(self.conn, 'child')[0]['flag'], False)

    def test_preserves_the_parent_child_relationship(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(tasks_db.find_task(self.conn, 'child')['parent_id'], 'parent')

    def test_preserves_the_tag(self):
        tasks_db.migrate(self.conn)
        self.assertEqual([t['text'] for t in tasks_db.tags_for_task(self.conn, 'child')], ['x'])

    def test_generated_done_column_still_works_after_the_rebuild(self):
        tasks_db.migrate(self.conn)
        self.assertIs(tasks_db.find_task(self.conn, 'child')['done'], True)
        self.assertIs(tasks_db.find_task(self.conn, 'parent')['done'], False)

    def test_indexes_survive_the_rebuild(self):
        tasks_db.migrate(self.conn)
        names = {row['name'] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        self.assertTrue({'idx_tasks_section', 'idx_tasks_parent', 'idx_tags_task'} <= names)

    def test_foreign_keys_are_intact_after_the_rebuild(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_constraints_actually_apply_once_the_rebuild_lands(self):
        tasks_db.migrate(self.conn)
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task('bad', section_id='s1', position=5, status='nope'))

    def test_is_idempotent(self):
        tasks_db.migrate(self.conn)
        tasks_db.migrate(self.conn)
        self.assertEqual(tasks_db.find_task(self.conn, 'child')['parent_id'], 'parent')

    def test_records_the_schema_version(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], tasks_db.SCHEMA_VERSION)

    def test_a_rejected_rebuild_leaves_the_version_and_data_untouched(self):
        """Forces the rebuild's own integrity gate to fire (by breaking the
        foreign_key_check it inspects before committing) and confirms the
        documented guarantee: migrate() must not bump user_version, or a
        later run would wrongly believe this migration already succeeded
        and skip retrying it."""
        # foreign_keys was on for this fixture's setUp inserts; turned off
        # here to stage the kind of orphaned row FK enforcement would
        # normally prevent, and that the rebuild's own foreign_key_check
        # has to catch instead.
        self.conn.execute('PRAGMA foreign_keys = OFF')
        self.conn.execute(
            "INSERT INTO tags (id, task_id, position, text, flag) VALUES ('orphan', 'no-such-task', 0, 'x', 0)"
        )
        self.conn.commit()

        with self.assertRaises(RuntimeError):
            tasks_db.migrate(self.conn)

        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], 1)
        # The original (unconstrained) tasks table must still be there,
        # untouched by the rolled-back rebuild.
        self.assertIsNotNone(tasks_db.find_task(self.conn, 'parent'))


class TestDateFormatConstraints(DatabaseTestCase):
    """Issue: canonical date/timestamp validation. A fresh database
    rejects a malformed due_date/created/modified/completed directly -
    shape-only (GLOB), not a real calendar check, see tasks_schema.sql's
    comment for why."""

    def setUp(self):
        super().setUp()
        self.given_section()

    def test_accepts_an_empty_due_date(self):
        tasks_db.insert_task(self.conn, a_task(due_date=''))

    def test_accepts_a_well_formed_due_date(self):
        tasks_db.insert_task(self.conn, a_task(due_date='2026-09-10'))

    def test_rejects_a_malformed_due_date(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task(due_date='next week'))

    def test_rejects_a_timestamp_in_due_date(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task(due_date='2026-09-10T00:00:00Z'))

    def test_rejects_a_malformed_created(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task(created='2026-09-01'))

    def test_rejects_a_malformed_completed(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task(status='done', completed='yesterday'))

    def test_accepts_an_empty_completed(self):
        tasks_db.insert_task(self.conn, a_task(completed=''))

    def test_rejects_a_malformed_scratchpad_modified(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO scratchpad_entries (entry_date, text, modified) VALUES ('2026-09-10', 'x', 'whenever')"
            )

    def test_rejects_a_malformed_scratchpad_entry_date(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO scratchpad_entries (entry_date, text, modified) VALUES ('not-a-date', 'x', '')"
            )


class TestDateFormatConstraintsMigration(unittest.TestCase):
    """Migration 3 (tasks_db._add_date_format_constraints): rebuilds
    tasks and scratchpad with the date/timestamp CHECK constraints,
    staged here as the shape every tasks.db had before this migration."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.conn = tasks_db.connect(os.path.join(self.tmp_dir.name, 'tasks.db'))
        # The pre-migration-3 shape: migration 2's enum/boolean constraints
        # already in place (that migration isn't this one's concern), but
        # no date/timestamp constraints yet.
        self.conn.executescript('''
            CREATE TABLE sections (
              id TEXT PRIMARY KEY, position INTEGER NOT NULL, label TEXT NOT NULL,
              slug TEXT NOT NULL UNIQUE, note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE tasks (
              id TEXT PRIMARY KEY, section_id TEXT NOT NULL REFERENCES sections(id),
              position INTEGER NOT NULL, "desc" TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'in-progress', 'pending', 'done', 'cancelled')),
              done INTEGER GENERATED ALWAYS AS (status = 'done') VIRTUAL,
              priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
              ticket_number TEXT NOT NULL DEFAULT '', servicenow_sys_id TEXT,
              assignment_group TEXT NOT NULL DEFAULT '', requested_by TEXT NOT NULL DEFAULT '',
              due_date TEXT NOT NULL DEFAULT '', time_estimate TEXT NOT NULL DEFAULT '',
              related_files TEXT NOT NULL DEFAULT '',
              parent_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
              work_type TEXT NOT NULL DEFAULT '' CHECK (work_type IN ('', 'new-feature', 'schema-change')),
              env_dev INTEGER NOT NULL DEFAULT 0 CHECK (env_dev IN (0, 1)),
              env_qa INTEGER NOT NULL DEFAULT 0 CHECK (env_qa IN (0, 1)),
              env_prod INTEGER NOT NULL DEFAULT 0 CHECK (env_prod IN (0, 1)),
              cmdb_updated INTEGER NOT NULL DEFAULT 0 CHECK (cmdb_updated IN (0, 1)),
              created TEXT NOT NULL, modified TEXT NOT NULL, completed TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE tags (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
              position INTEGER NOT NULL, text TEXT NOT NULL, flag INTEGER NOT NULL DEFAULT 0 CHECK (flag IN (0, 1))
            );
            CREATE TABLE scratchpad (
              id INTEGER PRIMARY KEY CHECK (id = 1), text TEXT NOT NULL DEFAULT '',
              modified TEXT NOT NULL DEFAULT ''
            );
        ''')
        self.conn.execute("INSERT INTO sections VALUES ('s1', 0, 'Sec', 's1', '')")
        self.conn.execute(
            '''INSERT INTO tasks (id, section_id, position, "desc", due_date, created, modified)
               VALUES ('parent', 's1', 0, 'Parent', '2026-09-10', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')'''
        )
        self.conn.execute(
            '''INSERT INTO tasks (id, section_id, position, "desc", parent_id, created, modified)
               VALUES ('child', 's1', 1, 'Child', 'parent', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')'''
        )
        self.conn.execute("INSERT INTO tags (id, task_id, position, text, flag) VALUES ('g1', 'child', 0, 'x', 0)")
        self.conn.execute("INSERT INTO scratchpad (id, text, modified) VALUES (1, 'hi', '2026-09-01T00:00:00Z')")
        self.conn.execute('PRAGMA user_version = 2')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_constraints_apply_once_the_rebuild_lands(self):
        tasks_db.migrate(self.conn)
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.insert_task(self.conn, a_task('bad', position=5, due_date='not-a-date'))

    def test_preserves_the_parent_child_relationship(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(tasks_db.find_task(self.conn, 'child')['parent_id'], 'parent')

    def test_preserves_the_due_date(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(tasks_db.find_task(self.conn, 'parent')['due_date'], '2026-09-10')

    def test_adds_triage_fields_with_safe_defaults(self):
        tasks_db.migrate(self.conn)
        task = tasks_db.find_task(self.conn, 'parent')
        self.assertIs(task['focus_today'], False)
        self.assertEqual(task['follow_up_date'], '')

    def test_preserves_the_tag(self):
        tasks_db.migrate(self.conn)
        self.assertEqual([t['text'] for t in tasks_db.tags_for_task(self.conn, 'child')], ['x'])

    def test_preserves_the_scratchpad(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-09-01'), 'hi')

    def test_foreign_keys_are_intact_after_the_rebuild(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_is_idempotent(self):
        tasks_db.migrate(self.conn)
        tasks_db.migrate(self.conn)
        self.assertEqual(tasks_db.find_task(self.conn, 'child')['parent_id'], 'parent')

    def test_records_the_schema_version(self):
        tasks_db.migrate(self.conn)
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], tasks_db.SCHEMA_VERSION)

    def test_refuses_to_migrate_an_existing_malformed_due_date(self):
        self.conn.execute("UPDATE tasks SET due_date = 'next week' WHERE id = 'parent'")
        self.conn.commit()

        with self.assertRaises(RuntimeError):
            tasks_db.migrate(self.conn)

        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertEqual(tasks_db.find_task(self.conn, 'parent')['due_date'], 'next week')


class TestGeneratedDoneColumn(DatabaseTestCase):

    def setUp(self):
        super().setUp()
        self.given_section()

    def test_done_follows_status(self):
        tasks_db.insert_task(self.conn, a_task(status='done'))
        self.assertIs(tasks_db.find_task(self.conn, 't1')['done'], True)

    def test_done_is_false_for_every_other_status(self):
        for i, status in enumerate(('open', 'in-progress', 'pending', 'cancelled')):
            tasks_db.insert_task(self.conn, a_task('t%d' % i, position=i, status=status))
            self.assertIs(tasks_db.find_task(self.conn, 't%d' % i)['done'], False)

    def test_done_cannot_drift_from_status(self):
        """The whole point of the generated column: a caller passing a
        contradictory `done` cannot make it stick."""
        tasks_db.insert_task(self.conn, a_task(status='done', done=False))
        self.assertIs(tasks_db.find_task(self.conn, 't1')['done'], True)

        stored = tasks_db.find_task(self.conn, 't1')
        stored['status'] = 'open'
        stored['done'] = True
        tasks_db.update_task(self.conn, stored)
        self.assertIs(tasks_db.find_task(self.conn, 't1')['done'], False)

    def test_done_is_not_a_writable_column(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.conn.execute("UPDATE tasks SET done = 1 WHERE id = 't1'")


class TestTaskRoundTrip(DatabaseTestCase):

    def setUp(self):
        super().setUp()
        self.given_section()

    def test_round_trips_every_field(self):
        original = a_task(
            note='A note.',
            notes='Long notes.',
            status='in-progress',
            priority='high',
            ticket_number='INC1234',
            assignment_group='GIS',
            requested_by='Someone',
            due_date='2026-02-01',
            focus_today=True,
            follow_up_date='2026-02-02',
            time_estimate='2h',
            related_files='a.py, b.py',
            work_type='new-feature',
            env_dev=True,
            env_prod=True,
            source_opened_at='2024-01-01T04:00:00Z',
            source_updated_at='2026-09-10T14:15:16Z',
            last_seen_at='2026-09-10T15:00:00Z',
            source_missing=True,
        )
        tasks_db.insert_task(self.conn, original)
        stored = tasks_db.find_task(self.conn, 't1')

        for field, value in original.items():
            self.assertEqual(stored[field], value, field)

    def test_booleans_come_back_as_booleans(self):
        """SQLite stores these as INTEGER. GET /tasks.json promised JSON
        true/false before the migration and has to keep doing so."""
        tasks_db.insert_task(self.conn, a_task(env_dev=True, cmdb_updated=True))
        stored = tasks_db.find_task(self.conn, 't1')

        for field in ('focus_today', 'env_dev', 'env_qa', 'env_prod', 'cmdb_updated',
                      'source_missing', 'done'):
            self.assertIsInstance(stored[field], bool, field)

    def test_triage_fields_validate_and_round_trip(self):
        tasks_db.insert_task(self.conn, a_task(focus_today=True, follow_up_date='2026-09-12'))
        stored = tasks_db.find_task(self.conn, 't1')
        self.assertIs(stored['focus_today'], True)
        self.assertEqual(stored['follow_up_date'], '2026-09-12')

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE tasks SET follow_up_date = 'next week' WHERE id = 't1'")

    def test_empty_parent_id_round_trips_as_empty_string(self):
        tasks_db.insert_task(self.conn, a_task(parent_id=''))
        self.assertEqual(tasks_db.find_task(self.conn, 't1')['parent_id'], '')
        # NULL on disk, so the foreign key doesn't try to resolve ''.
        row = self.conn.execute("SELECT parent_id FROM tasks WHERE id = 't1'").fetchone()
        self.assertIsNone(row['parent_id'])

    def test_real_parent_id_round_trips(self):
        tasks_db.insert_task(self.conn, a_task('parent'))
        tasks_db.insert_task(self.conn, a_task('child', position=1, parent_id='parent'))
        self.assertEqual(tasks_db.find_task(self.conn, 'child')['parent_id'], 'parent')

    def test_servicenow_sys_id_is_absent_unless_set(self):
        tasks_db.insert_task(self.conn, a_task())
        self.assertNotIn('servicenow_sys_id', tasks_db.find_task(self.conn, 't1'))

        tasks_db.insert_task(self.conn, a_task('t2', position=1, servicenow_sys_id='abc123'))
        self.assertEqual(tasks_db.find_task(self.conn, 't2')['servicenow_sys_id'], 'abc123')

    def test_update_task_writes_every_field_back(self):
        tasks_db.insert_task(self.conn, a_task())
        stored = tasks_db.find_task(self.conn, 't1')
        stored['desc'] = 'Changed.'
        stored['env_qa'] = True
        tasks_db.update_task(self.conn, stored)

        reloaded = tasks_db.find_task(self.conn, 't1')
        self.assertEqual(reloaded['desc'], 'Changed.')
        self.assertIs(reloaded['env_qa'], True)

    def test_find_task_returns_none_when_missing(self):
        self.assertIsNone(tasks_db.find_task(self.conn, 'nope'))


class TestSyncRuns(DatabaseTestCase):

    def test_round_trips_the_latest_run_and_previous_success(self):
        tasks_db.insert_sync_run(self.conn, {
            'started_at': '2026-09-10T10:00:00Z',
            'finished_at': '2026-09-10T10:01:00Z',
            'result': 'ok',
            'records_seen': 5,
            'created_count': 2,
            'updated_count': 1,
            'unchanged_count': 2,
            'query_fingerprint': 'first',
        })
        tasks_db.insert_sync_run(self.conn, {
            'started_at': '2026-09-10T11:00:00Z',
            'finished_at': '2026-09-10T11:00:10Z',
            'result': 'ok',
            'records_seen': 5,
            'query_fingerprint': 'second',
        })

        status = tasks_db.load_sync_status(self.conn)

        self.assertEqual(status['latest_run']['records_seen'], 5)
        self.assertEqual(status['latest_run']['query_fingerprint'], 'second')
        self.assertEqual(status['previous_success_started_at'], '2026-09-10T10:00:00Z')

    def test_error_run_uses_the_latest_success_as_its_baseline(self):
        tasks_db.insert_sync_run(self.conn, {
            'started_at': '2026-09-10T10:00:00Z',
            'finished_at': '2026-09-10T10:01:00Z',
            'result': 'ok',
        })
        tasks_db.insert_sync_run(self.conn, {
            'started_at': '2026-09-10T11:00:00Z',
            'finished_at': '2026-09-10T11:00:10Z',
            'result': 'error',
            'error': 'network unavailable',
        })

        status = tasks_db.load_sync_status(self.conn)

        self.assertEqual(status['latest_run']['result'], 'error')
        self.assertEqual(status['previous_success_started_at'], '2026-09-10T10:00:00Z')


class TestSyncHealthMigration(DatabaseTestCase):

    def test_version_four_database_keeps_tasks_and_gains_sync_health(self):
        self.given_section()
        tasks_db.insert_task(self.conn, a_task(notes='Personal note'))
        self.conn.execute('DROP TABLE sync_runs')
        self.conn.execute('PRAGMA user_version = 4')
        self.conn.commit()

        tasks_db.migrate(self.conn)
        tasks_db.migrate(self.conn)

        columns = {row['name'] for row in self.conn.execute('PRAGMA table_info(tasks)')}
        self.assertTrue({'source_opened_at', 'source_updated_at', 'last_seen_at'} <= columns)
        self.assertEqual(tasks_db.find_task(self.conn, 't1')['notes'], 'Personal note')
        self.assertEqual(self.conn.execute('PRAGMA user_version').fetchone()[0], tasks_db.SCHEMA_VERSION)
        self.assertIn('sync_runs', {
            row['name'] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        })

    def test_version_six_database_gains_missing_flags_without_losing_notes(self):
        self.given_section()
        tasks_db.insert_task(self.conn, a_task(notes='Keep this personal note'))
        self.conn.execute('PRAGMA user_version = 6')
        self.conn.execute('ALTER TABLE tasks DROP COLUMN source_missing')
        self.conn.execute('ALTER TABLE sync_runs DROP COLUMN missing_count')
        self.conn.commit()

        tasks_db.migrate(self.conn)
        tasks_db.migrate(self.conn)

        stored = tasks_db.find_task(self.conn, 't1')
        self.assertEqual(stored['notes'], 'Keep this personal note')
        self.assertIs(stored['source_missing'], False)
        self.assertIn('missing_count', {
            row['name'] for row in self.conn.execute('PRAGMA table_info(sync_runs)')
        })


class TestTags(DatabaseTestCase):

    def setUp(self):
        super().setUp()
        self.given_section()
        tasks_db.insert_task(self.conn, a_task())

    def test_replace_task_tags_keeps_submitted_order(self):
        tasks_db.replace_task_tags(self.conn, 't1', [
            {'id': 'g1', 'text': 'zebra', 'flag': False},
            {'id': 'g2', 'text': 'apple', 'flag': True},
        ])
        tags = tasks_db.tags_for_task(self.conn, 't1')
        self.assertEqual([t['text'] for t in tags], ['zebra', 'apple'])
        self.assertEqual([t['position'] for t in tags], [0, 1])
        self.assertIs(tags[1]['flag'], True)

    def test_replace_task_tags_drops_the_previous_set(self):
        tasks_db.replace_task_tags(self.conn, 't1', [{'id': 'g1', 'text': 'old', 'flag': False}])
        tasks_db.replace_task_tags(self.conn, 't1', [{'id': 'g2', 'text': 'new', 'flag': False}])
        self.assertEqual([t['text'] for t in tasks_db.tags_for_task(self.conn, 't1')], ['new'])


class TestDelete(DatabaseTestCase):

    def setUp(self):
        super().setUp()
        self.given_section()

    def test_deleting_a_task_removes_its_tags(self):
        tasks_db.insert_task(self.conn, a_task())
        tasks_db.replace_task_tags(self.conn, 't1', [{'id': 'g1', 'text': 'x', 'flag': False}])
        tasks_db.delete_task(self.conn, 't1')
        self.assertEqual(tasks_db.load_tags(self.conn), [])

    def test_deleting_a_parent_leaves_its_children(self):
        """Deleting a task with subtasks succeeded before the migration and
        has to keep succeeding: the children are orphaned, not blocked."""
        tasks_db.insert_task(self.conn, a_task('parent'))
        tasks_db.insert_task(self.conn, a_task('child', position=1, parent_id='parent'))
        tasks_db.delete_task(self.conn, 'parent')

        child = tasks_db.find_task(self.conn, 'child')
        self.assertIsNotNone(child)
        self.assertEqual(child['parent_id'], '')

    def test_reposition_section_closes_the_gap(self):
        for i in range(3):
            tasks_db.insert_task(self.conn, a_task('t%d' % i, position=i))
        tasks_db.delete_task(self.conn, 't1')
        tasks_db.reposition_section(self.conn, 's1')

        remaining = tasks_db.load_tasks(self.conn)
        self.assertEqual([(t['id'], t['position']) for t in remaining], [('t0', 0), ('t2', 1)])


class TestScratchpad(DatabaseTestCase):

    def test_empty_before_any_save(self):
        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-01-01'), '')

    def test_round_trips_saved_text(self):
        tasks_db.save_scratchpad(self.conn, '2026-01-01', 'Buy milk\nCall dentist', '2026-01-01T00:00:00Z')
        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-01-01'), 'Buy milk\nCall dentist')

    def test_saving_again_on_the_same_date_overwrites_rather_than_adding_a_row(self):
        tasks_db.save_scratchpad(self.conn, '2026-01-01', 'First draft', '2026-01-01T00:00:00Z')
        tasks_db.save_scratchpad(self.conn, '2026-01-01', 'Second draft', '2026-01-01T12:00:00Z')

        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-01-01'), 'Second draft')
        count = self.conn.execute('SELECT COUNT(*) AS n FROM scratchpad_entries').fetchone()['n']
        self.assertEqual(count, 1)

    def test_saving_empty_text_clears_it(self):
        tasks_db.save_scratchpad(self.conn, '2026-01-01', 'Something', '2026-01-01T00:00:00Z')
        tasks_db.save_scratchpad(self.conn, '2026-01-01', '', '2026-01-01T12:00:00Z')
        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-01-01'), '')

    def test_two_distinct_dates_do_not_cross_contaminate(self):
        tasks_db.save_scratchpad(self.conn, '2026-01-01', 'Day one', '2026-01-01T00:00:00Z')
        tasks_db.save_scratchpad(self.conn, '2026-01-02', 'Day two', '2026-01-02T00:00:00Z')

        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-01-01'), 'Day one')
        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-01-02'), 'Day two')

    def test_a_date_with_no_entry_is_empty_even_when_others_have_text(self):
        tasks_db.save_scratchpad(self.conn, '2026-01-01', 'Day one', '2026-01-01T00:00:00Z')
        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-01-02'), '')

    def test_most_recent_date_is_empty_before_any_save(self):
        self.assertEqual(tasks_db.most_recent_scratchpad_date(self.conn), '')

    def test_most_recent_date_tracks_the_latest_entry_by_date(self):
        tasks_db.save_scratchpad(self.conn, '2026-01-01', 'Day one', '2026-01-01T00:00:00Z')
        tasks_db.save_scratchpad(self.conn, '2026-01-03', 'Day three', '2026-01-03T00:00:00Z')
        tasks_db.save_scratchpad(self.conn, '2026-01-02', 'Day two', '2026-01-02T00:00:00Z')

        self.assertEqual(tasks_db.most_recent_scratchpad_date(self.conn), '2026-01-03')

    def test_rejects_a_malformed_entry_date(self):
        with self.assertRaises(sqlite3.IntegrityError):
            tasks_db.save_scratchpad(self.conn, 'not-a-date', 'x', '2026-01-01T00:00:00Z')


class TestScratchpadEntriesMigration(DatabaseTestCase):
    """Migration 6 (tasks_db._add_scratchpad_entries): replaces the single
    timeless scratchpad row with one row per calendar date. This is the one
    migration that touches text the user typed by hand and cannot
    reconstruct, so it gets its own coverage beyond the general schema
    migration tests."""

    def _stage_pre_migration_scratchpad(self, text, modified):
        """DatabaseTestCase already built the current (post-migration-6)
        schema, which has no `scratchpad` table at all - recreate the
        version-5 singleton-row shape in its place, the way a real
        pre-upgrade database still has it, then wind the version back."""
        self.conn.execute('DROP TABLE scratchpad_entries')
        self.conn.execute('''
            CREATE TABLE scratchpad (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              text TEXT NOT NULL DEFAULT '',
              modified TEXT NOT NULL DEFAULT ''
                CHECK (modified = '' OR
                       modified GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z')
            )
        ''')
        if text or modified:
            self.conn.execute('INSERT INTO scratchpad (id, text, modified) VALUES (1, ?, ?)', (text, modified))
        self.conn.execute('PRAGMA user_version = 5')
        self.conn.commit()

    def test_migrates_existing_text_onto_its_modified_date(self):
        self._stage_pre_migration_scratchpad('Buy milk\nCall dentist', '2026-09-05T14:30:00Z')
        tasks_db.migrate(self.conn)

        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-09-05'), 'Buy milk\nCall dentist')
        tables = {row['name'] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn('scratchpad', tables)
        self.assertIn('scratchpad_entries', tables)

    def test_migrates_a_row_with_no_modified_onto_todays_date(self):
        self._stage_pre_migration_scratchpad('No timestamp on this one', '')
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        tasks_db.migrate(self.conn)

        self.assertEqual(tasks_db.load_scratchpad(self.conn, today), 'No timestamp on this one')

    def test_migrates_an_empty_singleton_row_without_copying_anything(self):
        self._stage_pre_migration_scratchpad('', '')
        tasks_db.migrate(self.conn)

        self.assertEqual(tasks_db.most_recent_scratchpad_date(self.conn), '')
        count = self.conn.execute('SELECT COUNT(*) AS n FROM scratchpad_entries').fetchone()['n']
        self.assertEqual(count, 0)

    def test_is_idempotent(self):
        self._stage_pre_migration_scratchpad('Buy milk', '2026-09-05T14:30:00Z')
        tasks_db.migrate(self.conn)
        tasks_db.migrate(self.conn)

        self.assertEqual(tasks_db.load_scratchpad(self.conn, '2026-09-05'), 'Buy milk')
        count = self.conn.execute('SELECT COUNT(*) AS n FROM scratchpad_entries').fetchone()['n']
        self.assertEqual(count, 1)


class TestMigrateFromJson(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'tasks.db')
        self.paths = {}

        for name, rows in (
            ('sections', [
                {'id': 's1', 'label': 'One', 'slug': 'one', 'note': 'A note'},
                {'id': 's2', 'label': 'Two', 'slug': 'two', 'note': ''},
            ]),
            ('tasks', [
                a_task('t1', section_id='s1', position=0, status='done', done=True),
                a_task('t2', section_id='s2', position=0),
            ]),
            ('tags', [
                {'id': 'g1', 'task_id': 't1', 'position': 1, 'text': 'second', 'flag': False},
                {'id': 'g2', 'task_id': 't1', 'position': 0, 'text': 'first', 'flag': True},
            ]),
        ):
            path = os.path.join(self.tmp_dir.name, '%s.json' % name)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(rows, f)
            self.paths[name] = path

    def tearDown(self):
        self.tmp_dir.cleanup()

    def migrate(self):
        return tasks_db.migrate_from_json(
            db_path=self.db_path,
            sections_file=self.paths['sections'],
            tasks_file=self.paths['tasks'],
            tags_file=self.paths['tags'],
        )

    def test_imports_every_row_and_reports_counts(self):
        self.assertEqual(self.migrate(), {'sections': 2, 'tasks': 2, 'tags': 2})

        conn = tasks_db.connect(self.db_path)

        try:
            self.assertEqual(len(tasks_db.load_sections(conn)), 2)
            self.assertEqual(len(tasks_db.load_tasks(conn)), 2)
            self.assertEqual(len(tasks_db.load_tags(conn)), 2)
        finally:
            conn.close()

    def test_preserves_section_order_from_the_file(self):
        self.migrate()
        conn = tasks_db.connect(self.db_path)

        try:
            self.assertEqual([s['id'] for s in tasks_db.load_sections(conn)], ['s1', 's2'])
        finally:
            conn.close()

    def test_preserves_tag_order_within_a_task(self):
        self.migrate()
        conn = tasks_db.connect(self.db_path)

        try:
            self.assertEqual([t['text'] for t in tasks_db.tags_for_task(conn, 't1')], ['first', 'second'])
        finally:
            conn.close()

    def test_refuses_to_import_twice(self):
        self.migrate()

        with self.assertRaises(RuntimeError):
            self.migrate()

    def test_migrated_tasks_match_the_json_they_came_from(self):
        self.migrate()
        conn = tasks_db.connect(self.db_path)

        try:
            with open(self.paths['tasks'], 'r', encoding='utf-8') as f:
                expected = json.load(f)
            self.assertEqual(tasks_db.load_tasks(conn), expected)
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
