#!/usr/bin/env python3
"""Savant telnet token mapping. No live RacePoint, no live host."""
import os
import unittest
import xml.etree.ElementTree as ET

import savant

PROFILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "docs",
    "savant",
    "georgietech_gigawatt.xml",
)


class FakePlayer(object):
    def __init__(self):
        self.playing = False
        self.paused = False
        self.name = "glow.flac"
        self.origin = "local"
        self.title = "Glow"
        self.artist = "CRYPT Test"
        self.album = "Lab"
        self.position = 12.0
        self._vol = 80
        self.error = ""

    def snapshot(self):
        return {
            "playing": self.playing,
            "paused": self.paused,
            "name": self.name,
            "origin": self.origin,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "position": self.position,
        }

    def set_volume(self, n):
        self._vol = max(0, min(100, int(n)))
        return True

    def volume(self):
        return self._vol


class FakeApp(object):
    def __init__(self):
        self.player = FakePlayer()
        self.tracks = [{"name": "glow.flac", "title": "Glow"}]
        self.started = []
        self.seeked = []

    def catalog_snapshot(self):
        return list(self.tracks)

    def play_name(self, name, origin="local", start=0.0, order=None):
        self.started.append(name)
        self.player.name = name
        self.player.origin = origin
        self.player.playing = True
        self.player.paused = False
        return True

    def pause(self, follow=False):
        self.player.playing = False
        self.player.paused = True
        return True

    def resume(self, follow=False):
        self.player.playing = True
        self.player.paused = False
        return True

    def stop(self, follow=False):
        self.player.playing = False
        self.player.paused = False
        self.player.name = ""
        return True

    def next_track(self):
        self.started.append("next")
        self.player.playing = True
        return True

    def prev_track(self):
        self.started.append("prev")
        self.player.playing = True
        return True

    def seek(self, seconds, follow=False):
        self.seeked.append(float(seconds))
        self.player.position = float(seconds)
        return True


class VolumeMapTests(unittest.TestCase):
    def test_round_trip_50(self):
        self.assertEqual(savant.savant_to_host_vol(50), 100)
        self.assertEqual(savant.savant_to_host_vol(0), 0)
        self.assertEqual(savant.savant_to_host_vol(25), 50)
        self.assertEqual(savant.host_to_savant_vol(100), 50)
        self.assertEqual(savant.host_to_savant_vol(80), 40)

    def test_rejects_junk(self):
        self.assertIsNone(savant.savant_to_host_vol("x"))


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.bridge = savant.HostBridge(self.app)

    def test_play_starts_named_track(self):
        ok, lines = savant.handle_line("Play", self.bridge)
        self.assertTrue(ok)
        self.assertIn("glow.flac", self.app.started)
        self.assertTrue(any(row.startswith("Play=Play") for row in lines))
        self.assertTrue(any(row.startswith("Title=Glow") for row in lines))
        self.assertTrue(any(row == "CurrentSongName=Glow" for row in lines))
        self.assertTrue(any(row == "CurrentArtistName=CRYPT Test" for row in lines))
        self.assertTrue(any(row.startswith("CurrentCombinedPlayStatus=Play") for row in lines))

    def test_pause_and_resume(self):
        savant.handle_line("Play", self.bridge)
        ok, lines = savant.handle_line("Pause", self.bridge)
        self.assertTrue(ok)
        self.assertTrue(self.app.player.paused)
        self.assertTrue(any("Play=Pause" in row for row in lines))
        ok, lines = savant.handle_line("Play", self.bridge)
        self.assertTrue(self.app.player.playing)
        self.assertFalse(self.app.player.paused)

    def test_skip_and_stop(self):
        savant.handle_line("SkipNext", self.bridge)
        self.assertIn("next", self.app.started)
        savant.handle_line("SkipPrevious", self.bridge)
        self.assertIn("prev", self.app.started)
        savant.handle_line("Stop", self.bridge)
        self.assertFalse(self.app.player.playing)

    def test_setvolume_savant_scale(self):
        ok, lines = savant.handle_line("SetVolume 25", self.bridge)
        self.assertTrue(ok)
        self.assertEqual(self.app.player.volume(), 50)
        self.assertTrue(any(row == "Volume=25" for row in lines))

    def test_sendkeys_volume_and_standby(self):
        self.app.player._vol = 80
        savant.handle_line("SendKeys Volume-", self.bridge)
        self.assertEqual(self.app.player.volume(), 76)
        savant.handle_line("SendKeys Standby", self.bridge)
        self.assertFalse(self.app.player.playing)

    def test_getstatus_and_unknown(self):
        ok, lines = savant.handle_line("GetStatus", self.bridge)
        self.assertTrue(ok)
        self.assertEqual(lines[0], "OK")
        ok, lines = savant.handle_line("NoSuchCommand", self.bridge)
        self.assertFalse(ok)
        self.assertTrue(lines[0].startswith("ERR"))

    def test_mms_action_names(self):
        savant.handle_line("SkipUp", self.bridge)
        self.assertIn("next", self.app.started)
        savant.handle_line("SkipDown", self.bridge)
        self.assertIn("prev", self.app.started)

    def test_idle_play_uses_catalog(self):
        self.app.player.name = ""
        ok, _lines = savant.handle_line("Play", self.bridge)
        self.assertTrue(ok)
        self.assertEqual(self.app.started[-1], "glow.flac")


class ProfileTests(unittest.TestCase):
    def test_toslink_media_server_no_sms_coprocessor(self):
        tree = ET.parse(PROFILE)
        root = tree.getroot()
        self.assertEqual(root.get("manufacturer"), "GeorgieTech")
        self.assertEqual(root.get("model"), "Gigawatt")
        self.assertEqual(root.get("device_class"), "Media_server")
        self.assertIsNone(root.find("component_properties/obsolete"))
        self.assertIsNone(root.find("component_properties/coprocessor_required"))
        types = [n.get("type") for n in root.findall(".//audio_media")]
        self.assertEqual(types, ["optical_digital"])
        resources = [n.get("resource_type") for n in root.findall(".//resource")]
        self.assertIn("AV_EXTERNALMEDIASERVER_SOURCE", resources)
        self.assertIn("AV_LIVEMEDIAQUERY_SAVANTMEDIA_SOURCE", resources)
        self.assertNotIn("AV_LIVEMEDIAQUERY_SAVANTMEDIA_SOURCE_RADIO_SPOTIFY", resources)
        ip = root.find(".//control_interfaces/ip")
        self.assertEqual(ip.get("port"), "5004")


if __name__ == "__main__":
    unittest.main()
