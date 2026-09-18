#!/usr/bin/env python3
"""Savant RacePoint telnet on :5004. MMS/SMS tokens -> this host's player.

Python 3.8 stdlib. Does not talk to Carrillos Resident. Blueprint points
Inspector at this chassis IP, port 5004.
"""
from __future__ import print_function

import os
import socket
import subprocess
import threading
import time
import traceback

SAVANT_PORT = int(os.environ.get("SAVANT_PORT", "5004"))
PULSE_SINK = os.environ.get("PULSE_SINK", "@DEFAULT_SINK@")


def savant_to_host_vol(n):
    """Savant 0-50 -> host 0-100."""
    try:
        n = int(round(float(n)))
    except (TypeError, ValueError):
        return None
    n = max(0, min(50, n))
    return max(0, min(100, n * 2))


def host_to_savant_vol(n):
    try:
        n = int(round(float(n)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(50, int(round(n / 2.0))))


def _pactl(args):
    env = os.environ.copy()
    if "PULSE_SERVER" not in env:
        env["PULSE_SERVER"] = "unix:/var/run/pulse/native"
    try:
        return subprocess.check_output(
            ["pactl"] + list(args),
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=3,
            env=env,
        )
    except Exception:
        return ""


class HostBridge(object):
    """Talks to CryptApp in-process. Tests inject a fake."""

    def __init__(self, app):
        self.app = app
        self._muted = False
        self._vol_before_mute = 50

    def snapshot(self):
        snap = self.app.player.snapshot() if self.app is not None else {}
        vol = 0
        try:
            vol = int(self.app.player.volume())
        except Exception:
            vol = 0
        playing = bool(snap.get("playing"))
        paused = bool(snap.get("paused"))
        if playing:
            play = "Play"
        elif paused:
            play = "Pause"
        else:
            play = "Stop"
        title = snap.get("title") or ""
        if not title:
            name = snap.get("name") or ""
            title = os.path.splitext(os.path.basename(name))[0].replace("_", " ")
        return {
            "playing": playing,
            "paused": paused,
            "name": snap.get("name") or "",
            "origin": snap.get("origin") or "local",
            "title": title,
            "artist": snap.get("artist") or "",
            "album": snap.get("album") or "",
            "volume": vol,
            "muted": self._muted,
            "play": play,
            "power": "ON" if (playing or paused or (snap.get("name") or "")) else "OFF",
        }

    def play(self):
        snap = self.app.player.snapshot()
        if snap.get("paused"):
            return bool(self.app.resume())
        if snap.get("playing"):
            return True
        name = snap.get("name") or ""
        origin = snap.get("origin") or "local"
        if name:
            return bool(self.app.play_name(name, origin=origin))
        tracks = []
        try:
            tracks = self.app.catalog_snapshot() or []
        except Exception:
            tracks = list(getattr(self.app, "tracks", None) or [])
        if tracks:
            return bool(self.app.play_name(tracks[0].get("name") or ""))
        return False

    def pause(self):
        return bool(self.app.pause())

    def stop(self):
        return bool(self.app.stop())

    def next_track(self):
        return bool(self.app.next_track())

    def prev_track(self):
        return bool(self.app.prev_track())

    def set_volume(self, host_vol):
        ok = bool(self.app.player.set_volume(host_vol))
        if ok and host_vol > 0:
            self._muted = False
        return ok

    def bump_volume(self, delta_host):
        cur = int(self.app.player.volume() or 0)
        return self.set_volume(max(0, min(100, cur + int(delta_host))))

    def set_mute(self, on):
        on = bool(on)
        if on and not self._muted:
            self._vol_before_mute = int(self.app.player.volume() or 0)
        self._muted = on
        out = _pactl(["set-sink-mute", PULSE_SINK, "1" if on else "0"])
        if on:
            return True
        if self._vol_before_mute:
            self.app.player.set_volume(self._vol_before_mute)
        return True if out is not None else True

    def seek_rel(self, seconds):
        snap = self.app.player.snapshot()
        pos = float(snap.get("position") or 0)
        return bool(self.app.seek(max(0.0, pos + float(seconds))))


def status_lines(snap):
    vol = host_to_savant_vol(snap.get("volume") or 0)
    mute = "ON" if snap.get("muted") else "OFF"
    lines = [
        "OK",
        "Volume=%s" % vol,
        "Mute=%s" % mute,
        "Power=%s" % (snap.get("power") or "OFF"),
        "Play=%s" % (snap.get("play") or "Stop"),
        "Title=%s" % (snap.get("title") or ""),
        "Artist=%s" % (snap.get("artist") or ""),
        "Album=%s" % (snap.get("album") or ""),
    ]
    return lines


def handle_line(raw, bridge):
    """Parse one CR/LF command. Returns (ok, reply_lines)."""
    line = (raw or "").strip()
    if not line:
        return True, []
    if line.startswith("\xff"):
        return True, []
    # Telnet IAC leftovers at the front.
    while line and ord(line[0]) == 255:
        line = line[1:]
        if line and ord(line[0]) in (251, 252, 253, 254) and len(line) >= 2:
            line = line[2:] if len(line) > 2 else ""
        elif line:
            line = line[1:]
        line = line.strip()
        if not line:
            return True, []
    parts = line.split()
    cmd = parts[0]
    arg = " ".join(parts[1:]) if len(parts) > 1 else ""
    key = cmd.replace("_", "").lower()
    try:
        if key in ("play", "commandplay", "irplay", "transportcontrolplay", "transportcontrolplaypause"):
            snap = bridge.snapshot()
            if snap.get("playing") and key == "transportcontrolplaypause":
                ok = bridge.pause()
            else:
                ok = bridge.play()
            return ok, status_lines(bridge.snapshot())
        if key in ("pause", "commandpause", "irpause", "transportcontrolpause"):
            ok = bridge.pause()
            return ok, status_lines(bridge.snapshot())
        if key in ("stop", "commandstop", "irstop", "transportcontrolstop"):
            ok = bridge.stop()
            return ok, status_lines(bridge.snapshot())
        if key in ("skipnext", "skipup", "commandskipup", "irskip", "transportcontrolskipnext"):
            ok = bridge.next_track()
            return ok, status_lines(bridge.snapshot())
        if key in ("skipprevious", "skipdown", "commandskipdown", "irreplay", "transportcontrolskipprevious"):
            ok = bridge.prev_track()
            return ok, status_lines(bridge.snapshot())
        if key in ("setvolume",):
            n = savant_to_host_vol(arg.replace("=", " ").split()[-1] if arg else "")
            if n is None:
                return False, ["ERR volume"]
            ok = bridge.set_volume(n)
            return ok, status_lines(bridge.snapshot())
        if key in ("sendkeys", "ir"):
            token = arg.strip().lower()
            if token in ("volume+", "volumeplus", "vol+"):
                ok = bridge.bump_volume(4)
                return ok, status_lines(bridge.snapshot())
            if token in ("volume-", "volumeminus", "vol-"):
                ok = bridge.bump_volume(-4)
                return ok, status_lines(bridge.snapshot())
            if token in ("standby",):
                ok = bridge.stop()
                return ok, status_lines(bridge.snapshot())
            if token in ("fastforward", "ff"):
                ok = bridge.seek_rel(15)
                return ok, status_lines(bridge.snapshot())
            if token in ("rewind", "rew"):
                ok = bridge.seek_rel(-15)
                return ok, status_lines(bridge.snapshot())
            if token in ("mute",):
                snap = bridge.snapshot()
                ok = bridge.set_mute(not snap.get("muted"))
                return ok, status_lines(bridge.snapshot())
            return True, ["OK"]
        if key in ("mute", "irmute"):
            snap = bridge.snapshot()
            ok = bridge.set_mute(not snap.get("muted"))
            return ok, status_lines(bridge.snapshot())
        if key in ("muteon",):
            ok = bridge.set_mute(True)
            return ok, status_lines(bridge.snapshot())
        if key in ("muteoff",):
            ok = bridge.set_mute(False)
            return ok, status_lines(bridge.snapshot())
        if key in ("getstatus", "status"):
            return True, status_lines(bridge.snapshot())
        if key in ("shuffle", "repeat", "clearqueue", "thumbsup", "thumbsdown"):
            return True, ["OK"]
        return False, ["ERR unknown %s" % cmd]
    except Exception:
        traceback.print_exc()
        return False, ["ERR"]


class SavantTelnet(object):
    def __init__(self, app, port=SAVANT_PORT, host="0.0.0.0"):
        self.bridge = HostBridge(app)
        self.port = int(port)
        self.host = host
        self.sock = None
        self.error = ""
        self._stop = threading.Event()

    def snapshot(self):
        return {
            "ok": self.sock is not None and not self.error,
            "port": self.port,
            "error": self.error,
        }

    def start(self):
        t = threading.Thread(target=self._serve, name="savant-telnet", daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()
        sock = self.sock
        self.sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def _serve(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(8)
            sock.settimeout(1.0)
            self.sock = sock
            self.error = ""
        except Exception as exc:
            self.error = str(exc)
            traceback.print_exc()
            return
        while not self._stop.is_set():
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except Exception:
                if self._stop.is_set():
                    break
                time.sleep(0.2)
                continue
            threading.Thread(
                target=self._client,
                args=(conn,),
                name="savant-client",
                daemon=True,
            ).start()

    def _client(self, conn):
        conn.settimeout(300)
        buf = b""
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(1024)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    line = raw.replace(b"\r", b"").decode("utf-8", "replace")
                    _ok, lines = handle_line(line, self.bridge)
                    if not lines:
                        continue
                    payload = "\r\n".join(lines) + "\r\n"
                    try:
                        conn.sendall(payload.encode("utf-8", "replace"))
                    except Exception:
                        return
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
