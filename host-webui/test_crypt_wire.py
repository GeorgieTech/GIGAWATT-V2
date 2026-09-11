#!/usr/bin/env python3
"""CRYPT/1 wire tests. No live hosts."""
import socket
import unittest

import crypt_wire as w


class RoundtripTests(unittest.TestCase):
    def test_beacon_roundtrip(self):
        pkt = w.encode_beacon(
            "001AAE10E4090000", 42,
            ip="192.168.1.179", model="SHR-S2-00", version="1.1.10",
            tracks=12, libhash=0xDEADBEEFCAFEBABE, linked=True,
            playing=True, unison=True,
        )
        self.assertLessEqual(len(pkt), w.MAX_DGRAM)
        out = w.decode(pkt)
        self.assertEqual(out["kind"], "beacon")
        self.assertEqual(out["uid"], "001AAE10E4090000")
        self.assertEqual(out["ip"], "192.168.1.179")
        self.assertEqual(out["tracks"], 12)
        self.assertEqual(out["libver"], 0xDEADBEEFCAFEBABE)
        self.assertTrue(out["linked"])
        self.assertTrue(out["playing"])
        self.assertTrue(out["unison"])
        self.assertEqual(out["seq"], 42)
        self.assertEqual(out["v"], "1.1.10")

    def test_clock_roundtrip_microseconds(self):
        pkt = w.encode_clock("001AAE0739DB0000", 7, heard=1.234567, mono=9.0,
                             path=0.012, state=2, playing=True, unison=True)
        out = w.decode(pkt)
        self.assertEqual(out["kind"], "clock")
        self.assertAlmostEqual(out["heard"], 1.234567, places=5)
        self.assertAlmostEqual(out["path"], 0.012, places=5)
        self.assertEqual(out["state"], 2)
        self.assertTrue(out["unison"])

    def test_bad_checksum_dropped(self):
        pkt = bytearray(w.encode_beacon("001AAE10E4090000", 1, ip="192.168.1.179"))
        pkt[-1] ^= 0xFF
        self.assertIsNone(w.decode(bytes(pkt)))

    def test_json_beacon_still_accepted(self):
        raw = b'{"crypt":1,"v":"1.1.10","id":"crypt-001aae10e4090000","uid":"001AAE10E4090000"}'
        out = w.decode_any(raw)
        self.assertEqual(out["kind"], "beacon")
        self.assertEqual(out["wire"], 0)
        self.assertEqual(out["uid"], "001AAE10E4090000")

    def test_libver_stable(self):
        a = w.libver([
            {"name": "B.flac", "size": 2, "mtime": 9},
            {"name": "A.flac", "size": 1, "mtime": 8},
        ])
        b = w.libver([
            {"name": "A.flac", "size": 1, "mtime": 8},
            {"name": "B.flac", "size": 2, "mtime": 9},
        ])
        c = w.libver([
            {"name": "A.flac", "size": 1, "mtime": 99},
            {"name": "B.flac", "size": 2, "mtime": 9},
        ])
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class MulticastHelperTests(unittest.TestCase):
    def test_join_group_on_udp_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", 0))
            w.join_group(sock, iface="0.0.0.0")
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
