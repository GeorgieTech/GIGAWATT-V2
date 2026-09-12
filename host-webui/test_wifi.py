#!/usr/bin/env python3
"""Wi-Fi connman parser tests. No live radio."""
import unittest

import wifi


SAMPLE = """
*AR Wired                ethernet_001aae0739db_cable
    ACEGFamily           wifi_001aae0739d9_4143454746616d696c79_managed_psk
    DIRECT-A9-HP ENVY 6000 series wifi_001aae0739d9_4449524543542d41392d485020454e5659203630303020736572696573_managed_psk
*AO ACEGFamily           wifi_001aae0739d9_4143454746616d696c79_managed_psk
"""

TECH = """
/net/connman/technology/ethernet
  Name = Wired
  Type = ethernet
  Powered = True
  Connected = True
/net/connman/technology/wifi
  Name = WiFi
  Type = wifi
  Powered = True
  Connected = False
"""


class ParseTests(unittest.TestCase):
    def test_services(self):
        rows = wifi.parse_services(SAMPLE)
        names = [r["name"] for r in rows]
        self.assertIn("ACEGFamily", names)
        self.assertIn("DIRECT-A9-HP ENVY 6000 series", names)
        wired = [r for r in rows if r["type"] == "ethernet"][0]
        self.assertTrue(wired["connected"])
        live = [r for r in rows if r["name"] == "ACEGFamily" and r["connected"]]
        self.assertEqual(len(live), 1)

    def test_technologies(self):
        rows = wifi.parse_technologies(TECH)
        wifi_row = [r for r in rows if r["type"] == "wifi"][0]
        self.assertEqual(wifi_row["powered"], "True")
        self.assertEqual(wifi_row["connected"], "False")


if __name__ == "__main__":
    unittest.main()
