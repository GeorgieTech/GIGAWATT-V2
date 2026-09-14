#!/usr/bin/env python3
"""Lyrics lookup in the MusicBee / foobar2000 OpenLyrics style.

Local sidecar .lrc/.txt next to the track, then embedded tags, then optional
lrclib.net fetch (synced LRC). Karaoke timing follows Host Time Clock.
Sidecar files and /data/crypt/lyrics cache die with the track.
Python 3.8 stdlib only.
"""
from __future__ import print_function

import hashlib
import json
import os
import re
import subprocess
import threading
import time

try:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import urlencode
    from urllib2 import Request, urlopen

from player import MUSIC_DIR, NAS_DIR
from library import CATALOG, UNKNOWN_ARTIST, UNKNOWN_ALBUM, identity_from_path

LYRICS_DIR = os.environ.get("CRYPT_LYRICS", "/data/crypt/lyrics")
LRCLIB = os.environ.get("CRYPT_LRCLIB", "https://lrclib.net/api")
CLIENT = "CRYPT/2.2.35 (https://github.com/GeorgieTech/GIGAWATT-V2)"
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")

_TS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_HEAD = re.compile(r"^\[(ti|ar|al|offset):([^\]]*)\]\s*$", re.I)
_LINE = re.compile(r"^((?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+)\s*(.*)$")


def _seconds(m, s, frac):
    extra = 0.0
    if frac:
        if len(frac) == 1:
            extra = int(frac) / 10.0
        elif len(frac) == 2:
            extra = int(frac) / 100.0
        else:
            extra = int(frac[:3]) / 1000.0
    return int(m) * 60 + int(s) + extra


def _parse_stamp(match):
    return _seconds(match.group(1), match.group(2), match.group(3) or "")


def parse_lrc(text, offset_ms=0):
    """Parse LRC / enhanced LRC into karaoke lines."""
    lines = []
    meta = {"title": "", "artist": "", "album": ""}
    shift = (offset_ms or 0) / 1000.0
    if not text:
        return {"meta": meta, "lines": []}
    for raw in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        row = raw.strip()
        if not row:
            continue
        head = _HEAD.match(row)
        if head:
            key = head.group(1).lower()
            val = head.group(2).strip()
            if key == "ti":
                meta["title"] = val
            elif key == "ar":
                meta["artist"] = val
            elif key == "al":
                meta["album"] = val
            elif key == "offset":
                try:
                    shift += float(val) / 1000.0
                except ValueError:
                    pass
            continue
        packed = _LINE.match(row)
        if not packed:
            continue
        stamps, rest = packed.group(1), packed.group(2)
        times = [_parse_stamp(m) + shift for m in _TS.finditer(stamps)]
        extra = list(
            re.finditer(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]([^\[]*)", rest)
        )
        words = []
        if extra:
            pre = rest[: extra[0].start()]
            t0 = times[0] if times else 0.0
            if pre:
                words.append({"t": round(t0, 3), "text": pre})
            for wm in extra:
                words.append({
                    "t": round(_seconds(wm.group(1), wm.group(2), wm.group(3) or "") + shift, 3),
                    "text": wm.group(4),
                })
            text_line = "".join(w["text"] for w in words).strip()
        else:
            text_line = rest.strip()
        if not text_line and not words:
            continue
        for t in times:
            lines.append({
                "t": round(max(0.0, t), 3),
                "text": text_line,
                "words": words if words else [],
            })
    lines.sort(key=lambda x: x["t"])
    return {"meta": meta, "lines": lines}


_TOKEN = re.compile(r"\S+\s*")


def expand_words(lines):
    """Give line-timed LRC per-word stamps so karaoke can follow tempo."""
    rows = list(lines or [])
    n = len(rows)
    out = []
    for i, line in enumerate(rows):
        row = dict(line)
        words = list(row.get("words") or [])
        if words:
            row["words"] = words
            out.append(row)
            continue
        text = row.get("text") or ""
        tokens = _TOKEN.findall(text) or ([text] if text else [])
        t0 = float(row.get("t") or 0.0)
        if i + 1 < n:
            t1 = float(rows[i + 1].get("t") or 0.0)
        else:
            t1 = t0 + max(2.0, 0.45 * max(1, len(tokens)))
        if t1 <= t0:
            t1 = t0 + max(2.0, 0.45 * max(1, len(tokens)))
        span = t1 - t0
        count = float(max(1, len(tokens)))
        built = []
        for k, tok in enumerate(tokens):
            built.append({
                "t": round(t0 + span * (k / count), 3),
                "text": tok,
            })
        row["words"] = built
        out.append(row)
    return out


def parse_plain(text):
    lines = []
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        row = raw.strip()
        if row:
            lines.append({"t": 0.0, "text": row, "words": []})
    return {"meta": {"title": "", "artist": "", "album": ""}, "lines": lines}


def _join_rel(rel, origin="local"):
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return "", None
    origin = "nas" if origin == "nas" else "local"
    base = os.path.realpath(NAS_DIR if origin == "nas" else MUSIC_DIR)
    full = os.path.realpath(os.path.join(base, rel))
    if full == base or not full.startswith(base + os.sep):
        return rel, None
    return rel, full


def _full_audio(rel, origin="local"):
    rel, full = _join_rel(rel, origin=origin)
    if not full or not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in AUDIO_EXT:
        return None
    return full


def _probe_duration(full):
    try:
        raw = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json", full,
            ],
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        data = json.loads(raw.decode("utf-8") or "{}")
        return float(((data.get("format") or {}).get("duration") or 0) or 0)
    except Exception:
        return 0.0


def sidecar_paths(full):
    folder, name = os.path.split(full)
    stem, _ext = os.path.splitext(name)
    return [
        os.path.join(folder, stem + ".lrc"),
        os.path.join(folder, stem + ".txt"),
        os.path.join(folder, "lyrics", stem + ".lrc"),
        os.path.join(folder, "lyrics", stem + ".txt"),
    ]


def _cache_path(rel):
    key = hashlib.sha1((rel or "").encode("utf-8")).hexdigest()[:24]
    return os.path.join(LYRICS_DIR, key + ".json")


def _read_text(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read(400000)
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _embedded_lyrics(full):
    try:
        raw = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags=lyrics,unsyncedlyrics,LYRICS,Lyrics",
                "-of",
                "json",
                full,
            ],
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        data = json.loads(raw.decode("utf-8", "replace"))
        tags = ((data.get("format") or {}).get("tags") or {})
        for key, val in tags.items():
            short = str(key).split(":")[-1].lower()
            if short in ("lyrics", "unsyncedlyrics") and str(val).strip():
                return str(val)
    except Exception:
        return ""
    return ""


def _payload(source, parsed, synced, artist="", title="", album="", name=""):
    meta = parsed.get("meta") or {}
    lines = parsed.get("lines") or []
    if synced:
        lines = expand_words(lines)
    return {
        "ok": True,
        "synced": bool(synced),
        "source": source,
        "name": name or "",
        "artist": artist or meta.get("artist") or "",
        "title": title or meta.get("title") or "",
        "album": album or meta.get("album") or "",
        "lines": lines,
    }


class LyricsIndex(object):
    def __init__(self, start=True):
        self.lock = threading.Lock()
        self.mem = {}
        self.queue = []
        self.queued = set()
        self.busy = ""
        self.current_title = ""
        self.batch_total = 0
        self.batch_done = 0
        self.batch_ok = 0
        self.batch_fail = 0
        self._backfill_at = 0.0
        self._backfill = bool(start)
        if start:
            t = threading.Thread(target=self._loop, name="lyrics-prep", daemon=True)
            t.start()

    def _track_info(self, rel, origin="local"):
        if origin != "nas":
            for t in CATALOG.tracks():
                if t.get("name") == rel:
                    return t
            ident = identity_from_path(rel)
            ident["name"] = rel
            return ident
        try:
            import nas as nasmod
            artist, album, title = nasmod.parse_nas_meta(rel)
        except Exception:
            artist, album, title = "", "", os.path.splitext(os.path.basename(rel or ""))[0]
        return {
            "name": rel,
            "artist": artist or UNKNOWN_ARTIST,
            "album": album or UNKNOWN_ALBUM,
            "title": title or "",
        }

    def _remember(self, rel, payload):
        if not rel or not isinstance(payload, dict) or not payload.get("ok"):
            return payload
        with self.lock:
            self.mem[rel] = payload
        return payload

    def _cache_hit(self, rel):
        with self.lock:
            hit = self.mem.get(rel)
            if isinstance(hit, dict):
                return hit
        cache_path = _cache_path(rel)
        try:
            with open(cache_path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError, TypeError):
            pass
        return None

    def ready(self, rel, origin="local"):
        """True when local/cached lyrics exist (no remote fetch, no embedded probe)."""
        rel, full = _join_rel(rel, origin=origin)
        if not rel:
            return False
        hit = self._cache_hit(rel)
        if isinstance(hit, dict) and hit.get("ok") and hit.get("lines"):
            return True
        if full:
            for path in sidecar_paths(full):
                if not os.path.isfile(path):
                    continue
                try:
                    if os.path.getsize(path) > 0:
                        return True
                except OSError:
                    continue
        return False

    def missed(self, rel):
        hit = self._cache_hit(rel)
        if not isinstance(hit, dict):
            return False
        if hit.get("ok") and hit.get("lines"):
            return False
        return bool(hit.get("attempted"))

    def enqueue(self, rel, front=False):
        """Queue a host-disk track for automatic lyrics fetch. NAS paths are ignored."""
        rel, full = _join_rel(rel, origin="local")
        if not rel or not full or not os.path.isfile(full):
            return False
        if os.path.splitext(full)[1].lower() not in AUDIO_EXT:
            return False
        if self.ready(rel, origin="local") or self.missed(rel):
            return False
        with self.lock:
            if rel in self.queued or rel == self.busy:
                return True
            if not self.queue and not self.busy:
                self.batch_total = 0
                self.batch_done = 0
                self.batch_ok = 0
                self.batch_fail = 0
            if front:
                self.queue.insert(0, rel)
            else:
                self.queue.append(rel)
            self.queued.add(rel)
            self.batch_total += 1
        return True

    def status(self):
        with self.lock:
            pending = len(self.queue)
            busy = bool(self.busy or pending)
            total = self.batch_total
            done = self.batch_done
            working = done + (1 if self.busy else 0)
            pct = 0
            if total:
                pct = int(round(100.0 * working / float(total)))
                if pct > 100:
                    pct = 100
            elif not busy:
                pct = 100
            return {
                "ok": True,
                "busy": busy,
                "current": self.busy,
                "title": self.current_title,
                "pending": pending,
                "done": done,
                "found": self.batch_ok,
                "failed": self.batch_fail,
                "total": total,
                "pct": pct,
            }

    def _loop(self):
        idle_since = time.time()
        while True:
            rel = ""
            with self.lock:
                if self.queue:
                    rel = self.queue.pop(0)
                    self.queued.discard(rel)
                    self.busy = rel
                    self.current_title = os.path.splitext(os.path.basename(rel))[0].replace("_", " ")
            if rel:
                self._prep_one(rel)
                idle_since = time.time()
                time.sleep(0.25)
                continue
            if self._backfill and time.time() - idle_since >= 2.0:
                if time.time() - self._backfill_at >= 8.0:
                    self._backfill_at = time.time()
                    self._offer_catalog()
                    idle_since = time.time()
            time.sleep(0.4)

    def _offer_catalog(self):
        if getattr(CATALOG, "scanning", False):
            return
        try:
            tracks = CATALOG.tracks()
        except Exception:
            return
        n = 0
        for row in tracks or []:
            if n >= 400:
                break
            name = row.get("name") or ""
            if not name:
                continue
            if self.enqueue(name):
                n += 1

    def _prep_one(self, rel):
        rel, full = _join_rel(rel, origin="local")
        dur = _probe_duration(full) if full else 0.0
        info = self._track_info(rel, origin="local")
        label = (info.get("title") or os.path.splitext(os.path.basename(rel or ""))[0]).replace("_", " ")
        artist = info.get("artist") or ""
        if artist and artist != UNKNOWN_ARTIST:
            label = artist + " — " + label
        with self.lock:
            self.current_title = label
        ok = False
        try:
            data = self.lookup(rel, fetch=True, duration=dur, origin="local")
            ok = bool(data.get("ok") and data.get("lines"))
        except Exception:
            ok = False
        with self.lock:
            self.batch_done += 1
            if ok:
                self.batch_ok += 1
            else:
                self.batch_fail += 1
            self.busy = ""
            self.current_title = ""

    def _remember_miss(self, rel, artist="", title="", album=""):
        payload = {
            "ok": False,
            "error": "no lyrics",
            "attempted": True,
            "name": rel,
            "artist": artist,
            "title": title,
            "album": album,
            "lines": [],
            "hint": "Drop a matching .lrc next to the track, or fetch from Karaoke.",
        }
        cache_path = _cache_path(rel)
        try:
            os.makedirs(LYRICS_DIR, exist_ok=True)
            tmp = cache_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            os.replace(tmp, cache_path)
        except OSError:
            pass
        with self.lock:
            self.mem[rel] = payload
        return payload

    def lookup(self, rel, fetch=False, duration=0, origin="local"):
        origin = "nas" if origin == "nas" else "local"
        rel, full = _join_rel(rel, origin=origin)
        if not full or not os.path.isfile(full):
            return {"ok": False, "error": "not found", "name": rel, "lines": []}
        if os.path.splitext(full)[1].lower() not in AUDIO_EXT:
            return {"ok": False, "error": "not found", "name": rel, "lines": []}
        info = self._track_info(rel, origin=origin)
        artist = info.get("artist") or ""
        title = info.get("title") or ""
        album = info.get("album") or ""
        if artist == UNKNOWN_ARTIST:
            artist = ""
        if album == UNKNOWN_ALBUM:
            album = ""
        for path in sidecar_paths(full):
            if not os.path.isfile(path):
                continue
            text = _read_text(path)
            if not text.strip():
                continue
            if path.lower().endswith(".lrc") or _TS.search(text):
                parsed = parse_lrc(text)
                if parsed["lines"]:
                    return self._remember(rel, _payload("sidecar", parsed, True, artist, title, album, rel))
            parsed = parse_plain(text)
            if parsed["lines"]:
                return self._remember(rel, _payload("sidecar", parsed, False, artist, title, album, rel))
        embedded = _embedded_lyrics(full)
        if embedded.strip():
            if _TS.search(embedded):
                parsed = parse_lrc(embedded)
                if parsed["lines"]:
                    return self._remember(rel, _payload("tags", parsed, True, artist, title, album, rel))
            parsed = parse_plain(embedded)
            if parsed["lines"]:
                return self._remember(rel, _payload("tags", parsed, False, artist, title, album, rel))
        if not fetch:
            hit = self._cache_hit(rel)
            if isinstance(hit, dict) and hit.get("ok") and hit.get("lines"):
                hit["name"] = rel
                return hit
            return {
                "ok": False,
                "error": "no lyrics",
                "name": rel,
                "artist": artist,
                "title": title,
                "album": album,
                "lines": [],
                "hint": "Drop a matching .lrc next to the track (MusicBee / foobar OpenLyrics style), or fetch from LRCLIB.",
            }
        remote = self._fetch_lrclib(
            rel, full, artist, title, album, duration, write_sidecar=(origin != "nas")
        )
        if remote:
            return self._remember(rel, remote)
        return self._remember_miss(rel, artist, title, album)

    def drop_name(self, rel):
        """Remove sidecar lyrics and cache JSON for this library name."""
        rel, full = _join_rel(rel)
        if not rel:
            return 0
        victims = set()
        if full:
            for path in sidecar_paths(full):
                victims.add(path)
        victims.add(_cache_path(rel))
        try:
            listing = os.listdir(LYRICS_DIR)
        except OSError:
            listing = []
        for fn in listing:
            if not fn.endswith(".json"):
                continue
            path = os.path.join(LYRICS_DIR, fn)
            try:
                with open(path, "r") as fh:
                    data = json.load(fh)
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get("name") == rel:
                victims.add(path)
        removed = 0
        folders = set()
        for path in victims:
            for extra in (path, path + ".tmp"):
                try:
                    os.remove(extra)
                    removed += 1
                except OSError:
                    pass
            folder = os.path.dirname(path)
            if os.path.basename(folder) == "lyrics":
                folders.add(folder)
        for folder in folders:
            try:
                os.rmdir(folder)
            except OSError:
                pass
        with self.lock:
            for key in list(self.mem):
                data = self.mem.get(key) or {}
                if key == rel or data.get("name") == rel:
                    self.mem.pop(key, None)
            self.queue = [n for n in self.queue if n != rel]
            self.queued.discard(rel)
        return removed

    def _fetch_lrclib(self, rel, full, artist, title, album, duration, write_sidecar=True):
        if not title:
            return None
        os.makedirs(LYRICS_DIR, exist_ok=True)
        cache_path = _cache_path(rel)
        try:
            with open(cache_path, "r") as fh:
                cached = json.load(fh)
            if cached.get("ok") and cached.get("lines"):
                cached["name"] = rel
                return cached
        except (OSError, ValueError, TypeError):
            pass
        data = None
        if artist and duration:
            data = self._http_json(
                LRCLIB.rstrip("/")
                + "/get?"
                + urlencode({
                    "track_name": title,
                    "artist_name": artist,
                    "album_name": album or title,
                    "duration": int(round(float(duration))),
                })
            )
        if not data:
            q = {"track_name": title}
            if artist:
                q["artist_name"] = artist
            found = self._http_json(LRCLIB.rstrip("/") + "/search?" + urlencode(q))
            if isinstance(found, list) and found:
                data = found[0]
        if not isinstance(data, dict):
            return None
        synced = data.get("syncedLyrics") or ""
        plain = data.get("plainLyrics") or ""
        if synced.strip() and _TS.search(synced):
            parsed = parse_lrc(synced)
            payload = _payload("lrclib", parsed, True, artist, title, album, rel)
        elif plain.strip():
            parsed = parse_plain(plain)
            payload = _payload("lrclib", parsed, False, artist, title, album, rel)
        else:
            return None
        try:
            tmp = cache_path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            os.replace(tmp, cache_path)
        except OSError:
            pass
        # Never write a sidecar onto a NAS share. Cache JSON stays on this host.
        if write_sidecar:
            lrc_path = os.path.splitext(full)[0] + ".lrc"
            if synced.strip() and not os.path.isfile(lrc_path):
                try:
                    with open(lrc_path, "w") as fh:
                        fh.write(synced)
                except OSError:
                    pass
        return payload

    def _http_json(self, url):
        try:
            req = Request(url, headers={"User-Agent": CLIENT, "Lrclib-Client": CLIENT})
            fh = urlopen(req, timeout=6)
            try:
                raw = fh.read(250000)
            finally:
                fh.close()
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None


LYRICS = LyricsIndex()
