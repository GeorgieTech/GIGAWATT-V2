#!/usr/bin/env python3
"""Join this chassis to a Wi-Fi LAN via connman. Stdlib only. Passphrase stays on the host."""
from __future__ import print_function

import os
import re
import subprocess
import threading
import time

CONF_DIR = os.environ.get("CONNMAN_DIR", "/var/lib/connman")
CONF_FILE = os.path.join(CONF_DIR, "gigawatt-wifi.config")
SSID_RE = re.compile(r"^[\x20-\x7e]{1,32}$")


def _run(args, timeout=12):
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            universal_newlines=True,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as exc:
        return 1, "", str(exc)


def parse_services(text):
    rows = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if "wifi_" not in line and "ethernet_" not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        svc = parts[-1]
        flags = line[:4].replace(" ", "")
        name = line[4:].replace(svc, "").strip()
        kind = "wifi" if svc.startswith("wifi_") else "ethernet"
        rows.append({
            "id": svc,
            "name": name or svc,
            "type": kind,
            "connected": "*" in flags and ("O" in flags or "R" in flags),
            "favorite": "F" in flags or "A" in flags,
            "flags": flags,
        })
    return rows


def parse_technologies(text):
    rows = []
    current = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("/net/connman/technology/"):
            if current:
                rows.append(current)
            current = {"path": line, "type": line.rsplit("/", 1)[-1]}
            continue
        if "=" in line and current:
            key, _, val = line.partition("=")
            current[key.strip().lower()] = val.strip()
    if current:
        rows.append(current)
    return rows


def _iface_ipv4(name):
    code, out, _err = _run(["ip", "-4", "-o", "addr", "show", "dev", name], timeout=3)
    if code != 0 or not out:
        return ""
    for part in out.split():
        if "/" in part and part[0].isdigit():
            return part.split("/")[0]
    return ""


class Wifi(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.error = ""

    def enable(self):
        _run(["connmanctl", "enable", "wifi"], timeout=8)
        return True

    def scan(self):
        self.enable()
        code, _out, err = _run(["connmanctl", "scan", "wifi"], timeout=20)
        if code != 0 and err:
            self.error = err.strip().split("\n")[-1]
        else:
            self.error = ""
        time.sleep(1.2)
        return self.status(scan=False)

    def status(self, scan=False):
        if scan:
            return self.scan()
        _code, tech_text, _err = _run(["connmanctl", "technologies"], timeout=8)
        techs = parse_technologies(tech_text)
        wifi_tech = {}
        for row in techs:
            if row.get("type") == "wifi":
                wifi_tech = row
                break
        _code, svc_text, _err = _run(["connmanctl", "services"], timeout=8)
        services = parse_services(svc_text)
        wifi_rows = [s for s in services if s.get("type") == "wifi"]
        eth = [s for s in services if s.get("type") == "ethernet"]
        connected = [s for s in wifi_rows if s.get("connected")]
        wlan_ip = _iface_ipv4("wlan0")
        eth_ip = _iface_ipv4("eth0")
        powered = str(wifi_tech.get("powered") or "").lower() == "true"
        return {
            "ok": True,
            "available": True,
            "powered": powered,
            "connected": bool(connected or wlan_ip),
            "ssid": (connected[0]["name"] if connected else ""),
            "wlan_ip": wlan_ip,
            "eth_ip": eth_ip,
            "ethernet": bool(eth and eth[0].get("connected")) or bool(eth_ip),
            "networks": wifi_rows[:16],
            "error": self.error,
        }

    def _write_config(self, ssid, passphrase):
        os.makedirs(CONF_DIR, exist_ok=True)
        body = (
            "[service_gigawatt]\n"
            "Type = wifi\n"
            "Name = %s\n"
            "Passphrase = %s\n"
            "AutoConnect = true\n"
            "IPv6 = off\n"
        ) % (ssid.replace("\n", ""), passphrase.replace("\n", ""))
        tmp = CONF_FILE + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(body)
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONF_FILE)

    def connect(self, ssid, passphrase):
        ssid = (ssid or "").strip()
        passphrase = passphrase or ""
        if not SSID_RE.match(ssid):
            return False, "need a Wi-Fi name"
        if len(passphrase) < 8 or len(passphrase) > 63:
            return False, "passphrase must be 8-63 characters"
        try:
            self._write_config(ssid, passphrase)
        except OSError as exc:
            return False, "could not save Wi-Fi: %s" % exc
        self.enable()
        _run(["connmanctl", "scan", "wifi"], timeout=20)
        time.sleep(2.0)
        _code, svc_text, _err = _run(["connmanctl", "services"], timeout=8)
        match = None
        for row in parse_services(svc_text):
            if row.get("type") == "wifi" and row.get("name") == ssid:
                match = row
                break
        if not match:
            return False, "network not in range"
        code, _out, err = _run(["connmanctl", "connect", match["id"]], timeout=25)
        if code != 0:
            msg = (err or "").strip().split("\n")[-1] or "connect failed"
            if "passphrase" in msg.lower() or "invalid" in msg.lower():
                msg = "wrong passphrase or network rejected this radio"
            return False, msg
        time.sleep(1.5)
        self.error = ""
        return True, ""

    def disconnect(self):
        snap = self.status()
        for row in snap.get("networks") or []:
            if row.get("connected") and row.get("id"):
                _run(["connmanctl", "disconnect", row["id"]], timeout=8)
        try:
            if os.path.isfile(CONF_FILE):
                os.remove(CONF_FILE)
        except OSError:
            pass
        return True
