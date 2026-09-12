#!/usr/bin/env python3
"""AirPlay name and playback settings tests. No live hosts."""
import json
import os
import shutil
import tempfile
import unittest

import airplay
import playback


class ConfTests(unittest.TestCase):
    def test_stuffing_matches_beta2(self):
        conf = airplay.CONF_TEMPLATE % ("Gigawatt 39DB", "/tmp/gigawatt-airplay.meta")
        self.assertIn('interpolation = "basic"', conf)
        self.assertNotIn('interpolation = "auto"', conf)
        self.assertNotIn("audio_backend_buffer_desired_length_in_seconds", conf)
        self.assertIn('ignore_volume_control = "no"', conf)


class NameTests(unittest.TestCase):
    def test_sanitize_accepts_host_stamp_names(self):
        self.assertEqual(airplay.sanitize_name("Gigawatt E409"), "Gigawatt E409")
        self.assertEqual(airplay.sanitize_name("Gigawatt 39DB"), "Gigawatt 39DB")
        self.assertEqual(airplay.sanitize_name("Living RM"), "Living RM")

    def test_sanitize_rejects_empty_and_junk(self):
        self.assertIsNone(airplay.sanitize_name(""))
        self.assertIsNone(airplay.sanitize_name("no/slash"))
        self.assertIsNone(airplay.sanitize_name("a" * 51))


class PlaybackFileTests(unittest.TestCase):
    def test_save_round_trip(self):
        folder = tempfile.mkdtemp(prefix="crypt-pb-")
        try:
            path = os.path.join(folder, "playback.json")
            data, err = playback.save_playback(
                output="browser",
                airplay=True,
                airplay_name="Gigawatt E409",
                path=path,
            )
            self.assertEqual(err, "")
            self.assertEqual(data["output"], "browser")
            self.assertTrue(data["airplay"])
            self.assertEqual(data["airplay_name"], "Gigawatt E409")
            again = playback.load_playback(path)
            self.assertEqual(again, data)
            with open(path) as fh:
                raw = json.load(fh)
            self.assertEqual(raw["output"], "browser")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_bad_output_stays_jack(self):
        folder = tempfile.mkdtemp(prefix="crypt-pb-")
        try:
            path = os.path.join(folder, "playback.json")
            with open(path, "w") as fh:
                json.dump({"output": "hdmi", "airplay_name": "bad/name"}, fh)
            data = playback.load_playback(path)
            self.assertEqual(data["output"], "jack")
            self.assertTrue(data["airplay_name"])
            self.assertNotIn("/", data["airplay_name"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_rejects_bad_rename(self):
        folder = tempfile.mkdtemp(prefix="crypt-pb-")
        try:
            path = os.path.join(folder, "playback.json")
            data, err = playback.save_playback(airplay_name="nope!", path=path)
            self.assertTrue(err)
            self.assertNotEqual(data.get("airplay_name"), "nope!")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
