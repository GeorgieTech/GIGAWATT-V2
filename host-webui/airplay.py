#!/usr/bin/env python3
"""AirPlay 1 receiver wrapper around vendored shairport-sync 3.3.x."""
from __future__ import print_function

import base64
import os
import re
import stat
import subprocess
import threading
import time

META_PIPE = "/tmp/gigawatt-airplay.meta"
NAME_RE = re.compile(r"^[A-Za-z0-9._ -]{1,50}$")
DEFAULT_NAME = "Gigawatt"

# Same stuffing as Gigawatt Beta2 (worked). V2 auto/soxr + 0.5 s buffer skipped on TOSLINK.
CONF_TEMPLATE = """general = {
  name = "%s";
  interpolation = "basic";
  output_backend = "pa";
  ignore_volume_control = "no";
  port = 5000;
};
sessioncontrol = {
  allow_session_interruption = "yes";
  session_timeout = 120;
};
metadata = {
  enabled = "yes";
  include_cover_art = "no";
  pipe_name = "%s";
  pipe_timeout = 5000;
};
pa = {
  application_name = "Gigawatt AirPlay";
};
"""

ITEM_RE = re.compile(
    br"<item><type>([0-9a-fA-F]+)</type><code>([0-9a-fA-F]+)</code><length>(\d+)</length>"
    br"(?:\s*<data encoding=\"base64\">(.*?)</data>)?\s*</item>",
    re.DOTALL | re.IGNORECASE,
)


def sanitize_name(name):
    name = (name or "").strip()
    if not NAME_RE.match(name):
        return None
    return name


def default_name():
    try:
        from identity import identity, stamp
        me = identity()
        tag = stamp(me.get("uid") or me.get("id") or "")
        if tag:
            return "Gigawatt %s" % tag
    except Exception:
        pass
    return DEFAULT_NAME


def _fourcc(hexstr):
    try:
        n = int(hexstr, 16)
    except (TypeError, ValueError):
        return "????"
    chars = []
    for shift in (24, 16, 8, 0):
        c = (n >> shift) & 0xFF
        chars.append(chr(c) if 32 <= c < 127 else "?")
    return "".join(chars)


def _decode_payload(b64):
    if not b64:
        return ""
    raw = b64.strip()
    if not raw:
        return ""
    try:
        data = base64.b64decode(raw)
    except Exception:
        return raw.decode("utf-8", "replace").strip()
    if not data:
        return ""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", "replace").replace("\x00", "").strip()
    try:
        text = data.decode("utf-8")
    except Exception:
        text = data.decode("utf-8", "replace")
    if "\x00" in text:
        try:
            text = data.decode("utf-16-be")
        except Exception:
            text = text.replace("\x00", "")
    return text.strip()


def _pulse_sock_path():
    raw = os.environ.get("PULSE_SERVER") or ""
    if raw.startswith("unix:"):
        return raw[5:] or "/run/pulse/native"
    if raw.startswith("/"):
        return raw
    for path in ("/var/run/pulse/native", "/run/pulse/native"):
        if os.path.exists(path):
            return path
    return "/var/run/pulse/native"


def pulse_ready(timeout=0.0):
    path = _pulse_sock_path()
    deadline = time.time() + max(0.0, float(timeout))
    while True:
        if os.path.exists(path):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.2)


def _pulse_env():
    env = os.environ.copy()
    env["PULSE_SERVER"] = env.get("PULSE_SERVER") or ("unix:" + _pulse_sock_path())
    return env


AIRPLAY_RATES = (44100, 48000)
LOCAL_RATE = 96000
_SINK = "@DEFAULT_SINK@"


def parse_sink_rate(text):
    for line in (text or "").splitlines():
        if "Sample Specification:" not in line:
            continue
        match = re.search(r"(\d+)\s*Hz", line, re.I)
        if match:
            return int(match.group(1))
    return 0


def _pactl(args, timeout=4):
    try:
        return subprocess.check_output(
            ["pactl"] + args,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=timeout,
            env=_pulse_env(),
        )
    except Exception:
        return ""


def current_spdif_rate():
    return parse_sink_rate(_pactl(["list", "sinks"]))


def _suspend_sink(on):
    _pactl(["suspend-sink", _SINK, "1" if on else "0"])


def _kick_silence(rate, msec=80):
    """Short stream at `rate` so Pulse reopens imx-spdif at that rate."""
    try:
        rate = int(rate)
    except (TypeError, ValueError):
        return False
    frames = max(1, int(rate * (msec / 1000.0)))
    raw = b"\x00" * (frames * 4)
    proc = None
    try:
        proc = subprocess.Popen(
            [
                "paplay",
                "--device=" + _SINK,
                "--raw",
                "--format=s16le",
                "--rate=%d" % rate,
                "--channels=2",
                "--latency-msec=50",
                "--client-name=TOSLINK-RATE",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_pulse_env(),
        )
        proc.stdin.write(raw)
        proc.stdin.close()
        proc.wait(timeout=3)
        return True
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        return False


def set_spdif_rate(rate):
    """Open TOSLINK at `rate` so AirPlay is not resampled 44.1 → 96 kHz."""
    want = int(rate or 0)
    if want < 8000:
        return 0
    got = current_spdif_rate()
    if got == want:
        return got
    _suspend_sink(True)
    time.sleep(0.18)
    _suspend_sink(False)
    time.sleep(0.12)
    got = current_spdif_rate()
    if got == want:
        return got
    _kick_silence(want)
    time.sleep(0.12)
    return current_spdif_rate()


def _pulse_airplay_playing():
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sink-inputs"],
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=2,
            env=_pulse_env(),
        )
    except Exception:
        return False
    return "Gigawatt AirPlay" in out or "shairport" in out.lower()


def _relax_pulse_idle():
    """Savant loads module-suspend-on-idle timeout=0, which suspends TOSLINK
    between AirPlay packets and makes the jack skip. Hold the sink up."""
    env = _pulse_env()
    try:
        out = subprocess.check_output(
            ["pactl", "list", "modules", "short"],
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=3,
            env=env,
        )
    except Exception:
        return
    for line in out.splitlines():
        if "module-suspend-on-idle" not in line:
            continue
        idx = line.split()[0]
        try:
            subprocess.call(
                ["pactl", "unload-module", idx],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                env=env,
            )
        except Exception:
            pass
    try:
        subprocess.call(
            ["pactl", "load-module", "module-suspend-on-idle", "timeout=300"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            env=env,
        )
    except Exception:
        pass


class AirPlay(object):
    def __init__(self, directory, on_begin=None, on_end=None, name=None):
        self.directory = directory
        self.on_begin = on_begin
        self.on_end = on_end
        self.lock = threading.Lock()
        self.proc = None
        self.enabled = False
        self.active = False
        self.title = ""
        self.artist = ""
        self.album = ""
        self.client = ""
        self.error = ""
        self.name = sanitize_name(name) or default_name()
        self._meta_fh = None
        self._keeper = False
        self._jack_matched = False
        try:
            self._write_conf()
        except Exception:
            pass

    def available(self):
        return os.path.isfile(os.path.join(self.directory, "run-shairport"))

    def snapshot(self):
        with self.lock:
            running = self.proc is not None and self.proc.poll() is None
            if self.proc is not None and self.proc.poll() is not None:
                self.proc = None
                self.active = False
                running = False
            if running and not self.active:
                now = time.time()
                if now - float(getattr(self, "_pulse_at", 0) or 0) >= 5:
                    self._pulse_at = now
                    if _pulse_airplay_playing():
                        self.active = True
            title = self.title
            if self.active and not title:
                title = "AirPlay"
            err = self.error
            if self.enabled and not running and not err:
                err = "starting"
            return {
                "available": self.available(),
                "enabled": bool(self.enabled),
                "active": bool(self.active and running),
                "name": self.name,
                "title": title,
                "artist": self.artist,
                "album": self.album,
                "client": self.client,
                "error": err,
            }

    def set_name(self, name):
        clean = sanitize_name(name)
        if not clean:
            self.error = "name must be 1-50 letters, numbers, space, dot, underscore, or dash"
            return False
        with self.lock:
            self.name = clean
            try:
                self._write_conf()
            except Exception as exc:
                self.error = str(exc)
                return False
            self.error = ""
            if self.enabled:
                self._stop_locked()
                return self._start_locked()
            return True

    def _write_conf(self):
        path = os.path.join(self.directory, "shairport-sync.conf")
        body = CONF_TEMPLATE % (self.name.replace("\\", "").replace("\"", ""), META_PIPE)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(body)
        os.replace(tmp, path)

    def set_enabled(self, value):
        want = bool(value)
        with self.lock:
            self.enabled = want
            if want:
                ok = self._start_locked()
                self._ensure_keeper_locked()
                return ok
            self._stop_locked()
            self._restore_toslink()
            self.error = ""
            return True

    def _ensure_keeper_locked(self):
        if self._keeper:
            return
        self._keeper = True
        threading.Thread(target=self._keep_alive, daemon=True).start()

    def _keep_alive(self):
        while True:
            time.sleep(2)
            with self.lock:
                if not self.enabled:
                    self._keeper = False
                    return
                alive = self.proc is not None and self.proc.poll() is None
                if alive:
                    continue
                self._start_locked()

    def bounce(self):
        with self.lock:
            if not self.enabled:
                return True
            self._stop_locked()
            return self._start_locked()

    def _ensure_fifo(self):
        path = META_PIPE
        if os.path.exists(path) and not stat.S_ISFIFO(os.stat(path).st_mode):
            os.remove(path)
        if not os.path.exists(path):
            os.mkfifo(path, 0o666)
        try:
            os.chmod(path, 0o666)
        except Exception:
            pass
        if self._meta_fh is None:
            fd = os.open(path, os.O_RDWR)
            self._meta_fh = os.fdopen(fd, "rb", buffering=0)

    def _start_locked(self):
        if not self.available():
            self.error = "AirPlay binary missing"
            return False
        if self.proc is not None and self.proc.poll() is None:
            self.error = ""
            return True
        if not pulse_ready(0):
            self.error = "waiting for PulseAudio"
            return False
        _relax_pulse_idle()
        try:
            self._ensure_fifo()
        except Exception as exc:
            self.error = "metadata pipe: %s" % exc
            return False
        env = os.environ.copy()
        env["PULSE_SERVER"] = env.get("PULSE_SERVER") or ("unix:" + _pulse_sock_path())
        cmd = os.path.join(self.directory, "run-shairport")
        try:
            self.proc = subprocess.Popen(
                [cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except Exception as exc:
            self.error = str(exc)
            self.proc = None
            return False
        self.error = ""
        self.active = False
        self._jack_matched = False
        threading.Thread(target=self._meta_loop, daemon=True).start()
        threading.Thread(target=self._pulse_watch, daemon=True).start()
        return True

    def _stop_locked(self):
        proc = self.proc
        self.proc = None
        was = self.active
        self.active = False
        self.title = ""
        self.artist = ""
        self.album = ""
        self.client = ""
        if was:
            self._restore_toslink()
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _match_toslink(self):
        """Run imx-spdif at AirPlay's rate (44.1 kHz, else 48 kHz)."""
        if self._jack_matched:
            return
        for rate in AIRPLAY_RATES:
            if set_spdif_rate(rate) == rate:
                self._jack_matched = True
                return
        self._jack_matched = True

    def _restore_toslink(self):
        if not self._jack_matched and current_spdif_rate() == LOCAL_RATE:
            return
        set_spdif_rate(LOCAL_RATE)
        self._jack_matched = False

    def _pulse_watch(self):
        while True:
            with self.lock:
                proc = self.proc
                known_active = self.active
            if proc is None or proc.poll() is not None:
                return
            flowing = _pulse_airplay_playing()
            if flowing and not known_active:
                begin = False
                with self.lock:
                    if not self.active:
                        self.active = True
                        begin = True
                if begin:
                    if self.on_begin:
                        try:
                            self.on_begin()
                        except Exception:
                            pass
                    self._match_toslink()
            elif not flowing and known_active:
                end = False
                with self.lock:
                    if not self.title:
                        self.active = False
                        end = True
                if end:
                    self._restore_toslink()
            time.sleep(1.0)

    def _meta_loop(self):
        buf = b""
        while True:
            with self.lock:
                proc = self.proc
                fh = self._meta_fh
            if proc is None or proc.poll() is not None or fh is None:
                return
            try:
                chunk = os.read(fh.fileno(), 4096)
            except Exception:
                time.sleep(0.2)
                continue
            if not chunk:
                time.sleep(0.05)
                continue
            buf += chunk
            buf = self._consume(buf)

    def _consume(self, buf):
        while True:
            match = ITEM_RE.search(buf)
            if not match:
                if len(buf) > 2 * 1024 * 1024:
                    buf = buf[-65536:]
                return buf
            typ, code, _length, b64 = match.group(1), match.group(2), match.group(3), match.group(4)
            key = _fourcc(typ.decode("ascii", "replace")) + "." + _fourcc(code.decode("ascii", "replace"))
            payload = _decode_payload(b64 or b"")
            self._apply(key, payload)
            buf = buf[match.end():]
        return buf

    def _apply(self, key, text):
        begin = False
        end = False
        with self.lock:
            was = self.active
            if key == "ssnc.pbeg":
                self.active = True
            elif key == "ssnc.pend":
                self.active = False
                self.title = ""
                self.artist = ""
                self.album = ""
            elif key == "ssnc.prsm":
                self.active = True
            elif key == "core.minm":
                if text:
                    self.title = text
                self.active = True
            elif key == "core.asar":
                if text:
                    self.artist = text
            elif key == "core.asal":
                if text:
                    self.album = text
            elif key in ("ssnc.snam", "ssnc.snua", "ssnc.clip"):
                if text:
                    self.client = text
            if self.active and not was:
                begin = True
            if was and not self.active:
                end = True
        if begin:
            if self.on_begin:
                try:
                    self.on_begin()
                except Exception:
                    pass
            self._match_toslink()
        if end:
            self._restore_toslink()
