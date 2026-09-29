#!/usr/bin/env python3
"""LAN identity helpers. No live host."""
import unittest

import identity


class LanTests(unittest.TestCase):
    def test_rfc1918(self):
        self.assertTrue(identity._is_lan("192.168.1.142"))
        self.assertTrue(identity._is_lan("192.168.0.20"))
        self.assertTrue(identity._is_lan("10.0.0.15"))
        self.assertTrue(identity._is_lan("172.16.4.8"))
        self.assertTrue(identity._is_lan("172.31.255.1"))
        self.assertFalse(identity._is_lan("172.15.0.1"))
        self.assertFalse(identity._is_lan("8.8.8.8"))
        self.assertFalse(identity._is_lan("127.0.0.1"))
        self.assertFalse(identity._is_lan(""))
        self.assertFalse(identity._is_lan("not-an-ip"))

    def test_loopback_blocked(self):
        self.assertTrue(identity._blocked("127.0.0.1"))
        self.assertTrue(identity._blocked("localhost"))

    def test_lab_ok(self):
        self.assertFalse(identity._blocked("192.168.1.142"))
        self.assertFalse(identity._blocked("10.0.0.50"))

    def test_stamp(self):
        self.assertEqual(identity.stamp("001AAE0739DB0000"), "39DB")


if __name__ == "__main__":
    unittest.main()
