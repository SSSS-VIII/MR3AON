from __future__ import annotations

import unittest

from custom.game_process_watch import GameProcessWatch


class GameProcessWatchTest(unittest.TestCase):
    def test_not_watching_never_triggers(self):
        watch = GameProcessWatch(miss_threshold=1)
        self.assertFalse(watch.note_missing())

    def test_missing_before_seen_alive_is_not_crash(self):
        watch = GameProcessWatch(miss_threshold=1)
        watch.arm()
        self.assertFalse(watch.note_missing())
        self.assertFalse(watch.note_missing())
        self.assertFalse(watch.peek_waydroid_restart_request())

    def test_crash_after_seen_alive(self):
        watch = GameProcessWatch(miss_threshold=2)
        watch.arm()
        watch.note_present()
        self.assertFalse(watch.note_missing())
        self.assertTrue(watch.note_missing())

    def test_present_resets_streak(self):
        watch = GameProcessWatch(miss_threshold=2)
        watch.arm()
        watch.note_present()
        self.assertFalse(watch.note_missing())
        watch.note_present()
        self.assertFalse(watch.note_missing())
        self.assertTrue(watch.note_missing())

    def test_disarm_clears_trigger(self):
        watch = GameProcessWatch(miss_threshold=1)
        watch.arm()
        watch.note_present()
        watch.disarm()
        self.assertFalse(watch.note_missing())

    def test_begin_recovery_requests_restart_once(self):
        watch = GameProcessWatch(miss_threshold=1)
        watch.arm()
        watch.note_present()
        self.assertTrue(watch.note_missing())
        self.assertTrue(watch.begin_recovery())
        self.assertFalse(watch.begin_recovery())
        self.assertTrue(watch.peek_waydroid_restart_request())
        self.assertFalse(watch.watching)
        self.assertTrue(watch.consume_waydroid_restart_request())
        self.assertFalse(watch.peek_waydroid_restart_request())


if __name__ == "__main__":
    unittest.main()
