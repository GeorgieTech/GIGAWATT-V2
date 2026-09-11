#!/usr/bin/env python3
"""Track report + research plugin tests. No live network."""
import json
import os
import shutil
import tempfile
import unittest

import report
import research


class SentenceTests(unittest.TestCase):
    def test_takes_first_two(self):
        text = "One sentence. Two sentence. Three stays out."
        self.assertEqual(research.sentences(text, 2), "One sentence. Two sentence.")


class FakePlugin(object):
    def __init__(self):
        self.calls = 0

    def gather(self, artist, title, album=""):
        self.calls += 1
        return {
            "ok": True,
            "recording": {
                "source": "MusicBrainz recording",
                "year": "2018",
                "first_release": "2018-04-01",
                "tags": ["hip hop"],
                "releases": [{"title": "Glow LP", "year": "2018", "date": "2018-04-01"}],
                "url": "https://musicbrainz.org/recording/x",
            },
            "artist_info": {
                "source": "MusicBrainz artist",
                "type": "Person",
                "country": "US",
                "begin_area": "Maryland",
                "born": "1990",
                "tags": ["rap"],
                "url": "https://musicbrainz.org/artist/y",
            },
            "wiki_song": {
                "source": "Wikipedia",
                "extract": "Fixture Glow is a test recording. It was written in a lab.",
                "url": "https://en.wikipedia.org/wiki/Fixture_Glow",
            },
            "wiki_artist": {
                "source": "Wikipedia",
                "extract": "CRYPT Test is a fixture artist used only in unit tests.",
                "url": "https://en.wikipedia.org/wiki/CRYPT_Test",
            },
            "sources": [
                {"label": "MusicBrainz recording", "url": "https://musicbrainz.org/recording/x"},
                {"label": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Fixture_Glow"},
            ],
        }


class ReportAssembleTests(unittest.TestCase):
    def setUp(self):
        self.music = tempfile.mkdtemp(prefix="crypt-music-")
        self.cache = tempfile.mkdtemp(prefix="crypt-reports-")
        self.old_music = report.MUSIC_DIR
        self.old_cache = report.REPORT_DIR
        report.MUSIC_DIR = self.music
        report.REPORT_DIR = self.cache
        self.wav = os.path.join(self.music, "glow.wav")
        with open(self.wav, "wb") as fh:
            fh.write(b"RIFFTEST")

    def tearDown(self):
        report.MUSIC_DIR = self.old_music
        report.REPORT_DIR = self.old_cache
        shutil.rmtree(self.music, ignore_errors=True)
        shutil.rmtree(self.cache, ignore_errors=True)

    def test_local_does_not_hit_plugin(self):
        plugin = FakePlugin()
        idx = report.ReportIndex(plugin)
        data = idx.lookup("glow.wav", fetch=False)
        self.assertTrue(data["ok"])
        self.assertFalse(data["researched"])
        self.assertEqual(plugin.calls, 0)
        self.assertTrue(data["story"])

    def test_research_builds_caption_and_cache(self):
        plugin = FakePlugin()
        idx = report.ReportIndex(plugin)
        data = idx.lookup("glow.wav", fetch=True, duration=210)
        self.assertEqual(plugin.calls, 1)
        self.assertTrue(data["researched"])
        self.assertIn("2018", data["caption"])
        self.assertTrue(any(t.startswith("#") for t in data["hashtags"]))
        self.assertIn("Maryland", " ".join(f["value"] for f in data["facts"]))
        self.assertIn("Instagram caption", data["markdown"])
        self.assertGreaterEqual(len(data.get("essay") or []), 4)
        self.assertIn("Meaning and life", data["markdown"])
        cached = idx.lookup("glow.wav", fetch=False)
        self.assertTrue(cached["researched"])
        self.assertEqual(plugin.calls, 1)
        self.assertTrue(cached.get("essay"))

    def test_drop_removes_named_cache(self):
        plugin = FakePlugin()
        idx = report.ReportIndex(plugin)
        idx.lookup("glow.wav", fetch=True)
        keep = os.path.join(self.cache, "keep.json")
        with open(keep, "w") as fh:
            json.dump({"ok": True, "name": "keep.wav"}, fh)
        n = idx.drop_name("glow.wav")
        self.assertGreaterEqual(n, 1)
        self.assertTrue(os.path.isfile(keep))
        self.assertIsNone(idx._read_cache("glow.wav"))


class ResearchPluginTests(unittest.TestCase):
    def test_gather_from_fake_http(self):
        def fake(url, extra=None):
            if "recording/?" in url:
                return {"recordings": [{
                    "id": "rec-1",
                    "title": "Fixture Glow",
                    "first-release-date": "2018-04-01",
                    "length": 210000,
                    "releases": [{"title": "Glow LP", "date": "2018-04-01"}],
                    "tags": [{"name": "hip hop", "count": 4}],
                }]}
            if "artist/?" in url:
                return {"artists": [{
                    "id": "art-1",
                    "name": "CRYPT Test",
                    "type": "Person",
                    "country": "US",
                    "begin-area": {"name": "Maryland"},
                    "life-span": {"begin": "1990-01-22"},
                    "tags": [{"name": "rap", "count": 2}],
                }]}
            if "explaintext" in url or "prop=extracts" in url:
                return {"query": {"pages": {"1": {
                    "title": "Fixture Glow",
                    "extract": "Fixture Glow is a test recording written in a lab. It explores staying lit when the room goes dark.",
                }}}}
            if "api.php" in url:
                return {"query": {"search": [{"title": "Fixture Glow (song)", "snippet": "a song"}]}}
            if "summary" in url:
                return {
                    "type": "standard",
                    "title": "Fixture Glow",
                    "extract": "Fixture Glow is a test recording. Second line.",
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Fixture_Glow"}},
                }
            return None
        plugin = research.ResearchPlugin(http=fake, pause=0)
        data = plugin.gather("CRYPT Test", "Fixture Glow", "Glow LP")
        self.assertTrue(data["ok"])
        self.assertEqual(data["recording"]["year"], "2018")
        self.assertEqual(data["artist_info"]["begin_area"], "Maryland")
        self.assertTrue(data["wiki_song"]["extract"])
        self.assertIn("staying lit", data["wiki_song"].get("extract_long") or "")
        self.assertTrue(data["sources"])


class EssayTests(unittest.TestCase):
    def test_fallback_covers_meaning_and_life(self):
        import essay
        paras = essay.fallback_essay({
            "title": "Fixture Glow",
            "artist": "CRYPT Test",
            "album": "Glow LP",
            "year": "2018",
            "genre": "Electronic",
            "origin": "Maryland · US",
            "wiki_song": {"extract": "Fixture Glow explores staying lit when the room goes dark. It is a song about keeping a private fire."},
            "wiki_artist": {"extract": "CRYPT Test is a fixture artist from Maryland."},
            "lyrics": "Hold the line\nKeep the glow",
            "facts": [],
            "sources": [],
        })
        blob = " ".join(paras)
        self.assertGreaterEqual(len(paras), 5)
        self.assertIn("Fixture Glow", blob)
        self.assertIn("life", blob.lower())
        self.assertIn("Hold the line", blob)

    def test_xai_writer_parses_chat(self):
        import essay
        def fake_post(url, body, headers, timeout=55):
            self.assertIn("Bearer", headers.get("Authorization") or "")
            self.assertTrue(body.get("messages"))
            return {"choices": [{"message": {"content": "Para one about meaning.\n\nPara two about a life."}}]}
        old = os.environ.get("XAI_API_KEY")
        os.environ["XAI_API_KEY"] = "test-key"
        try:
            paras, err = essay.xai_essay({"title": "Glow", "artist": "X"}, post=fake_post)
        finally:
            if old is None:
                os.environ.pop("XAI_API_KEY", None)
            else:
                os.environ["XAI_API_KEY"] = old
        self.assertEqual(err, "")
        self.assertEqual(len(paras), 2)


if __name__ == "__main__":
    unittest.main()
