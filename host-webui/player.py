#!/usr/bin/env python3
"""TOSLINK playback on the SHR-S2: ffmpeg stereo WAV piped to paplay/Pulse."""
import json
import math
import os
import shlex
import signal
import subprocess
import threading
import time

MUSIC_DIR = os.environ.get("MUSIC_DIR", "/data/music")
PULSE_SINK = os.environ.get("PULSE_SINK", "@DEFAULT_SINK@")
FFMPEG_LOG = os.environ.get("FFMPEG_LOG", "/tmp/crypt-ffmpeg.log")
PROGRESS_FILE = os.environ.get("PROGRESS_FILE", "/tmp/crypt-ff.progress")
CLOCK_FILE = os.environ.get("CLOCK_FILE", "/data/crypt/clock.json")
# DualLite is happier at 48 kHz; Pulse resamples onto the 96 kHz S/PDIF sink.
RATE = os.environ.get("CRYPT_RATE", "48000")
# paplay WAV-on-stdin prebuffers seconds; raw PCM + this latency is the pause window.
try:
    LATENCY_MS = str(max(40, min(250, int(os.environ.get("CRYPT_LATENCY_MS", "90")))))
except ValueError:
    LATENCY_MS = "90"
# imx-spdif ALSA buffer is ~200 ms; paplay's 90 ms request is only the stream target.
try:
    CLOCK_PAD_MS = max(0, min(400, int(os.environ.get("CRYPT_CLOCK_PAD_MS", "270"))))
except ValueError:
    CLOCK_PAD_MS = 270
# AFC-style PLL: fast capture, then hold. Pulse latency is a noisy 10 MHz analog.
try:
    PLL_CAPTURE = max(0.05, min(0.5, float(os.environ.get("CRYPT_PLL_CAPTURE", "0.28"))))
except ValueError:
    PLL_CAPTURE = 0.28
try:
    PLL_HOLD = max(0.01, min(0.2, float(os.environ.get("CRYPT_PLL_HOLD", "0.045"))))
except ValueError:
    PLL_HOLD = 0.045
# Constant-Q 1/3-octave graphic EQ (ISO 266 / IEC 61260). Q = 1 / (2^(1/6)-2^(-1/6)).
EQ_Q = 4.318
EQ_FREQS = (
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500,
    630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000,
    10000, 12500, 16000, 20000,
)
EQ_LABELS = (
    "20", "25", "31.5", "40", "50", "63", "80", "100", "125", "160", "200",
    "250", "315", "400", "500", "630", "800", "1k", "1.25k", "1.6k", "2k",
    "2.5k", "3.15k", "4k", "5k", "6.3k", "8k", "10k", "12.5k", "16k", "20k",
)
EQ_BANDS = tuple(("peaking", freq, label) for freq, label in zip(EQ_FREQS, EQ_LABELS))
# V1.1.4 and earlier: 10-band Gigawatt-style shelf/peak/shelf.
EQ_LEGACY_FREQS = (32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)


def eq_region(freq):
    if freq < 90:
        return "bass"
    if freq < 350:
        return "lowmid"
    if freq < 1400:
        return "mid"
    if freq < 5500:
        return "presence"
    return "air"


def _clamp_gain(value):
    try:
        return max(-12.0, min(12.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _interp_log(freqs, gains, freq):
    if freq <= freqs[0]:
        return gains[0]
    if freq >= freqs[-1]:
        return gains[-1]
    target = math.log(freq)
    for i in range(len(freqs) - 1):
        lo, hi = freqs[i], freqs[i + 1]
        if lo <= freq <= hi:
            span = math.log(hi) - math.log(lo)
            if span <= 0:
                return gains[i]
            t = (target - math.log(lo)) / span
            return gains[i] + t * (gains[i + 1] - gains[i])
    return 0.0


def expand_eq(values, src_freqs=None):
    """Map a saved curve onto the 31 ISO bands. 10-band files are interpolated."""
    n = len(EQ_BANDS)
    if not isinstance(values, (list, tuple)):
        return [0.0] * n
    src = [_clamp_gain(v) for v in values]
    if len(src) == n:
        return src
    freqs = src_freqs
    if freqs is None:
        if len(src) == len(EQ_LEGACY_FREQS):
            freqs = EQ_LEGACY_FREQS
        else:
            out = [0.0] * n
            for i in range(min(n, len(src))):
                out[i] = src[i]
            return out
    return [_clamp_gain(round(_interp_log(freqs, src, freq) * 2.0) / 2.0) for freq in EQ_FREQS]


def clamp_eq(values):
    return expand_eq(values)


EQ_PRESETS = (
    {
        "id": "flat",
        "name": "Flat",
        "blurb": "No boost or cut. Use this, then notch a single 1/3-octave band to kill a room mode or mains hum.",
        "gains": [0.0] * 31,
    },
    {
        "id": "harman",
        "name": "Harman",
        "blurb": "Harman loudspeaker target (Olive 2013 in-room): bass shelf below ~100 Hz, then a gentle downward tilt through the treble. 31-band 1/3-octave fit, 1 kHz at 0 dB.",
        "gains": [6.5, 6.5, 6.5, 6.5, 6.0, 6.0, 5.5, 4.5, 4.0, 3.0, 2.5, 1.5, 1.0, 1.0, 0.5, 0.5, 0.0, 0.0, 0.0, -0.5, -0.5, -1.0, -2.0, -2.5, -3.0, -3.5, -4.0, -4.5, -5.5, -6.0, -6.0],
    },
    {
        "id": "bk1974",
        "name": "B&K 1974",
        "blurb": "Brüel & Kjær 1974 hi-fi room curve: fairly level bass into the lower mids, then a slow roll-off toward the top. 31-band 1/3-octave fit, 1 kHz at 0 dB.",
        "gains": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 1.5, 1.5, 1.0, 1.0, 0.5, 0.5, 0.5, 0.0, 0.0, -0.5, -0.5, -1.0, -1.0, -1.5, -1.5, -2.0, -2.0, -2.5, -3.0, -3.5, -4.0, -4.0],
    },
    {
        "id": "hifi",
        "name": "Optimum HiFi",
        "blurb": "Classic “optimum hi-fi” house curve: mild bass lift, a presence dip around 2–4 kHz, and easier treble. 31-band 1/3-octave fit, 1 kHz at 0 dB.",
        "gains": [3.0, 3.0, 3.0, 3.0, 2.5, 2.5, 2.0, 2.0, 1.5, 1.0, 1.0, 0.5, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, -0.5, -1.0, -1.5, -1.5, -2.0, -2.0, -1.5, -1.5, -1.0, -1.5, -2.0, -2.5, -2.5],
    },
    {
        "id": "nad",
        "name": "NAD / Bluesound",
        "blurb": "NAD / Bluesound house target: punch around 30–60 Hz, less deep rumble than a full bass shelf, warmer and steeper highs than Harman. 31-band 1/3-octave fit, 1 kHz at 0 dB.",
        "gains": [3.0, 4.5, 5.5, 5.5, 5.0, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0, 1.0, 0.5, 0.5, 0.0, 0.0, 0.0, -0.5, -1.0, -1.0, -2.0, -2.5, -3.0, -3.5, -4.5, -5.0, -6.0, -6.5, -7.5, -8.0],
    },
)


def ffmpeg_eq_filter(gains):
    """31-band 1/3-octave peaking EQ on TOSLINK. Zero bands are omitted."""
    gains = clamp_eq(gains)
    parts = []
    for (kind, freq, _label), gain in zip(EQ_BANDS, gains):
        if abs(gain) < 0.05:
            continue
        if kind == "lowshelf":
            parts.append("lowshelf=f=%s:t=q:w=%s:g=%.2f" % (freq, EQ_Q, gain))
        elif kind == "highshelf":
            parts.append("highshelf=f=%s:t=q:w=%s:g=%.2f" % (freq, EQ_Q, gain))
        else:
            parts.append("equalizer=f=%s:t=q:w=%s:g=%.2f" % (freq, EQ_Q, gain))
    return ",".join(parts)


def _cmd(args):
    try:
        return subprocess.check_output(
            args, stderr=subprocess.DEVNULL, text=True, timeout=1.2
        ).strip()
    except Exception:
        return ""


def _paplay_ms():
    try:
        return int(LATENCY_MS)
    except (TypeError, ValueError):
        return 90


def _word_rate():
    try:
        rate = int(RATE)
    except (TypeError, ValueError):
        return 48000
    return rate if rate > 0 else 48000


def _samples(sec, rate=None):
    rate = int(rate or _word_rate())
    return int(round(max(0.0, float(sec or 0.0)) * rate))


def new_pll_state(lat_ms, buf_ms=0.0, sink_ms=0.0):
    """Disciplined path-delay estimator. Rubidium analog: hold a stable reference."""
    return {
        "lat_ms": float(lat_ms or 0.0),
        "buf_ms": float(buf_ms or 0.0),
        "sink_ms": float(sink_ms or 0.0),
        "jitter_ms": 0.0,
        "n": 0,
        "locked": False,
        "accepted": True,
    }


def discipline_latency(state, sample, capture=PLL_CAPTURE, hold=PLL_HOLD):
    """
    4th-gen AFC analog: do not follow instantaneous Pulse jitter.
    Capture quickly, then oven-hold. Reject outliers once locked.
    """
    buf = float(sample.get("buffer_ms") or 0.0)
    sink = float(sample.get("sink_ms") or 0.0)
    total = float(sample.get("latency_ms") or (buf + sink))
    if total < 20 or total > 1200:
        state["accepted"] = False
        return state
    err = total - state["lat_ms"]
    jitter = state["jitter_ms"] or 0.0
    locked = bool(state["locked"])
    gate = max(18.0, jitter * 3.0 if jitter > 0.4 else 48.0)
    if locked and abs(err) > gate:
        state["accepted"] = False
        state["jitter_ms"] = jitter * 0.92 + abs(err) * 0.08
        return state
    alpha = hold if locked else capture
    state["lat_ms"] = state["lat_ms"] * (1.0 - alpha) + total * alpha
    state["buf_ms"] = buf
    state["sink_ms"] = sink
    state["n"] = int(state.get("n") or 0) + 1
    state["jitter_ms"] = jitter * 0.78 + abs(err) * 0.22
    if (not locked) and state["n"] >= 6 and state["jitter_ms"] < 8.0:
        state["locked"] = True
    elif locked and state["jitter_ms"] > 22.0:
        state["locked"] = False
        state["n"] = 3
    state["accepted"] = True
    return state


# Soft ahead-slew. Tens of ms is the Unison success band.
# V1.1.12 SIGSTOP'd the full 18–80 ms lead (≤80 ms) every 0.4 s — robotic
# when Quad sits ahead of DualLite. Hold a slight lead; bleed a larger
# one with a short pause. Catch-seek is behind-only: ahead catch was the
# #56 ~400 ms paplay restart (hallway slap).
FOLLOW_AHEAD_S = 0.05
SLEW_MAX_S = 0.024
SLEW_FRAC = 0.4
SLEW_MIN_S = 0.008
SLEW_COOL_S = 1.2


def follow_plan(
    local_heard,
    target_heard,
    hold_s=0.018,
    ahead_s=FOLLOW_AHEAD_S,
    catch_s=0.12,
    jump_s=1.25,
    warming=False,
    last_seek_age=999.0,
    good_age=999.0,
    catch_age=8.0,
):
    """How to keep this TOSLINK on another host's heard clock.

    Seek restarts ffmpeg+paplay and unlocks the latency PLL (~400 ms path).
    Jump only for a real discontinuity. Catch-up seek only when this jack
    is *behind*. Local slightly ahead holds; larger lead slews. Do not
    catch-seek an ahead error — that was the #56 slap.
    """
    try:
        err = float(target_heard) - float(local_heard)
    except (TypeError, ValueError):
        return "hold", 0.0
    if warming:
        return "hold", err
    if abs(err) < hold_s:
        return "hold", err
    if abs(err) >= jump_s and last_seek_age >= 2.0:
        return "seek", err
    if err >= catch_s and last_seek_age >= 2.0 and good_age >= catch_age:
        return "seek", err
    if err <= -ahead_s:
        return "slew", err
    return "hold", err


def slew_ahead_seconds(err, max_s=SLEW_MAX_S, frac=SLEW_FRAC, min_s=SLEW_MIN_S):
    """How long to SIGSTOP when follow_plan says slew. Not the full lead."""
    try:
        lead = abs(float(err))
    except (TypeError, ValueError):
        return 0.0
    seconds = min(max_s, lead * frac)
    if seconds < min_s:
        return 0.0
    return seconds


def discipline_decoder(corr, mono_s, ref_s, alpha=0.12, snap_s=0.35):
    """Steer the monotonic oscillator toward ffmpeg out_time without steps."""
    if ref_s is None:
        return corr
    err = float(ref_s) - (float(mono_s) + float(corr or 0.0))
    if abs(err) > snap_s:
        return corr + err
    return (corr or 0.0) + err * alpha


def _read_out_time_s(path=PROGRESS_FILE):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > 2048:
                fh.seek(size - 2048)
            data = fh.read()
    except OSError:
        return None
    us = None
    ms = None
    for raw in data.decode("ascii", "ignore").splitlines():
        if raw.startswith("out_time_us="):
            try:
                val = int(raw.split("=", 1)[1].strip())
            except ValueError:
                continue
            if val >= 0:
                us = val
        elif raw.startswith("out_time_ms="):
            try:
                val = int(raw.split("=", 1)[1].strip())
            except ValueError:
                continue
            if val >= 0:
                ms = val
    if us is not None:
        return us / 1000000.0
    if ms is not None:
        return ms / 1000.0
    return None


def _usec_field(line, prefix):
    if not line.startswith(prefix):
        return None
    parts = line.split()
    for i, part in enumerate(parts):
        if part.isdigit() and i + 1 < len(parts) and parts[i + 1].startswith("usec"):
            try:
                return int(part)
            except ValueError:
                return None
    return None


def _read_crypt_latency():
    """Pulse stream latency for the CRYPT paplay client, in milliseconds."""
    text = _cmd(["pactl", "list", "sink-inputs"])
    if not text:
        return None
    name = ""
    buf_usec = None
    sink_usec = None
    found = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Sink Input #"):
            if name == "CRYPT" and buf_usec is not None:
                found = (buf_usec, sink_usec or 0)
            name = ""
            buf_usec = None
            sink_usec = None
            continue
        if line.startswith("application.name"):
            _, _, val = line.partition("=")
            name = val.strip().strip('"')
            continue
        usec = _usec_field(line, "Buffer Latency:")
        if usec is not None:
            buf_usec = usec
            continue
        usec = _usec_field(line, "Sink Latency:")
        if usec is not None:
            sink_usec = usec
    if name == "CRYPT" and buf_usec is not None:
        found = (buf_usec, sink_usec or 0)
    if not found:
        return None
    buf_ms = max(0, found[0] / 1000.0)
    sink_ms = max(0, found[1] / 1000.0)
    total = buf_ms + sink_ms
    # paplay still priming or tearing down reports 0 buffer; ignore those.
    if buf_ms < 40 or sink_ms < 10 or total < 60 or total > 1200:
        return None
    return {"buffer_ms": buf_ms, "sink_ms": sink_ms, "latency_ms": total}


def _load_clock_file():
    try:
        with open(CLOCK_FILE, "r") as fh:
            data = json.load(fh)
        lat = float(data.get("latency_ms") or 0)
        buf = float(data.get("buffer_ms") or 0)
        sink = float(data.get("sink_ms") or 0)
        if lat < 60 or lat > 1200 or buf < 40:
            return None
        return {
            "latency_ms": lat,
            "buffer_ms": buf,
            "sink_ms": sink,
            "jitter_ms": float(data.get("jitter_ms") or 0),
        }
    except Exception:
        return None


def _save_clock_file(data):
    try:
        folder = os.path.dirname(CLOCK_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = CLOCK_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, CLOCK_FILE)
    except OSError:
        pass


class HostPlayer(object):
    def __init__(self, on_end=None):
        self.on_end = on_end
        self.lock = threading.Lock()
        self.proc = None
        self.name = ""
        self.media = ""
        self.paused = False
        self.t0 = 0.0
        self.offset = 0.0
        self.hold = 0.0
        self.duration = 0.0
        self.error = ""
        self.generation = 0
        self.eq = [0.0] * len(EQ_BANDS)
        self._eq_timer = None
        self._vol_lock = threading.Lock()
        self._vol_cv = threading.Condition(self._vol_lock)
        self._vol = self._read_sink_volume()
        self._vol_target = self._vol
        self._muted = False
        self._clock_init()
        self._set_mute(False)
        threading.Thread(target=self._watch, daemon=True).start()
        threading.Thread(target=self._vol_loop, name="vol-fade", daemon=True).start()
        threading.Thread(target=self._clock_loop, name="time-clock", daemon=True).start()

    def snapshot(self):
        with self.lock:
            alive = self._alive_locked()
            playback = self._position_locked()
            clock = self._clock_locked(playback)
            return {
                "playing": bool(alive and not self.paused),
                "paused": bool(self.paused and alive),
                "name": self.name,
                "position": clock["heard"],
                "playback": clock["playback"],
                "duration": round(self.duration or 0.0, 3),
                "error": self.error,
                "eq": list(self.eq),
                "clock": clock,
            }

    def play(self, relname, start=0.0):
        base = os.path.realpath(MUSIC_DIR)
        full = os.path.realpath(os.path.join(base, relname.replace("\\", "/").lstrip("/")))
        if full != base and not full.startswith(base + os.sep):
            self.error = "not found"
            return False
        if not os.path.isfile(full):
            self.error = "not found"
            return False
        try:
            start = float(start or 0.0)
        except (TypeError, ValueError):
            start = 0.0
        if start < 0:
            start = 0.0
        with self.lock:
            self.name = os.path.relpath(full, base).replace("\\", "/")
            self.media = full
            self.duration = self._probe(full)
            if self.duration and start >= max(0.0, self.duration - 0.2):
                start = 0.0
            return self._play_locked(full, start)

    def pause(self):
        with self.lock:
            return self._pause_locked()

    def _pause_locked(self):
        if not self._alive_locked():
            self.error = "nothing playing"
            return False
        if self.paused:
            return True
        self.hold = self._position_locked()
        self._play_corr = 0.0
        self._set_mute(True)
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGSTOP)
        except Exception as exc:
            self._set_mute(False)
            self.error = str(exc)
            return False
        self.paused = True
        self.error = ""
        return True

    def resume(self):
        with self.lock:
            if not self._alive_locked():
                self.error = "nothing playing"
                return False
            if not self.paused:
                return True
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGCONT)
            except Exception as exc:
                self.error = str(exc)
                return False
            self.t0 = time.monotonic() - (self.hold - self.offset)
            self._play_corr = 0.0
            self.paused = False
            self.error = ""
            self._set_mute(False)
            return True

    def stop(self):
        with self.lock:
            self._stop_locked()
            self.name = ""
            self.media = ""
            self.duration = 0.0
            self.error = ""
            return True

    def follow_heard(self, target_heard):
        """Steer this chassis toward another host's heard position."""
        snap = self.snapshot()
        if not snap.get("playing"):
            return False
        clock = snap.get("clock") or {}
        local = clock.get("heard")
        if local is None:
            return False
        now = time.monotonic()
        lat = float(clock.get("latency_ms") or 90.0) / 1000.0
        warming = now < float(self._sync_warm_until or 0.0)
        plan, err = follow_plan(
            local,
            target_heard,
            warming=warming,
            last_seek_age=now - float(self._sync_seek_at or 0.0),
            good_age=now - float(self._sync_good_at or 0.0),
        )
        if plan == "hold":
            if abs(err) < 0.018:
                self._sync_good_at = now
            return True
        if plan == "slew":
            now2 = time.monotonic()
            if now2 - float(self._sync_slew_at or 0.0) < SLEW_COOL_S:
                return True
            if self._sync_slewing:
                return True
            seconds = slew_ahead_seconds(err)
            if seconds < SLEW_MIN_S:
                return True
            self._sync_slew_at = now2
            gen = self.generation
            threading.Thread(
                target=self._slew_ahead,
                args=(seconds, gen),
                daemon=True,
                name="unison-slew",
            ).start()
            return True
        if plan == "seek":
            self._sync_seek_at = now
            self._sync_good_at = now
            return self.seek(max(0.0, float(target_heard) + lat))
        return True

    def _slew_ahead(self, seconds, gen=None):
        """Local optical is ahead: pause the pipe briefly. Do not restart ffmpeg."""
        seconds = max(0.0, min(SLEW_MAX_S, float(seconds or 0.0)))
        if seconds < SLEW_MIN_S:
            return True
        self._sync_slewing = True
        try:
            with self.lock:
                if gen is not None and gen != self.generation:
                    return True
                if self.paused or not self._alive_locked() or self.proc is None:
                    return True
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGSTOP)
                except Exception:
                    return False
            time.sleep(seconds)
            with self.lock:
                if gen is not None and gen != self.generation:
                    return True
                if self.proc is None or self.paused:
                    return True
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGCONT)
                except Exception:
                    return False
                self.t0 += seconds
            return True
        finally:
            self._sync_slewing = False

    def seek(self, seconds):
        with self.lock:
            if not self.media:
                self.error = "nothing playing"
                return False
            try:
                pos = float(seconds)
            except (TypeError, ValueError):
                self.error = "bad seek"
                return False
            if pos < 0:
                pos = 0.0
            if self.duration > 0:
                pos = min(pos, max(0.0, self.duration - 0.15))
            return self._play_locked(self.media, pos)

    def set_eq(self, gains):
        next_eq = clamp_eq(gains)
        with self.lock:
            same = self.eq == next_eq
            self.eq = next_eq
            if self._eq_timer is not None:
                try:
                    self._eq_timer.cancel()
                except Exception:
                    pass
                self._eq_timer = None
            if same or not self.media:
                return True
            if not self._alive_locked() and not self.paused:
                return True
            timer = threading.Timer(0.4, self._apply_eq_now)
            timer.daemon = True
            self._eq_timer = timer
            timer.start()
        return True

    def _apply_eq_now(self):
        with self.lock:
            self._eq_timer = None
            if not self.media:
                return
            if not self._alive_locked() and not self.paused:
                return
            pos = self._position_locked()
            paused = self.paused
            ok = self._play_locked(self.media, pos)
            if ok and paused:
                self._pause_locked()

    def set_volume(self, n):
        try:
            n = int(round(float(n)))
        except (TypeError, ValueError):
            return False
        n = max(0, min(100, n))
        with self._vol_cv:
            self._vol_target = n
            self._vol_cv.notify()
        return True

    def volume(self):
        with self._vol_lock:
            return int(self._vol_target)

    def _read_sink_volume(self):
        out = _cmd(["pactl", "get-sink-volume", PULSE_SINK])
        for part in out.replace("/", " ").split():
            if part.endswith("%"):
                try:
                    return max(0, min(100, int(part[:-1])))
                except ValueError:
                    pass
        return 100

    def _apply_vol(self, n):
        _cmd(["pactl", "set-sink-volume", PULSE_SINK, "%s%%" % int(n)])

    def _set_mute(self, mute):
        _cmd(["pactl", "set-sink-mute", PULSE_SINK, "1" if mute else "0"])
        self._muted = bool(mute)

    def _vol_loop(self):
        while True:
            with self._vol_cv:
                while self._vol == self._vol_target:
                    self._vol_cv.wait(timeout=0.4)
                target = self._vol_target
                cur = self._vol
            if cur == target:
                continue
            delta = target - cur
            step = int(round(delta * 0.38))
            if step == 0:
                step = 1 if delta > 0 else -1
            nxt = cur + step
            if (delta > 0 and nxt > target) or (delta < 0 and nxt < target):
                nxt = target
            self._apply_vol(nxt)
            with self._vol_lock:
                self._vol = nxt
            time.sleep(0.018)

    def _alive_locked(self):
        return self.proc is not None and self.proc.poll() is None

    def _clock_init(self):
        saved = _load_clock_file()
        default = float(_paplay_ms() + CLOCK_PAD_MS)
        if saved:
            lat = saved["latency_ms"]
            buf = saved.get("buffer_ms") or 0.0
            sink = saved.get("sink_ms") or 0.0
            jitter = saved.get("jitter_ms") or 0.0
        else:
            lat = default
            buf = float(_paplay_ms())
            sink = float(CLOCK_PAD_MS)
            jitter = 0.0
        self._pll = new_pll_state(lat, buf, sink)
        self._pll["jitter_ms"] = float(jitter or 0.0)
        self._pll["locked"] = bool(saved)
        self._lat_ms = self._pll["lat_ms"]
        self._buf_ms = self._pll["buf_ms"]
        self._sink_ms = self._pll["sink_ms"]
        self._clock_on = False
        self._clock_saved = 0.0
        self._play_corr = 0.0
        self._ppm = 0.0
        self._ref_age = 0.0
        self._sync_seek_at = 0.0
        self._sync_warm_until = 0.0
        self._sync_slew_at = 0.0
        self._sync_slewing = False
        self._sync_good_at = 0.0

    def _mono_locked(self):
        if self.paused or not self._alive_locked():
            return self.hold
        return self.offset + (time.monotonic() - self.t0)

    def _position_locked(self):
        pos = self._mono_locked() + (self._play_corr or 0.0)
        if self.duration > 0:
            pos = min(pos, self.duration)
        return max(0.0, pos)

    def _clock_locked(self, playback):
        playback = max(0.0, playback or 0.0)
        lat_s = max(0.0, (self._pll["lat_ms"] or 0.0) / 1000.0)
        heard = max(self.offset if self.media else 0.0, playback - lat_s)
        if self.duration > 0:
            heard = min(heard, self.duration)
            playback = min(playback, self.duration)
        heard = max(0.0, heard)
        offset_ms = max(0.0, (playback - heard) * 1000.0)
        rate = _word_rate()
        jitter = float(self._pll.get("jitter_ms") or 0.0)
        locked = bool(
            self._clock_on
            and self._pll.get("locked")
            and self._alive_locked()
            and not self.paused
        )
        if not self.media:
            phase = "idle"
        elif self.paused or not self._alive_locked():
            phase = "frozen"
        elif not self._clock_on:
            phase = "warmup"
        elif not self._pll.get("locked"):
            phase = "locking"
        else:
            phase = "locked"
        return {
            "heard": round(heard, 6),
            "playback": round(playback, 6),
            "heard_samples": _samples(heard, rate),
            "playback_samples": _samples(playback, rate),
            "offset_ms": int(round(offset_ms)),
            "latency_ms": round(self._pll["lat_ms"], 2),
            "buffer_ms": round(self._pll["buf_ms"], 2),
            "sink_ms": round(self._pll["sink_ms"], 2),
            "paplay_ms": _paplay_ms(),
            "drift_ms": int(round(self._pll["lat_ms"] - float(_paplay_ms()))),
            "jitter_ms": round(jitter, 3),
            "ppm": round(self._ppm, 3),
            "locked": locked,
            "phase": phase,
            "rate": rate,
            "warming": bool(time.monotonic() < float(self._sync_warm_until or 0.0)),
        }

    def _apply_latency_sample(self, sample):
        discipline_latency(self._pll, sample)
        self._lat_ms = self._pll["lat_ms"]
        self._buf_ms = self._pll["buf_ms"]
        self._sink_ms = self._pll["sink_ms"]
        if not self._pll.get("accepted"):
            return
        self._clock_on = True
        now = time.monotonic()
        if self._pll["buf_ms"] >= 40 and now - self._clock_saved >= 8.0:
            self._clock_saved = now
            _save_clock_file({
                "latency_ms": round(self._pll["lat_ms"], 2),
                "buffer_ms": round(self._pll["buf_ms"], 2),
                "sink_ms": round(self._pll["sink_ms"], 2),
                "jitter_ms": round(self._pll["jitter_ms"], 3),
            })

    def _steer_decoder_locked(self):
        if self.paused or not self._alive_locked():
            return
        mono = self.offset + (time.monotonic() - self.t0)
        ref = _read_out_time_s()
        if ref is None:
            return
        self._play_corr = discipline_decoder(self._play_corr, mono, self.offset + ref)
        wall = max(0.25, time.monotonic() - self.t0)
        if wall >= 1.5 and ref > 0.2:
            self._ppm = ((ref / wall) - 1.0) * 1e6
            if self._ppm > 5000 or self._ppm < -5000:
                self._ppm = 0.0
        self._ref_age = time.monotonic()

    def _probe(self, path):
        out = _cmd(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ]
        )
        try:
            dur = float(out)
            return dur if dur > 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _stop_locked(self):
        proc = self.proc
        self.proc = None
        self.paused = False
        self.offset = 0.0
        self.hold = 0.0
        self.t0 = time.monotonic()
        self.generation += 1
        self._set_mute(False)
        self._play_corr = 0.0
        self._ppm = 0.0
        self._clock_on = False
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _play_locked(self, path, start):
        self._stop_locked()
        self.media = path
        ss = "-ss %.3f " % start if start > 0.04 else ""
        af = ffmpeg_eq_filter(self.eq)
        extra = ("-af %s " % shlex.quote(af)) if af else ""
        try:
            open(FFMPEG_LOG, "w").close()
        except OSError:
            pass
        try:
            open(PROGRESS_FILE, "w").close()
        except OSError:
            pass
        cmd = (
            "ffmpeg -nostdin -hide_banner -nostats -loglevel error "
            "-progress %s -fflags +nobuffer %s-i %s -ac 2 -ar %s %s-f s16le - 2>>%s "
            "| paplay --device=%s --raw --format=s16le --rate=%s --channels=2 "
            "--latency-msec=%s --process-time-msec=20 --client-name=CRYPT"
            % (
                shlex.quote(PROGRESS_FILE),
                ss,
                shlex.quote(path),
                shlex.quote(RATE),
                extra,
                shlex.quote(FFMPEG_LOG),
                shlex.quote(PULSE_SINK),
                shlex.quote(RATE),
                shlex.quote(str(int(LATENCY_MS))),
            )
        )
        try:
            self.proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
        except Exception as exc:
            self.error = str(exc)
            self.proc = None
            return False
        self.offset = start
        self.hold = start
        self.t0 = time.monotonic()
        self.paused = False
        self._play_corr = 0.0
        self._ppm = 0.0
        self._clock_on = False
        lat_s = max(0.15, (self._pll["lat_ms"] or 400.0) / 1000.0)
        self._sync_warm_until = self.t0 + lat_s + 0.12
        self.error = ""
        return True

    def _watch(self):
        last = -1
        while True:
            time.sleep(0.4)
            ended = False
            gen = 0
            with self.lock:
                if self.proc is not None and self.proc.poll() is not None and not self.paused:
                    if self.generation != last:
                        ended = True
                        gen = self.generation
                        self.proc = None
                        self.hold = self.duration or self._position_locked()
                        self._clock_on = False
            if ended:
                last = gen
                if self.on_end:
                    try:
                        self.on_end()
                    except Exception:
                        pass

    def _clock_loop(self):
        while True:
            playing = False
            locked = False
            with self.lock:
                playing = bool(self._alive_locked() and not self.paused)
                locked = bool(self._pll.get("locked") and self._clock_on)
            if not playing:
                time.sleep(0.4)
                continue
            with self.lock:
                if self._alive_locked() and not self.paused:
                    self._steer_decoder_locked()
            sample = _read_crypt_latency()
            if sample:
                with self.lock:
                    if self._alive_locked() and not self.paused:
                        self._apply_latency_sample(sample)
            time.sleep(0.22 if not locked else 1.0)
