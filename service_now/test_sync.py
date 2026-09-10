import unittest

import sync


class TestStatusMapping(unittest.TestCase):

    def test_maps_actionable_states(self):
        self.assertEqual(sync.map_status('Open'), 'open')
        self.assertEqual(sync.map_status('Work in Progress'), 'in-progress')

    def test_maps_waiting_states_to_pending(self):
        for state in ('Pending', 'Awaiting User Info', 'Awaiting User Information', 'On Hold'):
            with self.subTest(state=state):
                self.assertEqual(sync.map_status(state), 'pending')

    def test_maps_resolved_states_to_done(self):
        self.assertEqual(sync.map_status('Resolved'), 'done')
        self.assertEqual(sync.map_status('Closed Complete'), 'done')


class TestSourceTimestamps(unittest.TestCase):

    def test_normalizes_instance_local_timestamp_to_utc(self):
        self.assertEqual(
            sync.normalize_servicenow_timestamp('2026-07-01 08:30:00'),
            '2026-07-01T11:30:00Z',
        )
        self.assertEqual(
            sync.normalize_servicenow_timestamp('2026-01-01 08:30:00'),
            '2026-01-01T12:30:00Z',
        )

    def test_map_record_uses_opened_at_then_created_fallback(self):
        record = {
            'opened_at': {'display_value': ''},
            'sys_created_on': {'display_value': '2026-01-01 08:30:00'},
            'sys_updated_on': {'display_value': '2026-01-02 08:30:00'},
        }
        mapped = sync.map_record(record)
        self.assertEqual(mapped['source_opened_at'], '2026-01-01T12:30:00Z')
        self.assertEqual(mapped['source_updated_at'], '2026-01-02T12:30:00Z')


class TestUpsertFreshness(unittest.TestCase):

    def setUp(self):
        self.mapped = {
            'servicenow_sys_id': 'source-1',
            'ticket_number': 'TASK001',
            'desc': 'Do the thing',
            'note': 'Source note',
            'assignment_group': 'GIS',
            'requested_by': 'Alex',
            'due_date': '',
            'status': 'open',
            'source_opened_at': '2026-01-01T12:30:00Z',
            'source_updated_at': '2026-09-10T12:30:00Z',
        }

    def test_unchanged_task_gets_last_seen_without_counting_as_updated(self):
        task = dict(self.mapped, id='task-1', section_id='own-tasks', position=0,
                    notes='Personal note', priority='medium', created='2026-01-01T00:00:00Z',
                    modified='2026-01-01T00:00:00Z', completed='', last_seen_at='')
        pending = {'created': [], 'updated': set(), 'refreshed': set()}

        outcome = sync.upsert([task], 'own-tasks', self.mapped, '2026-09-10T14:00:00Z', False, pending)

        self.assertEqual(outcome, 'unchanged')
        self.assertEqual(task['last_seen_at'], '2026-09-10T14:00:00Z')
        self.assertEqual(pending['updated'], set())
        self.assertEqual(pending['refreshed'], {'task-1'})

    def test_source_timestamp_only_change_does_not_inflate_updated_count(self):
        task = dict(self.mapped, id='task-1', section_id='own-tasks', position=0,
                    notes='', priority='medium', created='2026-01-01T00:00:00Z',
                    modified='2026-01-01T00:00:00Z', completed='', last_seen_at='',
                    source_updated_at='2026-09-09T12:30:00Z')
        pending = {'created': [], 'updated': set(), 'refreshed': set()}

        outcome = sync.upsert([task], 'own-tasks', self.mapped, '2026-09-10T14:00:00Z', False, pending)

        self.assertEqual(outcome, 'unchanged')
        self.assertEqual(pending['updated'], set())
        self.assertEqual(task['source_updated_at'], '2026-09-10T12:30:00Z')


if __name__ == '__main__':
    unittest.main()
