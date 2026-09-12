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
    def test_stuffing_is_auto_not_basic(self):
        conf = airplay.CONF_TEMPLATE % ("Gigawatt E409", "/tmp/gigawatt-airplay.meta")
        self.assertIn('interpolation = "auto"', conf)
        self.assertNotIn('interpolation = "basic"', conf)
        self.assertIn("audio_backend_buffer_desired_length_in_seconds = 0.50", conf)
        self.assertIn("resync_threshold_in_seconds = 0.150", conf)
        self.assertIn('ignore_volume_control = "yes"', conf)

    def test_pulse_daemon_snip_keeps_96k_word_clock(self):
        snip = airplay.PULSE_DAEMON_SNIPPET
        self.assertIn("default-sample-rate = 96000", snip)
        self.assertIn("alternate-sample-rate = 48000", snip)
        self.assertIn("speex-float-1", snip)

    def test_ensure_pulse_daemon_conf_rewrites_old_block(self):
        folder = tempfile.mkdtemp(prefix="crypt-pa-")
        try:
            path = os.path.join(folder, "daemon.conf")
            with open(path, "w") as fh:
                fh.write("# pulse\n\n# GIGAWATT-AUDIO\nresample-method = speex-float-1\n")
            self.assertTrue(airplay.ensure_pulse_daemon_conf(path))
            with open(path) as fh:
                text = fh.read()
            self.assertIn("GIGAWATT-AUDIO-BEGIN", text)
            self.assertIn("default-sample-rate = 96000", text)
            self.assertEqual(text.count("GIGAWATT-AUDIO-BEGIN"), 1)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


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
