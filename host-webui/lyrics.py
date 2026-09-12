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

try:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import urlencode
    from urllib2 import Request, urlopen

from player import MUSIC_DIR
from library import CATALOG, UNKNOWN_ARTIST, UNKNOWN_ALBUM, identity_from_path

LYRICS_DIR = os.environ.get("CRYPT_LYRICS", "/data/crypt/lyrics")
LRCLIB = os.environ.get("CRYPT_LRCLIB", "https://lrclib.net/api")
CLIENT = "CRYPT/2.1.0 (https://github.com/GeorgieTech/GIGAWATT-V2)"
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


def _join_rel(rel):
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return "", None
    base = os.path.realpath(MUSIC_DIR)
    full = os.path.realpath(os.path.join(base, rel))
    if full == base or not full.startswith(base + os.sep):
        return rel, None
    return rel, full


def _full_audio(rel):
    rel, full = _join_rel(rel)
    if not full or not os.path.isfile(full):
        return None
    if os.path.splitext(full)[1].lower() not in AUDIO_EXT:
        return None
    return full


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
    def __init__(self):
        self.lock = threading.Lock()
        self.mem = {}

    def _track_info(self, rel):
        for t in CATALOG.tracks():
            if t.get("name") == rel:
                return t
        ident = identity_from_path(rel)
        ident["name"] = rel
        return ident

    def lookup(self, rel, fetch=False, duration=0):
        rel, full = _join_rel(rel)
        if not full or not os.path.isfile(full):
            return {"ok": False, "error": "not found", "name": rel, "lines": []}
        if os.path.splitext(full)[1].lower() not in AUDIO_EXT:
            return {"ok": False, "error": "not found", "name": rel, "lines": []}
        info = self._track_info(rel)
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
                    return _payload("sidecar", parsed, True, artist, title, album, rel)
            parsed = parse_plain(text)
            if parsed["lines"]:
                return _payload("sidecar", parsed, False, artist, title, album, rel)
        embedded = _embedded_lyrics(full)
        if embedded.strip():
            if _TS.search(embedded):
                parsed = parse_lrc(embedded)
                if parsed["lines"]:
                    return _payload("tags", parsed, True, artist, title, album, rel)
            parsed = parse_plain(embedded)
            if parsed["lines"]:
                return _payload("tags", parsed, False, artist, title, album, rel)
        if fetch:
            remote = self._fetch_lrclib(rel, full, artist, title, album, duration)
            if remote:
                return remote
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
        return removed

    def _fetch_lrclib(self, rel, full, artist, title, album, duration):
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
