#!/usr/bin/env python3
"""Library main-artist grouping. No live host."""
import unittest

import library


class MainArtistTests(unittest.TestCase):
    def test_kanye_features_fold_to_west(self):
        self.assertEqual(library.main_artist("Kanye West, T-Pain"), "Kanye West")
        self.assertEqual(library.main_artist("Kanye West, Mos Def, Al Be Back"), "Kanye West")
        self.assertEqual(library.main_artist("Kanye West"), "Kanye West")

    def test_feat_and_ft(self):
        self.assertEqual(library.main_artist("Prospa feat. RAHH"), "Prospa")
        self.assertEqual(library.main_artist("Dom Dolla ft. Clementine Douglas"), "Dom Dolla")

    def test_albumartist_wins(self):
        self.assertEqual(
            library.main_artist("Kanye West, Chris Martin", "Kanye West"),
            "Kanye West",
        )

    def test_file_kind_from_extension(self):
        self.assertEqual(library.file_kind("Good Life.opus"), "OPUS")
        self.assertEqual(library.file_kind("Glow.flac"), "FLAC")
        self.assertEqual(library.file_kind("track.mp3"), "MP3")

    def test_bitrate_kbps_from_format(self):
        self.assertEqual(library._bitrate_kbps({"bit_rate": "192000"}, {}, 0), 192)
        self.assertEqual(library._bitrate_kbps({}, {"bit_rate": 320000}, 0), 320)
        self.assertEqual(library._bitrate_kbps({"duration": "10"}, {}, 240000), 192)

    def test_identity_exposes_main_artist(self):
        ident = library.identity_from_path(
            "Homecoming.opus",
            probed={"title": "Homecoming", "artist": "Kanye West, Chris Martin", "album": "Graduation"},
        )
        self.assertEqual(ident["artist"], "Kanye West, Chris Martin")
        self.assertEqual(ident["main_artist"], "Kanye West")
        self.assertEqual(ident["album"], "Graduation")


if __name__ == "__main__":
    unittest.main()
