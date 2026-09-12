#!/usr/bin/env python3
"""Play-next queue + requester name. Stdlib only."""
import unittest

import queueing


class RequesterTests(unittest.TestCase):
    def test_strips_and_caps(self):
        self.assertEqual(queueing.sanitize_requester("  George  "), "George")
        self.assertEqual(queueing.sanitize_requester("A" * 40), "A" * 32)
        self.assertEqual(queueing.sanitize_requester(""), "")

    def test_drops_junk(self):
        self.assertEqual(queueing.sanitize_requester("Ann<script>"), "Annscript")
        self.assertEqual(queueing.sanitize_requester("Jo-Jo O'Neil"), "Jo-Jo O'Neil")


class InsertPlayNextTests(unittest.TestCase):
    def test_inserts_after_current(self):
        order, idx = queueing.insert_play_next(["a.mp3", "b.mp3", "c.mp3"], 0, "c.mp3")
        self.assertEqual(order, ["a.mp3", "c.mp3", "b.mp3"])
        self.assertEqual(idx, 0)

    def test_moves_later_track_up(self):
        order, idx = queueing.insert_play_next(["a.mp3", "b.mp3", "c.mp3"], 0, "b.mp3")
        self.assertEqual(order, ["a.mp3", "b.mp3", "c.mp3"])
        self.assertEqual(idx, 0)

    def test_current_song_stays_put(self):
        order, idx = queueing.insert_play_next(["a.mp3", "b.mp3"], 0, "a.mp3")
        self.assertEqual(order, ["a.mp3", "b.mp3"])
        self.assertEqual(idx, 0)

    def test_idle_inserts_front(self):
        order, idx = queueing.insert_play_next(["a.mp3", "b.mp3"], -1, "c.mp3")
        self.assertEqual(order[0], "c.mp3")
        self.assertEqual(idx, -1)

    def test_empty_name_noop(self):
        order, idx = queueing.insert_play_next(["a.mp3"], 0, "")
        self.assertEqual(order, ["a.mp3"])
        self.assertEqual(idx, 0)


if __name__ == "__main__":
    unittest.main()
