#!/usr/bin/env python3
"""Delete-with-track, orphan prune, and media path routing. No live host."""
import json
import os
import shutil
import tempfile
import unittest

import cover
import library
import lyrics
import player
import report
import savant
import wave as cryptwave


JPEG = b"\xff\xd8\xff" + b"\x00" * 24


class CoverDropTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="crypt-cover-")
        self.idx = cover.CoverIndex(
            folder=self.folder,
            http_json=lambda url: None,
            http_bytes=lambda url: (b"", ""),
            pause=0,
        )
        self.idx._alive = False

    def tearDown(self):
        self.idx._alive = False
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_drop_last_track_removes_album_and_extract(self):
        rel = "Artist/Album/gone.flac"
        key = cover.album_key("Artist", "Album", rel)
        path = self.idx._path(key)
        extract = os.path.join(self.folder, cover.extract_filename(rel))
        with open(path, "wb") as fh:
            fh.write(JPEG)
        with open(extract, "wb") as fh:
            fh.write(JPEG)
        self.idx.index[key] = {"found": True, "missing": False}
        n = self.idx.drop_name(rel, remaining=[], key=key)
        self.assertGreaterEqual(n, 2)
        self.assertFalse(os.path.isfile(path))
        self.assertFalse(os.path.isfile(extract))
        self.assertNotIn(key, self.idx.index)

    def test_drop_keeps_album_when_sibling_remains(self):
        gone = "Artist/Album/gone.flac"
        keep = "Artist/Album/keep.flac"
        key = cover.album_key("Artist", "Album")
        path = self.idx._path(key)
        with open(path, "wb") as fh:
            fh.write(JPEG)
        self.idx.index[key] = {"found": True, "missing": False}
        remaining = [{"name": keep, "artist": "Artist", "album": "Album"}]
        self.idx.drop_name(gone, remaining=remaining, key=key)
        self.assertTrue(os.path.isfile(path))
        self.assertIn(key, self.idx.index)

    def test_prune_drops_extract_and_orphan_img(self):
        live = "keep.flac"
        live_key = cover.album_key("Keep", "LP", live)
        dead_key = cover.album_key("Gone", "LP", "gone.flac")
        live_path = self.idx._path(live_key)
        dead_path = self.idx._path(dead_key)
        extract = os.path.join(self.folder, "extract-deadbeefdeadbeefde.img")
        with open(live_path, "wb") as fh:
            fh.write(JPEG)
        with open(dead_path, "wb") as fh:
            fh.write(JPEG)
        with open(extract, "wb") as fh:
            fh.write(JPEG)
        self.idx.index[live_key] = {"found": True}
        self.idx.index[dead_key] = {"found": True}
        n = self.idx.prune([{"name": live, "artist": "Keep", "album": "LP"}])
        self.assertGreaterEqual(n, 2)
        self.assertTrue(os.path.isfile(live_path))
        self.assertFalse(os.path.isfile(dead_path))
        self.assertFalse(os.path.isfile(extract))
        self.assertIn(live_key, self.idx.index)
        self.assertNotIn(dead_key, self.idx.index)

    def test_file_for_rejects_path_escape(self):
        path, ctype = self.idx.file_for("../covers/secret")
        self.assertEqual(path, "")
        self.assertEqual(ctype, "")
        path, ctype = self.idx.file_for("")
        self.assertEqual(path, "")


class MusicSweepTests(unittest.TestCase):
    def setUp(self):
        self.music = tempfile.mkdtemp(prefix="crypt-music-")
        self.state = tempfile.mkdtemp(prefix="crypt-state-")
        self.old = library.MUSIC_DIR, library.STATE_DIR, library.META_FILE, library.PLAYLIST_FILE
        library.MUSIC_DIR = self.music
        library.STATE_DIR = self.state
        library.META_FILE = os.path.join(self.state, "library-meta.json")
        library.PLAYLIST_FILE = os.path.join(self.state, "playlists.json")

    def tearDown(self):
        library.MUSIC_DIR, library.STATE_DIR, library.META_FILE, library.PLAYLIST_FILE = self.old
        shutil.rmtree(self.music, ignore_errors=True)
        shutil.rmtree(self.state, ignore_errors=True)

    def test_sweep_removes_art_lyrics_and_empty_album_dir(self):
        album = os.path.join(self.music, "Artist", "Album")
        os.makedirs(album)
        cover_path = os.path.join(album, "cover.jpg")
        lrc = os.path.join(album, "gone.lrc")
        part = os.path.join(album, "gone.flac.part")
        keep_dir = os.path.join(self.music, "Keep Artist", "Keep Album")
        os.makedirs(keep_dir)
        keep_audio = os.path.join(keep_dir, "keep.flac")
        keep_cover = os.path.join(keep_dir, "cover.jpg")
        for path, data in (
            (cover_path, b"x"),
            (lrc, b"[00:00.00]x"),
            (part, b"partial"),
            (keep_audio, b"fLaC"),
            (keep_cover, b"x"),
        ):
            with open(path, "wb") as fh:
                fh.write(data)
        n = library.sweep_music_orphans()
        self.assertGreaterEqual(n, 3)
        self.assertFalse(os.path.isdir(album))
        self.assertTrue(os.path.isfile(keep_audio))
        self.assertTrue(os.path.isfile(keep_cover))

    def test_probe_prune_drops_deleted_names(self):
        cat = library.Library()
        cat.scanning = False
        with cat.lock:
            cat.cache = {
                "gone.flac|10|1": {"title": "Gone"},
                "keep.flac|10|1": {"title": "Keep"},
            }
            cat.edits = {"gone.flac": {"artist": "X"}}
        n = cat.prune(["keep.flac"])
        self.assertGreaterEqual(n, 2)
        self.assertIn("keep.flac|10|1", cat.cache)
        self.assertNotIn("gone.flac|10|1", cat.cache)
        self.assertNotIn("gone.flac", cat.edits)


class CachePruneTests(unittest.TestCase):
    def test_wave_prune(self):
        d = tempfile.mkdtemp(prefix="crypt-waves-")
        old = cryptwave.WAVE_DIR
        cryptwave.WAVE_DIR = d
        try:
            keep = os.path.join(d, "keep.json")
            gone = os.path.join(d, "gone.json")
            tmp = os.path.join(d, "stale.json.tmp")
            with open(keep, "w") as fh:
                json.dump({"v": 4, "name": "keep.wav", "n": 1}, fh)
            with open(gone, "w") as fh:
                json.dump({"v": 4, "name": "gone.wav", "n": 1}, fh)
            with open(tmp, "w") as fh:
                fh.write("{}")
            idx = cryptwave.WaveIndex()
            n = idx.prune(["keep.wav"])
            self.assertGreaterEqual(n, 2)
            self.assertTrue(os.path.isfile(keep))
            self.assertFalse(os.path.isfile(gone))
            self.assertFalse(os.path.isfile(tmp))
        finally:
            cryptwave.WAVE_DIR = old
            shutil.rmtree(d, ignore_errors=True)

    def test_lyrics_prune(self):
        music = tempfile.mkdtemp(prefix="crypt-music-")
        cache = tempfile.mkdtemp(prefix="crypt-lyrics-")
        old_m, old_c = lyrics.MUSIC_DIR, lyrics.LYRICS_DIR
        lyrics.MUSIC_DIR = music
        lyrics.LYRICS_DIR = cache
        try:
            keep = os.path.join(cache, "keep.json")
            gone = os.path.join(cache, "gone.json")
            with open(keep, "w") as fh:
                json.dump({"ok": True, "name": "keep.wav", "lines": [1]}, fh)
            with open(gone, "w") as fh:
                json.dump({"ok": True, "name": "gone.wav", "lines": [1]}, fh)
            idx = lyrics.LyricsIndex(start=False)
            n = idx.prune(["keep.wav"])
            self.assertGreaterEqual(n, 1)
            self.assertTrue(os.path.isfile(keep))
            self.assertFalse(os.path.isfile(gone))
        finally:
            lyrics.MUSIC_DIR, lyrics.LYRICS_DIR = old_m, old_c
            shutil.rmtree(music, ignore_errors=True)
            shutil.rmtree(cache, ignore_errors=True)

    def test_report_prune(self):
        music = tempfile.mkdtemp(prefix="crypt-music-")
        cache = tempfile.mkdtemp(prefix="crypt-reports-")
        old_m, old_c = report.MUSIC_DIR, report.REPORT_DIR
        report.MUSIC_DIR = music
        report.REPORT_DIR = cache
        try:
            keep = os.path.join(cache, "keep.json")
            gone = os.path.join(cache, "gone.json")
            with open(keep, "w") as fh:
                json.dump({"ok": True, "name": "keep.wav"}, fh)
            with open(gone, "w") as fh:
                json.dump({"ok": True, "name": "gone.wav"}, fh)
            idx = report.ReportIndex()
            n = idx.prune(["keep.wav"])
            self.assertGreaterEqual(n, 1)
            self.assertTrue(os.path.isfile(keep))
            self.assertFalse(os.path.isfile(gone))
        finally:
            report.MUSIC_DIR, report.REPORT_DIR = old_m, old_c
            shutil.rmtree(music, ignore_errors=True)
            shutil.rmtree(cache, ignore_errors=True)


class RecentsPruneTests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="crypt-state-")
        self.old = savant.STATE_DIR, savant.RECENTS_FILE
        savant.STATE_DIR = self.state
        savant.RECENTS_FILE = os.path.join(self.state, "savant-recents.json")

    def tearDown(self):
        savant.STATE_DIR, savant.RECENTS_FILE = self.old
        shutil.rmtree(self.state, ignore_errors=True)

    def test_drop_play_and_keep_nas(self):
        savant.remember_play("gone.flac", title="Gone", origin="local")
        savant.remember_play("keep.flac", title="Keep", origin="local")
        savant.remember_play("NAS/Song.mp3", title="Nas", origin="nas")
        self.assertEqual(savant.drop_play("gone.flac"), 1)
        names = [r["name"] for r in savant.load_recents()]
        self.assertNotIn("gone.flac", names)
        self.assertIn("keep.flac", names)
        n = savant.prune_recents(["keep.flac"])
        self.assertEqual(n, 0)
        savant.remember_play("old.flac", title="Old", origin="local")
        n = savant.prune_recents(["keep.flac"])
        self.assertEqual(n, 1)
        names = [r["name"] for r in savant.load_recents()]
        self.assertIn("NAS/Song.mp3", names)
        self.assertIn("keep.flac", names)
        self.assertNotIn("old.flac", names)


class PlayRouteTests(unittest.TestCase):
    def test_rejects_non_audio_and_dotdot(self):
        p = player.HostPlayer(on_end=lambda: None)
        self.assertFalse(p.play("../secret.mp3"))
        self.assertEqual(p.error, "not found")
        self.assertFalse(p.play("notes.txt"))
        self.assertFalse(p.play("cover.jpg"))
        self.assertFalse(p.play("folder/../escape.flac"))


if __name__ == "__main__":
    unittest.main()
