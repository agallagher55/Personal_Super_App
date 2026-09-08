import json
import os
import sqlite3
import sys
import tempfile
import unittest
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
        'time_estimate': '',
        'related_files': '',
        'parent_id': '',
        'work_type': '',
        'env_dev': False,
        'env_qa': False,
        'env_prod': False,
        'cmdb_updated': False,
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
        self.assertTrue({'sections', 'tasks', 'tags'} <= names)

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
            time_estimate='2h',
            related_files='a.py, b.py',
            work_type='new-feature',
            env_dev=True,
            env_prod=True,
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

        for field in ('env_dev', 'env_qa', 'env_prod', 'cmdb_updated', 'done'):
            self.assertIsInstance(stored[field], bool, field)

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
        self.assertEqual(tasks_db.load_scratchpad(self.conn), '')

    def test_round_trips_saved_text(self):
        tasks_db.save_scratchpad(self.conn, 'Buy milk\nCall dentist', '2026-01-01T00:00:00Z')
        self.assertEqual(tasks_db.load_scratchpad(self.conn), 'Buy milk\nCall dentist')

    def test_saving_again_overwrites_rather_than_adding_a_row(self):
        tasks_db.save_scratchpad(self.conn, 'First draft', '2026-01-01T00:00:00Z')
        tasks_db.save_scratchpad(self.conn, 'Second draft', '2026-01-02T00:00:00Z')

        self.assertEqual(tasks_db.load_scratchpad(self.conn), 'Second draft')
        count = self.conn.execute('SELECT COUNT(*) AS n FROM scratchpad').fetchone()['n']
        self.assertEqual(count, 1)

    def test_saving_empty_text_clears_it(self):
        tasks_db.save_scratchpad(self.conn, 'Something', '2026-01-01T00:00:00Z')
        tasks_db.save_scratchpad(self.conn, '', '2026-01-02T00:00:00Z')
        self.assertEqual(tasks_db.load_scratchpad(self.conn), '')


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
