#!/usr/bin/env python3
"""AirPlay name and playback settings tests. No live hosts."""
import json
import os
import shutil
import tempfile
import unittest

import airplay
import playback


class RateParseTests(unittest.TestCase):
    def test_reads_96k_and_44k(self):
        self.assertEqual(airplay.parse_sink_rate(
            "Sample Specification: s24-32le 2ch 96000Hz\n"
        ), 96000)
        self.assertEqual(airplay.parse_sink_rate(
            "Sample Specification: s16le 2ch 44100Hz\n"
        ), 44100)
        self.assertEqual(airplay.parse_sink_rate(""), 0)


class ConfTests(unittest.TestCase):
    def test_stuffing_matches_beta2(self):
        conf = airplay.CONF_TEMPLATE % {
            "name": "Gigawatt 39DB",
            "begin": "/data/opt/airplay/toslink-airplay-begin.sh",
            "end": "/data/opt/airplay/toslink-airplay-end.sh",
            "pipe": "/tmp/gigawatt-airplay.meta",
        }
        self.assertIn('interpolation = "basic"', conf)
        self.assertNotIn('interpolation = "auto"', conf)
        self.assertNotIn("audio_backend_buffer_desired_length_in_seconds", conf)
        self.assertIn('ignore_volume_control = "no"', conf)
        self.assertIn('wait_for_completion = "yes"', conf)
        self.assertIn("toslink-airplay-begin.sh", conf)
        self.assertIn("toslink-airplay-end.sh", conf)

    def test_rate_hooks_live_next_to_binary(self):
        folder = os.path.join(os.path.dirname(airplay.__file__), "airplay")
        begin = os.path.join(folder, "toslink-airplay-begin.sh")
        end = os.path.join(folder, "toslink-airplay-end.sh")
        self.assertTrue(os.path.isfile(begin), begin)
        self.assertTrue(os.path.isfile(end), end)
        with open(begin) as fh:
            body = fh.read()
        self.assertIn("44100", body)
        with open(os.path.join(folder, "shairport-sync.conf")) as fh:
            self.assertIn("wait_for_completion", fh.read())


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
