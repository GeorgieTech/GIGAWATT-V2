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
        conf = airplay.CONF_TEMPLATE % ("Gigawatt 39DB", "/tmp/gigawatt-airplay.meta")
        self.assertIn('interpolation = "basic"', conf)
        self.assertNotIn('interpolation = "auto"', conf)
        self.assertIn("resync_threshold_in_seconds = 0.0", conf)
        self.assertIn("audio_backend_buffer_desired_length_in_seconds", conf)
        self.assertIn("audio_backend_latency_offset_in_seconds", conf)
        self.assertIn('ignore_volume_control = "no"', conf)
        self.assertNotIn("wait_for_completion", conf)
        self.assertNotIn("run_this_before_play_begins", conf)
        self.assertNotIn("44100", conf)

    def test_never_targets_silent_44k1(self):
        self.assertEqual(airplay.AIRPLAY_RATE, 48000)
        self.assertNotEqual(airplay.AIRPLAY_RATE, 44100)


class MetaParseTests(unittest.TestCase):
    def test_compact_and_pretty_items(self):
        compact = (
            b"<item><type>73736e63</type><code>636c6970</code><length>4</length>"
            b"<data encoding=\"base64\">MS4xMQ==</data></item>"
        )
        pretty = b"""<item>
  <type>636f7265</type>
  <code>6d696e6d</code>
  <length>5</length>
  <data encoding="base64">
  R2xvdw==
  </data>
</item>"""
        self.assertTrue(airplay.ITEM_RE.search(compact))
        self.assertTrue(airplay.ITEM_RE.search(pretty))
        ap = airplay.AirPlay("/tmp/no-such-airplay")
        ap._apply("dmap.minm", "Havana")
        ap._apply("dmap.asar", "Camila Cabello")
        self.assertEqual(ap.title, "Havana")
        self.assertEqual(ap.artist, "Camila Cabello")


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
