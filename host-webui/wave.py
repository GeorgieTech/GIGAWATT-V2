#!/usr/bin/env python3
"""Precompute Rekordbox-style 3-band waveforms (low / mid / high)."""
from __future__ import print_function

import hashlib
import json
import os
import select
import struct
import subprocess
import threading
import time

from player import MUSIC_DIR

WAVE_DIR = os.environ.get("CRYPT_WAVES", "/data/crypt/waves")
WAVE_VER = 4
# 80 Hz columns. Envelope is computed at 22.05 kHz, so DualLite cost is the
# filter graph, not this rate. 80 was too heavy when aresample ran on raw PCM.
RATE = 80
MAX_FRAMES = 28800
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")
# percentile, gamma, gain, gate. Highs stay peak-referenced so hiss is not hats.
SCALE_LOW = (0.95, 0.68, 1.00, 0.03)
SCALE_MID = (0.94, 0.70, 1.00, 0.03)
SCALE_HIGH = (0.99, 0.72, 0.90, 0.04)

def _lower_nice():
    try:
        os.nice(8)
    except Exception:
        pass


# Envelope each band at full rate, then downsample. aresample-to-RATE of the
# raw 6–12 kHz band is a ~20 Hz lowpass, so highs (and most mids) vanished.
_FILTER = (
    "[0:a]aformat=channel_layouts=mono:sample_fmts=flt,aresample=22050,asplit=3[l0][m0][h0];"
    "[l0]lowpass=f=250,lowpass=f=250,aeval=abs(val(0)):c=same,lowpass=f=18[l];"
    "[m0]highpass=f=250,lowpass=f=4000,lowpass=f=4000,aeval=abs(val(0)):c=same,lowpass=f=18[m];"
    "[h0]highpass=f=4000,highpass=f=4000,aeval=abs(val(0)):c=same,lowpass=f=18[h];"
    "[l][m][h]join=inputs=3:channel_layout=3.0:map=0.0-FL|1.0-FR|2.0-FC,aresample=%d[a]"
) % RATE


def _full_path(rel):
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return None
    base = os.path.realpath(MUSIC_DIR)
    full = os.path.realpath(os.path.join(base, rel))
    if full == base or not full.startswith(base + os.sep):
        return None
    if not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in AUDIO_EXT:
        return None
    return full


def _stat(full):
    try:
        st = os.stat(full)
        return int(st.st_size), int(st.st_mtime)
    except OSError:
        return 0, 0


def _cache_path(rel, size, mtime):
    key = "%s|%s|%s|v%s" % (rel, size, mtime, WAVE_VER)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return os.path.join(WAVE_DIR, digest + ".json")


def _smooth(vals, passes=2):
    if len(vals) < 3:
        return list(vals)
    cur = list(vals)
    for _ in range(passes):
        nxt = list(cur)
        for i in range(1, len(cur) - 1):
            nxt[i] = (cur[i - 1] + cur[i] * 2.0 + cur[i + 1]) * 0.25
        cur = nxt
    return cur


def _scale_band(vals, percentile=0.96, gamma=0.72, gain=1.0, gate=0.05):
    if not vals:
        return []
    ordered = sorted(vals)
    idx = int(len(ordered) * percentile)
    if idx >= len(ordered):
        idx = len(ordered) - 1
    peak = ordered[idx] or 0.000001
    out = []
    for v in vals:
        x = (v / peak) * gain
        if x > 1.0:
            x = 1.0
        if x < gate:
            x = 0.0
        elif gate > 0:
            x = (x - gate) / (1.0 - gate)
        if x < 0.0:
            x = 0.0
        out.append(int(round((x ** gamma) * 255.0)))
    return out


def _onset(lows):
    n = len(lows)
    out = [0.0] * n
    for i in range(2, n):
        d = lows[i] - lows[i - 2]
        if d > 0.0:
            out[i] = d
    return out


def _autocorr_lag(onset, min_lag, max_lag):
    n = len(onset)
    scores = []
    best = -1.0
    best_lag = min_lag
    for lag in range(min_lag, max_lag + 1):
        s = 0.0
        i = lag
        while i < n:
            s += onset[i] * onset[i - lag]
            i += 1
        scores.append(s)
        if s > best:
            best = s
            best_lag = lag
    return best_lag, best, scores


def _prefer_dance_tempo(lag, rate, scores, min_lag, max_lag):
    def score_at(period):
        idx = period - min_lag
        if 0 <= idx < len(scores):
            return scores[idx]
        return 0.0

    bpm = 60.0 * rate / float(lag or 1)
    half = int(round(lag / 2.0))
    if bpm < 78 and min_lag <= half <= max_lag:
        if score_at(half) >= score_at(lag) * 0.62:
            lag = half
            bpm = 60.0 * rate / float(lag)
    dbl = lag * 2
    if bpm > 168 and min_lag <= dbl <= max_lag:
        if score_at(dbl) >= score_at(lag) * 0.52:
            lag = dbl
            bpm = 60.0 * rate / float(lag)
    return lag, bpm


def _best_phase(onset, lows, lag):
    best_off = 0
    best = -1.0
    n = len(onset)
    for off in range(max(1, lag)):
        s = 0.0
        c = 0
        k = off
        while k < n:
            s += onset[k] + 0.28 * lows[k]
            c += 1
            k += lag
        s /= float(c or 1)
        if s > best:
            best = s
            best_off = off
    return best_off


def _best_downbeat(lows, lag, off, bar=4):
    best_i = 0
    best = -1.0
    n = len(lows)
    step = lag * bar
    if step <= 0:
        return off
    for i in range(bar):
        s = 0.0
        c = 0
        k = off + i * lag
        while k < n:
            s += lows[k]
            c += 1
            k += step
        s /= float(c or 1)
        if s > best:
            best = s
            best_i = i
    return off + best_i * lag


def beat_grid(lows, rate):
    """Rekordbox-style grid: BPM + first downbeat, from the low envelope."""
    empty = {"bpm": 0.0, "beat0": 0.0, "bar": 4}
    n = len(lows or [])
    rate = float(rate or 0.0)
    if n < 32 or rate < 8:
        return empty
    min_bpm, max_bpm = 70.0, 180.0
    min_lag = max(4, int(round(60.0 * rate / max_bpm)))
    max_lag = min(n // 3, int(round(60.0 * rate / min_bpm)))
    if max_lag <= min_lag + 2:
        return empty
    onset = _onset(lows)
    if sum(onset) <= 1e-9:
        return empty
    lag, best, scores = _autocorr_lag(onset, min_lag, max_lag)
    mean = sum(scores) / float(len(scores) or 1)
    if best < mean * 1.22:
        return empty
    lag, bpm = _prefer_dance_tempo(lag, rate, scores, min_lag, max_lag)
    if bpm < 55 or bpm > 200:
        return empty
    off = _best_phase(onset, lows, lag)
    down = _best_downbeat(lows, lag, off, 4)
    return {
        "bpm": round(bpm, 2),
        "beat0": round(down / rate, 4),
        "bar": 4,
    }


def _probe_duration(full):
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                full,
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        ).strip()
        dur = float(out)
        return dur if dur > 0 else 0.0
    except Exception:
        return 0.0


def _analyze(full, on_progress=None):
    def report(pct, stage):
        if on_progress:
            try:
                on_progress(int(max(0, min(99, pct))), stage)
            except Exception:
                pass

    report(1, "Starting")
    expect = 0
    dur = _probe_duration(full)
    if dur > 0:
        expect = int(dur * RATE * 12)
        report(3, "Analyzing waveform")
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-threads",
        "1",
        "-i",
        full,
        "-filter_complex",
        _FILTER,
        "-map",
        "[a]",
        "-f",
        "f32le",
        "pipe:1",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        preexec_fn=_lower_nice,
    )
    raw = bytearray()
    deadline = time.monotonic() + 150
    t0 = time.monotonic()
    last_pct = 3
    fd = proc.stdout.fileno() if proc.stdout else None
    try:
        while time.monotonic() < deadline:
            if fd is None:
                break
            ready, _, _ = select.select([proc.stdout], [], [], 0.4)
            if not ready:
                if proc.poll() is not None:
                    rest = proc.stdout.read() or b""
                    if rest:
                        raw.extend(rest)
                    break
                elapsed = time.monotonic() - t0
                if expect <= 0:
                    guess = min(88, 4 + int(elapsed / 40.0 * 84))
                    if guess > last_pct:
                        last_pct = guess
                        report(guess, "Analyzing waveform")
                continue
            buf = os.read(fd, 12 * 4096)
            if not buf:
                break
            raw.extend(buf)
            if expect > 0:
                pct = min(96, 4 + int(len(raw) * 92 / float(expect)))
            else:
                pct = min(88, 4 + int((time.monotonic() - t0) / 40.0 * 84))
            if pct > last_pct:
                last_pct = pct
                report(pct, "Analyzing waveform")
            if len(raw) > MAX_FRAMES * 12 * 8:
                break
        timed_out = time.monotonic() >= deadline
        if proc.poll() is None:
            if timed_out:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.communicate()
                except Exception:
                    pass
            else:
                try:
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        return None
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
    if not raw:
        return None
    report(97, "Building bands")
    frame = 12
    n = len(raw) // frame
    if n < 8:
        return None
    if n > MAX_FRAMES:
        step = int((n + MAX_FRAMES - 1) / MAX_FRAMES)
    else:
        step = 1
    lows, mids, highs = [], [], []
    i = 0
    while i < n:
        chunk = min(step, n - i)
        sl = sm = sh = 0.0
        for k in range(chunk):
            off = (i + k) * frame
            l, m, h = struct.unpack_from("<fff", raw, off)
            sl += l * l
            sm += m * m
            sh += h * h
        den = float(chunk) or 1.0
        lows.append((sl / den) ** 0.5)
        mids.append((sm / den) ** 0.5)
        highs.append((sh / den) ** 0.5)
        i += step
    lows = _smooth(lows, 2)
    mids = _smooth(mids, 2)
    highs = _smooth(highs, 1)
    wave_rate = RATE / float(step)
    report(98, "Finding beat grid")
    grid = beat_grid(lows, wave_rate)
    if not dur:
        dur = len(lows) / float(wave_rate or RATE)
    return {
        "v": WAVE_VER,
        "rate": wave_rate,
        "n": len(lows),
        "dur": round(dur, 3),
        "grid": grid,
        "l": _scale_band(lows, *SCALE_LOW),
        "m": _scale_band(mids, *SCALE_MID),
        "h": _scale_band(highs, *SCALE_HIGH),
    }


class WaveIndex(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.mem = {}
        self.busy = set()
        self.queue = []
        self.error = {}
        self.progress = {}
        t = threading.Thread(target=self._loop, name="wave-scan", daemon=True)
        t.start()

    def get(self, rel):
        rel = (rel or "").replace("\\", "/").lstrip("/")
        full = _full_path(rel)
        if not full:
            return {"ok": False, "error": "not found"}
        size, mtime = _stat(full)
        path = _cache_path(rel, size, mtime)
        with self.lock:
            cached = self.mem.get(path)
        if cached:
            data = dict(cached)
            data["ok"] = True
            data["name"] = rel
            data["analyzing"] = False
            return data
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("v") == WAVE_VER and data.get("l") and data.get("m") and data.get("h"):
                with self.lock:
                    self.mem[path] = data
                out = dict(data)
                out["ok"] = True
                out["name"] = rel
                out["analyzing"] = False
                return out
        except (OSError, ValueError, TypeError):
            pass
        self.ensure(rel, front=True)
        with self.lock:
            err = self.error.get(rel)
            busy = rel in self.busy
            queued = rel in self.queue
            prog = dict(self.progress.get(rel) or {})
        if err:
            return {"ok": False, "name": rel, "analyzing": False, "error": err, "progress": 0}
        if queued and not busy:
            stage = "Waiting to analyze"
            pct = 0
        else:
            stage = prog.get("stage") or "Analyzing waveform"
            pct = int(prog.get("pct") or 0)
        return {
            "ok": False,
            "name": rel,
            "analyzing": True,
            "progress": max(0, min(99, pct)),
            "stage": stage,
        }

    def ensure(self, rel, front=False):
        rel = (rel or "").replace("\\", "/").lstrip("/")
        if not rel or not _full_path(rel):
            return
        with self.lock:
            if rel in self.busy or rel in self.queue:
                if front and rel in self.queue:
                    self.queue.remove(rel)
                    self.queue.insert(0, rel)
                return
            if front:
                self.queue.insert(0, rel)
            else:
                self.queue.append(rel)
            if rel not in self.progress:
                self.progress[rel] = {"pct": 0, "stage": "Waiting to analyze"}

    def drop_name(self, rel):
        """Remove cached waveform JSON for this library name (all analyzer versions)."""
        rel = (rel or "").replace("\\", "/").lstrip("/")
        if not rel:
            return 0
        victims = set()
        full = _full_path(rel)
        if full:
            size, mtime = _stat(full)
            if size:
                victims.add(_cache_path(rel, size, mtime))
        try:
            listing = os.listdir(WAVE_DIR)
        except OSError:
            listing = []
        for fn in listing:
            if not fn.endswith(".json"):
                continue
            path = os.path.join(WAVE_DIR, fn)
            try:
                with open(path, "r") as fh:
                    data = json.load(fh)
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get("name") == rel:
                victims.add(path)
        removed = 0
        for path in victims:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
            try:
                os.remove(path + ".tmp")
            except OSError:
                pass
        with self.lock:
            for path in list(self.mem):
                data = self.mem.get(path) or {}
                if path in victims or data.get("name") == rel:
                    self.mem.pop(path, None)
            self.error.pop(rel, None)
            self.progress.pop(rel, None)
            self.busy.discard(rel)
            self.queue = [item for item in self.queue if item != rel]
        return removed

    def _mark(self, rel, pct, stage):
        with self.lock:
            self.progress[rel] = {"pct": int(max(0, min(100, pct))), "stage": stage}

    def _loop(self):
        while True:
            with self.lock:
                rel = self.queue.pop(0) if self.queue else None
                if rel:
                    self.busy.add(rel)
            if not rel:
                time.sleep(0.4)
                continue
            try:
                self._build(rel)
            except Exception as exc:
                with self.lock:
                    self.error[rel] = str(exc)[:160]
            finally:
                with self.lock:
                    self.busy.discard(rel)

    def _build(self, rel):
        full = _full_path(rel)
        if not full:
            with self.lock:
                self.error[rel] = "not found"
            return
        size, mtime = _stat(full)
        path = _cache_path(rel, size, mtime)
        if os.path.isfile(path):
            try:
                with open(path, "r") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and data.get("v") == WAVE_VER and data.get("n"):
                    with self.lock:
                        self.mem[path] = data
                        self.error.pop(rel, None)
                    return
            except (OSError, ValueError):
                pass
        self._mark(rel, 1, "Starting")
        data = _analyze(full, lambda pct, stage: self._mark(rel, pct, stage))
        if not data:
            with self.lock:
                self.error[rel] = "analyze failed"
                self.progress.pop(rel, None)
            return
        self._mark(rel, 100, "Complete")
        data["name"] = rel
        try:
            os.makedirs(WAVE_DIR, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(data, fh, separators=(",", ":"))
            os.replace(tmp, path)
        except OSError:
            pass
        with self.lock:
            self.mem[path] = data
            self.error.pop(rel, None)


WAVES = WaveIndex()
