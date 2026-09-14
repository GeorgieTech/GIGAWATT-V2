#!/usr/bin/env python3
"""NAS path and form checks. No live share."""
import os
import shutil
import tempfile
import unittest

import nas


class RelTests(unittest.TestCase):
    def test_rejects_dotdot(self):
        self.assertIsNone(nas.rel_ok("../etc"))
        self.assertEqual(nas.rel_ok("Artist/Album"), "Artist/Album")
        self.assertEqual(nas.rel_ok(""), "")

    def test_meta_from_folders(self):
        artist, album, title = nas.parse_nas_meta("Kanye West/Graduation/Stronger.flac")
        self.assertEqual(artist, "Kanye West")
        self.assertEqual(album, "Graduation")
        self.assertEqual(title, "Stronger")


class ApplyTests(unittest.TestCase):
    def test_rejects_bad_host(self):
        folder = tempfile.mkdtemp(prefix="nas-")
        try:
            share = nas.NasShare(folder, os.path.join(folder, "mnt"), folder)
            self.assertFalse(share.apply({"host": "bad host!"}))
            self.assertTrue(share.error)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_splits_truenas_dataset_path(self):
        folder = tempfile.mkdtemp(prefix="nas-")
        try:
            share = nas.NasShare(folder, os.path.join(folder, "mnt"), folder)
            ok = share.apply({"host": "192.168.1.61", "share": "Pool/Delorean/Music", "username": "carrillo"})
            self.assertTrue(ok, share.error)
            self.assertEqual(share.cfg["share"], "Music")
            self.assertEqual(share.cfg["host"], "192.168.1.61")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_saves_share(self):
        folder = tempfile.mkdtemp(prefix="nas-")
        try:
            share = nas.NasShare(folder, os.path.join(folder, "mnt"), folder)
            ok = share.apply({"host": "192.168.1.10", "share": "Music", "username": "user"})
            self.assertTrue(ok)
            snap = share.snapshot()
            self.assertEqual(snap["host"], "192.168.1.10")
            self.assertEqual(snap["share"], "Music")
            self.assertFalse(snap["available"])
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class BrowseTests(unittest.TestCase):
    def test_empty_unmounted(self):
        catalog = nas.browse("", mountpoint="/tmp/does-not-exist-nas")
        self.assertTrue(catalog.get("error"))


if __name__ == "__main__":
    unittest.main()
