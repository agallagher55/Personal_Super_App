import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tasks_db  # noqa: E402
import tasks_export  # noqa: E402

from test_tasks_db import a_task  # noqa: E402


class ExportTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp_dir.name
        self.db_path = os.path.join(self.data_dir, 'tasks.db')
        conn = tasks_db.connect(self.db_path)

        try:
            tasks_db.init_schema(conn)
            # Two sections deliberately out of alphabetical order, so a
            # section_id sort and a position sort disagree.
            tasks_db.insert_section(conn, {'id': 'zeta', 'position': 0, 'label': 'Zeta', 'slug': 'zeta', 'note': 'n'})
            tasks_db.insert_section(conn, {'id': 'alpha', 'position': 1, 'label': 'Alpha', 'slug': 'alpha', 'note': ''})
            tasks_db.insert_task(conn, a_task('z1', section_id='zeta', position=1))
            tasks_db.insert_task(conn, a_task('z0', section_id='zeta', position=0))
            tasks_db.insert_task(conn, a_task('a0', section_id='alpha', position=0))
            tasks_db.replace_task_tags(conn, 'z0', [
                {'id': 'g1', 'text': 'first', 'flag': True},
                {'id': 'g2', 'text': 'second', 'flag': False},
            ])
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def export(self, check_only=False):
        return tasks_export.export(db_path=self.db_path, data_dir=self.data_dir, check_only=check_only)

    def read(self, name):
        with open(os.path.join(self.data_dir, '%s.json' % name), 'r', encoding='utf-8') as f:
            return json.load(f)

    def raw(self, name):
        with open(os.path.join(self.data_dir, '%s.json' % name), 'r', encoding='utf-8') as f:
            return f.read()


class TestExport(ExportTestCase):

    def test_writes_all_three_files(self):
        results = self.export()
        self.assertEqual({n: c for n, (c, _) in results.items()}, {'sections': 2, 'tasks': 3, 'tags': 2})

        for name in ('sections', 'tasks', 'tags'):
            self.assertTrue(os.path.exists(os.path.join(self.data_dir, '%s.json' % name)), name)

    def test_matches_the_old_json_formatting(self):
        """indent=2 and a trailing newline, the way save_json() wrote these
        before the migration - otherwise the first export is a whole-file
        diff for no reason."""
        self.export()
        raw = self.raw('sections')
        self.assertTrue(raw.endswith(']\n'))
        self.assertIn('\n  {\n    "id": "zeta"', raw)

    def test_sections_come_out_in_position_order(self):
        self.export()
        self.assertEqual([s['id'] for s in self.read('sections')], ['zeta', 'alpha'])

    def test_sections_do_not_leak_the_position_column(self):
        """position is implied by array order in the file, the way it was
        before the migration, so migrate re-derives it and the committed
        shape doesn't change."""
        self.export()
        self.assertEqual(set(self.read('sections')[0]), {'id', 'label', 'slug', 'note'})

    def test_tasks_are_ordered_by_section_then_position(self):
        """Not by section_id: 'zeta' sorts after 'alpha' alphabetically but
        comes first on the page."""
        self.export()
        self.assertEqual([t['id'] for t in self.read('tasks')], ['z0', 'z1', 'a0'])

    def test_tags_follow_their_task_and_keep_their_order(self):
        self.export()
        self.assertEqual([g['text'] for g in self.read('tags')], ['first', 'second'])

    def test_tasks_keep_json_booleans(self):
        self.export()
        task = self.read('tasks')[0]

        for field in ('done', 'env_dev', 'env_qa', 'env_prod', 'cmdb_updated'):
            self.assertIsInstance(task[field], bool, field)

    def test_export_is_idempotent(self):
        self.export()
        results = self.export()
        self.assertEqual({n: changed for n, (_, changed) in results.items()},
                         {'sections': False, 'tasks': False, 'tags': False})

    def test_reports_the_change_after_an_edit(self):
        self.export()
        conn = tasks_db.connect(self.db_path)

        try:
            task = tasks_db.find_task(conn, 'a0')
            task['desc'] = 'Edited.'
            tasks_db.update_task(conn, task)
            conn.commit()
        finally:
            conn.close()

        self.assertTrue(self.export(check_only=True)['tasks'][1])


class TestCheckMode(ExportTestCase):

    def test_check_reports_missing_files_as_changed(self):
        results = self.export(check_only=True)
        self.assertTrue(all(changed for _, changed in results.values()))

    def test_check_writes_nothing(self):
        self.export(check_only=True)
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, 'tasks.json')))

    def test_check_is_clean_right_after_an_export(self):
        self.export()
        results = self.export(check_only=True)
        self.assertFalse(any(changed for _, changed in results.values()))


class TestRoundTrip(ExportTestCase):

    def test_export_then_migrate_then_export_is_byte_identical(self):
        """The export is the exact inverse of tasks_db.py migrate."""
        self.export()
        originals = {name: self.raw(name) for name in ('sections', 'tasks', 'tags')}

        second_db = os.path.join(self.data_dir, 'roundtrip.db')
        tasks_db.migrate_from_json(
            db_path=second_db,
            sections_file=os.path.join(self.data_dir, 'sections.json'),
            tasks_file=os.path.join(self.data_dir, 'tasks.json'),
            tags_file=os.path.join(self.data_dir, 'tags.json'),
        )
        tasks_export.export(db_path=second_db, data_dir=self.data_dir)

        for name in ('sections', 'tasks', 'tags'):
            self.assertEqual(self.raw(name), originals[name], name)

    def test_round_tripped_rows_match_the_source_database(self):
        self.export()
        second_db = os.path.join(self.data_dir, 'roundtrip.db')
        tasks_db.migrate_from_json(
            db_path=second_db,
            sections_file=os.path.join(self.data_dir, 'sections.json'),
            tasks_file=os.path.join(self.data_dir, 'tasks.json'),
            tags_file=os.path.join(self.data_dir, 'tags.json'),
        )

        source = tasks_db.connect(self.db_path)
        copy = tasks_db.connect(second_db)

        try:
            self.assertEqual(tasks_db.load_sections(source), tasks_db.load_sections(copy))
            self.assertEqual(tasks_db.load_tasks(source), tasks_db.load_tasks(copy))
            self.assertEqual(tasks_db.load_tags(source), tasks_db.load_tags(copy))
        finally:
            source.close()
            copy.close()


class TestMissingDatabase(unittest.TestCase):

    def test_export_without_a_database_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError) as caught:
                tasks_export.export(db_path=os.path.join(tmp, 'nope.db'), data_dir=tmp)
            self.assertIn('migrate', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
