"""Tests for backend/server.py's shared task-creation logic.

create_task() is the one place both /tasks/new (the full form) and
/tasks/quick-task (the scratchpad's convert-line-to-task action, issue
#165) build a task row - see the "Tests" section of #165, which asks for
server-side coverage of whatever the new endpoint uses if it doesn't reuse
POST /tasks/new unchanged.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tasks_db  # noqa: E402
import server  # noqa: E402


class CreateTaskTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, 'tasks.db')
        self.conn = tasks_db.connect(self.db_path)
        tasks_db.init_schema(self.conn)
        tasks_db.insert_section(self.conn, {
            'id': 's1', 'position': 0, 'label': 'Section', 'slug': 's1', 'note': '',
        })
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp_dir.cleanup()

    def test_creates_a_task_with_just_a_section_and_description(self):
        task_id = server.create_task(self.conn, 's1', 'A quick task')
        task = tasks_db.find_task(self.conn, task_id)
        self.assertEqual(task['desc'], 'A quick task')
        self.assertEqual(task['section_id'], 's1')

    def test_defaults_match_the_full_new_task_form(self):
        task_id = server.create_task(self.conn, 's1', 'A quick task')
        task = tasks_db.find_task(self.conn, task_id)
        self.assertEqual(task['status'], 'open')
        self.assertEqual(task['priority'], 'medium')
        self.assertEqual(task['notes'], '')
        self.assertEqual(task['parent_id'], '')
        self.assertEqual(task['work_type'], '')
        self.assertFalse(task['focus_today'])

    def test_appends_at_the_end_of_the_section(self):
        server.create_task(self.conn, 's1', 'First')
        second_id = server.create_task(self.conn, 's1', 'Second')

        task = tasks_db.find_task(self.conn, second_id)
        self.assertEqual(task['position'], 1)

    def test_falls_back_to_medium_for_an_invalid_priority(self):
        task_id = server.create_task(self.conn, 's1', 'A quick task', priority='urgent')
        task = tasks_db.find_task(self.conn, task_id)
        self.assertEqual(task['priority'], 'medium')

    def test_work_type_only_applies_to_the_work_section(self):
        task_id = server.create_task(self.conn, 's1', 'A quick task', work_type='new-feature')
        task = tasks_db.find_task(self.conn, task_id)
        self.assertEqual(task['work_type'], '')

    def test_no_tags_by_default(self):
        task_id = server.create_task(self.conn, 's1', 'A quick task')
        self.assertEqual(tasks_db.tags_for_task(self.conn, task_id), [])

    def test_each_call_gets_a_unique_id(self):
        first_id = server.create_task(self.conn, 's1', 'First')
        second_id = server.create_task(self.conn, 's1', 'Second')

        self.assertNotEqual(first_id, second_id)

    def test_an_unknown_parent_id_is_dropped_rather_than_stored(self):
        task_id = server.create_task(self.conn, 's1', 'A quick task', parent_id='no-such-task')
        task = tasks_db.find_task(self.conn, task_id)
        self.assertEqual(task['parent_id'], '')


if __name__ == '__main__':
    unittest.main()
