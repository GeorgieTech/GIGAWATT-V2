#!/usr/bin/env python3
"""31-band 1/3-octave EQ tests. Stdlib only."""
import unittest

import player


class IsoBandsTests(unittest.TestCase):
    def test_thirty_one_iso_centers(self):
        self.assertEqual(len(player.EQ_BANDS), 31)
        self.assertEqual(len(player.EQ_FREQS), 31)
        self.assertEqual(player.EQ_FREQS[0], 20)
        self.assertEqual(player.EQ_FREQS[17], 1000)
        self.assertEqual(player.EQ_FREQS[-1], 20000)
        self.assertTrue(all(kind == "peaking" for kind, _f, _l in player.EQ_BANDS))

    def test_constant_q_is_third_octave(self):
        self.assertAlmostEqual(player.EQ_Q, 4.318, places=3)


class ExpandEqTests(unittest.TestCase):
    def test_flat_stays_flat(self):
        self.assertEqual(player.clamp_eq(None), [0.0] * 31)
        self.assertEqual(player.clamp_eq([0] * 10), [0.0] * 31)

    def test_ten_band_harman_keeps_1k_at_zero(self):
        old = [6.5, 6.0, 4.0, 1.5, 0.5, 0, -0.5, -2.5, -4.0, -6.0]
        got = player.clamp_eq(old)
        self.assertEqual(len(got), 31)
        self.assertAlmostEqual(got[player.EQ_FREQS.index(1000)], 0.0, places=2)
        self.assertGreater(got[player.EQ_FREQS.index(31.5)], 6.0)
        self.assertLess(got[player.EQ_FREQS.index(16000)], -5.0)
        harman = [p["gains"] for p in player.EQ_PRESETS if p["id"] == "harman"][0]
        self.assertEqual(got, harman)

    def test_thirty_one_passthrough(self):
        src = [0.0] * 31
        src[player.EQ_FREQS.index(50)] = -6.0
        got = player.clamp_eq(src)
        self.assertEqual(got[player.EQ_FREQS.index(50)], -6.0)
        self.assertEqual(sum(1 for g in got if g), 1)

    def test_clips_to_12(self):
        got = player.clamp_eq([99] * 31)
        self.assertTrue(all(g == 12.0 for g in got))


class FfmpegFilterTests(unittest.TestCase):
    def test_flat_omits_filters(self):
        self.assertEqual(player.ffmpeg_eq_filter([0] * 31), "")

    def test_single_hum_notch(self):
        gains = [0.0] * 31
        gains[player.EQ_FREQS.index(50)] = -6.0
        af = player.ffmpeg_eq_filter(gains)
        self.assertIn("equalizer=f=50:t=q:w=4.318:g=-6.00", af)
        self.assertEqual(af.count("equalizer="), 1)


class PresetTests(unittest.TestCase):
    def test_all_presets_are_31_bands(self):
        ids = [p["id"] for p in player.EQ_PRESETS]
        self.assertEqual(ids, ["flat", "harman", "bk1974", "hifi", "nad"])
        for preset in player.EQ_PRESETS:
            self.assertEqual(len(preset["gains"]), 31, preset["id"])
            self.assertEqual(player.clamp_eq(preset["gains"]), list(map(float, preset["gains"])))

    def test_house_curves_anchor_1k(self):
        idx = player.EQ_FREQS.index(1000)
        for preset in player.EQ_PRESETS:
            if preset["id"] == "flat":
                continue
            self.assertAlmostEqual(preset["gains"][idx], 0.0, places=2, msg=preset["id"])

    def test_nad_has_less_rumble_than_punch(self):
        nad = [p for p in player.EQ_PRESETS if p["id"] == "nad"][0]["gains"]
        self.assertLess(nad[0], nad[player.EQ_FREQS.index(31.5)])
        self.assertLess(nad[player.EQ_FREQS.index(20)], nad[player.EQ_FREQS.index(50)])


if __name__ == "__main__":
    unittest.main()
