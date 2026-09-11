#!/usr/bin/env python3
"""Cover Art Archive lookup tests. No live network."""
import json
import os
import shutil
import tempfile
import time
import unittest

import cover


class PickTests(unittest.TestCase):
    def test_prefers_front_500(self):
        url = cover.pick_image({
            "images": [
                {
                    "types": ["Back"],
                    "thumbnails": {"500": "http://x/back-500.jpg"},
                    "image": "http://x/back.jpg",
                },
                {
                    "types": ["Front"],
                    "front": True,
                    "thumbnails": {"250": "http://x/front-250.jpg", "500": "http://x/front-500.jpg"},
                    "image": "http://x/front.jpg",
                },
            ]
        })
        self.assertEqual(url, "http://x/front-500.jpg")

    def test_empty(self):
        self.assertEqual(cover.pick_image({}), "")
        self.assertEqual(cover.pick_image(None), "")


class KeyTests(unittest.TestCase):
    def test_same_album_same_key(self):
        a = cover.album_key("Daft Punk", "Random Access Memories")
        b = cover.album_key("  daft   punk ", "random access memories")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 20)

    def test_unknown_falls_back_to_name(self):
        k = cover.album_key("Unknown artist", "Unknown album", "Glow.flac")
        self.assertTrue(k)
        self.assertEqual(k, cover.album_key("", "", "Glow.flac"))


class IndexTests(unittest.TestCase):
    def test_decorate_and_missing_ttl(self):
        folder = tempfile.mkdtemp(prefix="crypt-cover-")
        try:
            idx = cover.CoverIndex(folder=folder, http_json=lambda url: None, http_bytes=lambda url: (b"", ""), pause=0)
            idx._alive = False
            key = cover.album_key("Artist", "Album")
            idx.index[key] = {"found": True, "missing": False, "at": time.time()}
            path = idx._path(key)
            with open(path, "wb") as fh:
                fh.write(b"\xff\xd8\xff" + b"x" * 20)
            rows = idx.decorate([{"name": "a.flac", "artist": "Artist", "album": "Album"}])
            self.assertTrue(rows[0]["cover"].endswith(key))
            idx.index[key] = {"found": False, "missing": True, "at": time.time()}
            os.remove(path)
            rows = idx.decorate([{"name": "a.flac", "artist": "Artist", "album": "Album"}])
            self.assertTrue(rows[0].get("cover_missing"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_caa_json_then_bytes(self):
        folder = tempfile.mkdtemp(prefix="crypt-cover-")
        jpeg = b"\xff\xd8\xff" + b"\x00" * 80

        def fake_json(url):
            if "/release/?" in url:
                return {"releases": [{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "title": "Album", "release-group": {"id": "rg"}}]}
            if "coverartarchive.org/release/" in url:
                return {"images": [{"types": ["Front"], "thumbnails": {"500": "http://archive.example/front-500.jpg"}}]}
            return None

        def fake_bytes(url):
            if "front-500" in url:
                return jpeg, "image/jpeg"
            return b"", ""

        try:
            idx = cover.CoverIndex(folder=folder, http_json=fake_json, http_bytes=fake_bytes, pause=0)
            idx._alive = False
            raw, kind, mbid = idx._caa_bytes("Artist", "Album", "Song")
            self.assertEqual(kind, "image/jpeg")
            self.assertEqual(raw[:3], b"\xff\xd8\xff")
            self.assertEqual(mbid, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
