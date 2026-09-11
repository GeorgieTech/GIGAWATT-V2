#!/usr/bin/env python3
"""LRC / karaoke parser and delete-with-track tests. Original fixture text only."""
import json
import os
import shutil
import tempfile
import unittest

import lyrics


class ParseLrcTests(unittest.TestCase):
    def test_plain_timed_lines(self):
        text = "\n".join([
            "[ti:Fixture Glow]",
            "[ar:CRYPT Test]",
            "[00:01.00]First glow",
            "[00:04.50]Second glow",
            "[00:08.00]Third glow",
        ])
        parsed = lyrics.parse_lrc(text)
        self.assertEqual(parsed["meta"]["title"], "Fixture Glow")
        self.assertEqual(len(parsed["lines"]), 3)
        self.assertEqual(parsed["lines"][0]["t"], 1.0)
        self.assertEqual(parsed["lines"][1]["text"], "Second glow")
        self.assertAlmostEqual(parsed["lines"][1]["t"], 4.5)

    def test_enhanced_words(self):
        text = "[00:02.00]Hold [00:02.40]the [00:02.80]line"
        parsed = lyrics.parse_lrc(text)
        words = parsed["lines"][0]["words"]
        self.assertEqual(len(words), 3)
        self.assertEqual(words[0]["text"].strip(), "Hold")
        self.assertAlmostEqual(words[1]["t"], 2.4)
        self.assertEqual(parsed["lines"][0]["text"].replace(" ", ""), "Holdtheline")

    def test_offset_tag(self):
        text = "[offset:500]\n[00:01.00]Shifted"
        parsed = lyrics.parse_lrc(text)
        self.assertAlmostEqual(parsed["lines"][0]["t"], 1.5)

    def test_plain_text(self):
        parsed = lyrics.parse_plain("One\n\nTwo")
        self.assertEqual([row["text"] for row in parsed["lines"]], ["One", "Two"])


class SidecarAndDropTests(unittest.TestCase):
    def setUp(self):
        self.music = tempfile.mkdtemp(prefix="crypt-music-")
        self.cache = tempfile.mkdtemp(prefix="crypt-lyrics-")
        self.old_music = lyrics.MUSIC_DIR
        self.old_cache = lyrics.LYRICS_DIR
        lyrics.MUSIC_DIR = self.music
        lyrics.LYRICS_DIR = self.cache

    def tearDown(self):
        lyrics.MUSIC_DIR = self.old_music
        lyrics.LYRICS_DIR = self.old_cache
        shutil.rmtree(self.music, ignore_errors=True)
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_sidecar_lookup(self):
        path = os.path.join(self.music, "glow.wav")
        lrc = os.path.join(self.music, "glow.lrc")
        with open(path, "wb") as fh:
            fh.write(b"RIFF")
        with open(lrc, "w") as fh:
            fh.write("[00:00.50]Sidecar glow\n[00:03.00]Keep time\n")
        data = lyrics.LyricsIndex().lookup("glow.wav")
        self.assertTrue(data["ok"])
        self.assertEqual(data["source"], "sidecar")
        self.assertEqual(data["name"], "glow.wav")
        self.assertEqual(data["lines"][0]["text"], "Sidecar glow")
        self.assertTrue(any(p.endswith(".lrc") for p in lyrics.sidecar_paths(path)))

    def test_drop_removes_sidecar_and_named_cache(self):
        wav = os.path.join(self.music, "gone.wav")
        keep_wav = os.path.join(self.music, "keep.wav")
        lrc = os.path.join(self.music, "gone.lrc")
        keep_lrc = os.path.join(self.music, "keep.lrc")
        for path in (wav, keep_wav):
            with open(path, "wb") as fh:
                fh.write(b"RIFF")
        with open(lrc, "w") as fh:
            fh.write("[00:00.10]Gone\n")
        with open(keep_lrc, "w") as fh:
            fh.write("[00:00.10]Keep\n")
        gone_json = os.path.join(self.cache, "gone.json")
        keep_json = os.path.join(self.cache, "keep.json")
        with open(gone_json, "w") as fh:
            json.dump({"ok": True, "name": "gone.wav", "lines": [1]}, fh)
        with open(keep_json, "w") as fh:
            json.dump({"ok": True, "name": "keep.wav", "lines": [1]}, fh)
        idx = lyrics.LyricsIndex()
        n = idx.drop_name("gone.wav")
        self.assertGreaterEqual(n, 2)
        self.assertFalse(os.path.isfile(lrc))
        self.assertFalse(os.path.isfile(gone_json))
        self.assertTrue(os.path.isfile(keep_lrc))
        self.assertTrue(os.path.isfile(keep_json))
        self.assertTrue(os.path.isfile(wav))


if __name__ == "__main__":
    unittest.main()
