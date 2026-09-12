#!/usr/bin/env python3
"""Upload prep / ready flags. No live host."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lyrics
import wave as cryptwave


def _tone_wav(path, seconds=3.0):
    import math
    import struct
    rate = 44100
    n = int(rate * seconds)
    samples = [int(0.2 * 32767 * math.sin(2 * math.pi * 440 * (i / float(rate)))) for i in range(n)]
    data = struct.pack("<%dh" % len(samples), *samples)
    with open(path, "wb") as fh:
        fh.write(b"RIFF")
        fh.write(struct.pack("<I", 36 + len(data)))
        fh.write(b"WAVEfmt ")
        fh.write(struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
        fh.write(b"data")
        fh.write(struct.pack("<I", len(data)))
        fh.write(data)


class WaveReadyTests(unittest.TestCase):
    def test_ready_false_without_cache(self):
        music = tempfile.mkdtemp(prefix="crypt-music-")
        waves = tempfile.mkdtemp(prefix="crypt-waves-")
        old_m, old_w = cryptwave.MUSIC_DIR, cryptwave.WAVE_DIR
        cryptwave.MUSIC_DIR = music
        cryptwave.WAVE_DIR = waves
        try:
            path = os.path.join(music, "glow.wav")
            _tone_wav(path)
            idx = cryptwave.WaveIndex()
            self.assertFalse(idx.ready("glow.wav"))
            self.assertFalse(idx.analyzing("glow.wav"))
        finally:
            cryptwave.MUSIC_DIR = old_m
            cryptwave.WAVE_DIR = old_w
            shutil.rmtree(music, ignore_errors=True)
            shutil.rmtree(waves, ignore_errors=True)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_ready_true_after_analyze(self):
        music = tempfile.mkdtemp(prefix="crypt-music-")
        waves = tempfile.mkdtemp(prefix="crypt-waves-")
        old_m, old_w = cryptwave.MUSIC_DIR, cryptwave.WAVE_DIR
        cryptwave.MUSIC_DIR = music
        cryptwave.WAVE_DIR = waves
        try:
            path = os.path.join(music, "glow.wav")
            _tone_wav(path)
            idx = cryptwave.WaveIndex()
            idx._build("glow.wav")
            self.assertTrue(idx.ready("glow.wav"))
            self.assertFalse(idx.analyzing("glow.wav"))
        finally:
            cryptwave.MUSIC_DIR = old_m
            cryptwave.WAVE_DIR = old_w
            shutil.rmtree(music, ignore_errors=True)
            shutil.rmtree(waves, ignore_errors=True)

    def test_ensure_marks_analyzing(self):
        music = tempfile.mkdtemp(prefix="crypt-music-")
        waves = tempfile.mkdtemp(prefix="crypt-waves-")
        old_m, old_w = cryptwave.MUSIC_DIR, cryptwave.WAVE_DIR
        cryptwave.MUSIC_DIR = music
        cryptwave.WAVE_DIR = waves
        try:
            path = os.path.join(music, "glow.wav")
            _tone_wav(path)
            idx = cryptwave.WaveIndex()
            # Drain the worker queue so ensure is deterministic.
            with idx.lock:
                idx.queue[:] = []
                idx.busy.clear()
            idx.ensure("glow.wav")
            self.assertTrue(idx.analyzing("glow.wav"))
            with idx.lock:
                idx.queue[:] = []
                idx.busy.clear()
                idx.progress.clear()
        finally:
            cryptwave.MUSIC_DIR = old_m
            cryptwave.WAVE_DIR = old_w
            shutil.rmtree(music, ignore_errors=True)
            shutil.rmtree(waves, ignore_errors=True)


class LyricsReadyTests(unittest.TestCase):
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

    def test_ready_from_sidecar(self):
        audio = os.path.join(self.music, "glow.wav")
        _tone_wav(audio)
        with open(os.path.join(self.music, "glow.lrc"), "w") as fh:
            fh.write("[00:01.00]Hello\n")
        idx = lyrics.LyricsIndex()
        self.assertTrue(idx.ready("glow.wav"))

    def test_ready_from_cache_json(self):
        audio = os.path.join(self.music, "glow.wav")
        _tone_wav(audio)
        key = __import__("hashlib").sha1(b"glow.wav").hexdigest()[:24]
        os.makedirs(self.cache, exist_ok=True)
        with open(os.path.join(self.cache, key + ".json"), "w") as fh:
            json.dump({"ok": True, "lines": [{"t": 1, "text": "Hi"}], "name": "glow.wav"}, fh)
        idx = lyrics.LyricsIndex()
        self.assertTrue(idx.ready("glow.wav"))

    def test_ready_false_without_lyrics(self):
        audio = os.path.join(self.music, "glow.wav")
        _tone_wav(audio)
        idx = lyrics.LyricsIndex()
        self.assertFalse(idx.ready("glow.wav"))


class DecorateReadyTests(unittest.TestCase):
    def test_decorate_flags(self):
        try:
            import server
        except OSError:
            self.skipTest("server import needs writable MUSIC_DIR")

        music = tempfile.mkdtemp(prefix="crypt-music-")
        waves = tempfile.mkdtemp(prefix="crypt-waves-")
        lyrics_dir = tempfile.mkdtemp(prefix="crypt-lyrics-")
        old = (cryptwave.MUSIC_DIR, cryptwave.WAVE_DIR, lyrics.MUSIC_DIR, lyrics.LYRICS_DIR)
        cryptwave.MUSIC_DIR = music
        cryptwave.WAVE_DIR = waves
        lyrics.MUSIC_DIR = music
        lyrics.LYRICS_DIR = lyrics_dir
        try:
            path = os.path.join(music, "glow.wav")
            _tone_wav(path)
            with open(os.path.join(music, "glow.lrc"), "w") as fh:
                fh.write("[00:01.00]Hello\n")
            # Seed wave cache as ready.
            size = os.path.getsize(path)
            mtime = int(os.path.getmtime(path))
            cache = cryptwave._cache_path("glow.wav", size, mtime)
            os.makedirs(waves, exist_ok=True)
            with open(cache, "w") as fh:
                json.dump({"v": cryptwave.WAVE_VER, "l": [1], "m": [1], "h": [1], "n": 1, "name": "glow.wav"}, fh)
            rows = server._decorate_ready([{"name": "glow.wav", "title": "Glow"}])
            self.assertTrue(rows[0]["ready"])
            self.assertTrue(rows[0]["analyzed"])
            self.assertTrue(rows[0]["lyrics"])
            self.assertFalse(rows[0]["analyzing"])
        finally:
            cryptwave.MUSIC_DIR, cryptwave.WAVE_DIR, lyrics.MUSIC_DIR, lyrics.LYRICS_DIR = old
            shutil.rmtree(music, ignore_errors=True)
            shutil.rmtree(waves, ignore_errors=True)
            shutil.rmtree(lyrics_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
