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

CONF_TEMPLATE = """general = {
  name = "%s";
  interpolation = "auto";
  output_backend = "pa";
  ignore_volume_control = "yes";
  drift_tolerance_in_seconds = 0.012;
  resync_threshold_in_seconds = 0.150;
  audio_backend_buffer_desired_length_in_seconds = 0.50;
  audio_backend_buffer_interpolation_threshold_in_seconds = 0.075;
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

# Pulse daemon.conf fragment. Savant SPDIF is fixed at 96 kHz; AirPlay ALAC
# lands at 44.1/48 kHz. Keep the hardware word clock at 96 and let Pulse
# speex-remap once at the sink edge (do not fight Host Time Clock).
PULSE_DAEMON_SNIPPET = """
# GIGAWATT-AUDIO-BEGIN
# TOSLINK word clock stays 96 kHz (imx-spdif). AirPlay / library streams may
# be 44.1 or 48 kHz; Pulse remaps with speex onto the Savant sink.
default-sample-rate = 96000
alternate-sample-rate = 48000
resample-method = speex-float-1
avoid-resampling = no
default-fragments = 8
default-fragment-size-msec = 50
high-priority = yes
# GIGAWATT-AUDIO-END
"""


def ensure_pulse_daemon_conf(path="/etc/pulse/daemon.conf"):
    """Install / refresh the 48→96 remap block. Safe to call on every push."""
    try:
        with open(path, "r") as fh:
            text = fh.read()
    except OSError:
        return False
    begin = "# GIGAWATT-AUDIO-BEGIN"
    end = "# GIGAWATT-AUDIO-END"
    block = PULSE_DAEMON_SNIPPET.strip() + "\n"
    if begin in text and end in text:
        pre = text.split(begin, 1)[0].rstrip()
        post = text.split(end, 1)[1].lstrip("\n")
        nxt = pre + "\n\n" + block + ("\n" + post if post else "")
    elif "GIGAWATT-AUDIO" in text:
        # Older single-marker append from V2.1.2 — replace from that comment on.
        idx = text.find("# GIGAWATT-AUDIO")
        nxt = text[:idx].rstrip() + "\n\n" + block
    else:
        nxt = text.rstrip() + "\n\n" + block
    if nxt == text:
        return True
    try:
        tmp = path + ".gigawatt.tmp"
        with open(tmp, "w") as fh:
            fh.write(nxt)
            if not nxt.endswith("\n"):
                fh.write("\n")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def prepare_toslink_for_airplay():
    """Hold the 96 kHz SPDIF sink up and unsuspend it for an AirPlay session."""
    _relax_pulse_idle()
    env = _pulse_env()
    for args in (
        ["pactl", "suspend-sink", "@DEFAULT_SINK@", "0"],
        ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
    ):
        try:
            subprocess.call(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                env=env,
            )
        except Exception:
            pass


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
        from peers import identity, stamp
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
    for path in ("/run/pulse/native", "/var/run/pulse/native"):
        if os.path.exists(path):
            return path
    return "/run/pulse/native"


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
    def __init__(self, directory, on_begin=None, name=None):
        self.directory = directory
        self.on_begin = on_begin
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
        prepare_toslink_for_airplay()
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
        threading.Thread(target=self._meta_loop, daemon=True).start()
        return True

    def _stop_locked(self):
        proc = self.proc
        self.proc = None
        self.active = False
        self.title = ""
        self.artist = ""
        self.album = ""
        self.client = ""
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
        with self.lock:
            if key == "ssnc.pbeg":
                self.active = True
                begin = True
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
        if begin and self.on_begin:
            try:
                self.on_begin()
            except Exception:
                pass
