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


if __name__ == '__main__':
    unittest.main()
