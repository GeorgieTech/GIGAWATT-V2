#!/usr/bin/env python3
"""Track report for Instagram-ready notes.

Local tags first, then the research plugin (MusicBrainz + Wikipedia).
Cache in /data/crypt/reports dies with the track.
Python 3.8 stdlib only.
"""
from __future__ import print_function

import hashlib
import json
import os
import re
import subprocess
import threading

from player import MUSIC_DIR
from library import CATALOG, UNKNOWN_ARTIST, UNKNOWN_ALBUM, identity_from_path
from lyrics import LYRICS
from research import PLUGIN, _clean, _year, sentences
from essay import write_essay

REPORT_DIR = os.environ.get("CRYPT_REPORTS", "/data/crypt/reports")
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")
CLIENT = "CRYPT/1.1.7"


def _join_rel(rel):
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return "", None
    base = os.path.realpath(MUSIC_DIR)
    full = os.path.realpath(os.path.join(base, rel))
    if full == base or not full.startswith(base + os.sep):
        return rel, None
    return rel, full


def _cache_path(rel):
    key = hashlib.sha1((rel or "").encode("utf-8")).hexdigest()[:24]
    return os.path.join(REPORT_DIR, key + ".json")


def _fmt_time(sec):
    try:
        sec = max(0, int(round(float(sec or 0))))
    except (TypeError, ValueError):
        return ""
    return "%d:%02d" % (sec // 60, sec % 60)


def _hashtag(word):
    text = re.sub(r"[^A-Za-z0-9]+", "", str(word or ""))
    if len(text) < 2:
        return ""
    return "#" + text


def _local_year(full):
    if not full or not os.path.isfile(full):
        return ""
    try:
        raw = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags=date,year,DATE,Year,originalyear,ORIGINALDATE",
                "-of",
                "json",
                full,
            ],
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
        tags = ((data.get("format") or {}).get("tags") or {})
        for key, val in tags.items():
            found = _year(val)
            if found:
                return found
    except Exception:
        return ""
    return ""


def _facts(ident, rec, artist_info):
    rows = []
    def add(label, value):
        value = _clean(value)
        if value:
            rows.append({"label": label, "value": value})
    add("Artist", ident.get("artist"))
    add("Song", ident.get("title"))
    add("Album", ident.get("album") if ident.get("album") != UNKNOWN_ALBUM else "")
    add("Year", ident.get("year"))
    add("Genre", ident.get("genre"))
    add("Duration", ident.get("length"))
    if rec:
        add("First release", rec.get("first_release") or rec.get("year"))
        if rec.get("releases"):
            names = []
            for item in rec["releases"][:3]:
                bit = item.get("title") or ""
                if item.get("year"):
                    bit += " (%s)" % item["year"]
                if bit:
                    names.append(bit)
            add("Also on", "; ".join(names))
        if rec.get("tags"):
            add("Recording tags", ", ".join(rec["tags"]))
    if artist_info:
        add("Artist type", artist_info.get("type"))
        origin = " · ".join([p for p in (artist_info.get("begin_area"), artist_info.get("country")) if p])
        add("Origin", origin)
        add("Born / formed", artist_info.get("born"))
        if artist_info.get("disambiguation"):
            add("Also known", artist_info.get("disambiguation"))
        if artist_info.get("tags"):
            add("Artist tags", ", ".join(artist_info["tags"]))
    return rows


def _hashtags(ident, rec, artist_info):
    tags = []
    seen = set()
    def push(word):
        tag = _hashtag(word)
        key = tag.lower()
        if not tag or key in seen:
            return
        seen.add(key)
        tags.append(tag)
    push(ident.get("artist"))
    for part in re.split(r"\s+", ident.get("title") or ""):
        if len(part) > 3:
            push(part)
            break
    push(ident.get("album") if ident.get("album") != UNKNOWN_ALBUM else "")
    push(ident.get("genre"))
    push(ident.get("year"))
    for name in (rec or {}).get("tags") or []:
        push(name)
    for name in (artist_info or {}).get("tags") or []:
        push(name)
    push("NowPlaying")
    push("HiFi")
    push("TOSLINK")
    return tags[:12]


def _story(ident, rec, wiki_song, wiki_artist):
    title = ident.get("title") or "This track"
    artist = ident.get("artist") or "an unknown artist"
    album = ident.get("album")
    year = ident.get("year") or (rec or {}).get("year")
    line = '"%s" is a recording by %s' % (title, artist)
    if album and album != UNKNOWN_ALBUM:
        line += " from the album %s" % album
    if year:
        line += ", first released in %s" % year
    line += "."
    paras = [line]
    song_bit = sentences((wiki_song or {}).get("extract"), 3)
    if song_bit and song_bit.lower() not in line.lower():
        paras.append(song_bit)
    artist_bit = sentences((wiki_artist or {}).get("extract"), 2)
    if artist_bit:
        paras.append(artist_bit)
    return paras


def _caption(ident, story, hashtags):
    artist = ident.get("artist") or ""
    title = ident.get("title") or ""
    album = ident.get("album") if ident.get("album") != UNKNOWN_ALBUM else ""
    year = ident.get("year") or ""
    lines = ['%s — “%s”' % (artist, title)]
    sub = album
    if year:
        sub = (sub + " · " if sub else "") + year
    if sub:
        lines.append(sub)
    lines.append("")
    if story:
        lines.append(story[0])
        if len(story) > 1:
            extra = story[1]
            if len(extra) < 280:
                lines.append("")
                lines.append(extra)
    lines.append("")
    lines.append(" ".join(hashtags))
    return "\n".join(lines).strip()


def _lyric_text(rel):
    try:
        data = LYRICS.lookup(rel, fetch=False)
    except Exception:
        return ""
    lines = []
    for row in data.get("lines") or []:
        text = (row or {}).get("text") or ""
        if text:
            lines.append(text)
        if len(lines) >= 48:
            break
    return "\n".join(lines)


def _essay_ctx(ident, payload, research):
    artist_info = (research or {}).get("artist_info") or {}
    origin = " · ".join(
        [p for p in (artist_info.get("begin_area"), artist_info.get("country")) if p]
    )
    return {
        "title": payload.get("title"),
        "artist": payload.get("artist"),
        "album": payload.get("album"),
        "year": payload.get("year"),
        "genre": payload.get("genre"),
        "origin": origin,
        "facts": payload.get("facts") or [],
        "wiki_song": (research or {}).get("wiki_song") or {},
        "wiki_artist": (research or {}).get("wiki_artist") or {},
        "lyrics": _lyric_text(ident.get("name") or payload.get("name") or ""),
        "sources": payload.get("sources") or [],
    }


def _markdown(payload):
    ident = payload
    lines = [
        "# %s — %s" % (ident.get("artist") or "", ident.get("title") or ""),
        "",
    ]
    if ident.get("album") and ident.get("album") != UNKNOWN_ALBUM:
        lines.append("Album: %s" % ident["album"])
    if ident.get("year"):
        lines.append("Year: %s" % ident["year"])
    if ident.get("genre"):
        lines.append("Genre: %s" % ident["genre"])
    lines.append("")
    lines.append("## Story")
    for para in ident.get("story") or []:
        lines.append("")
        lines.append(para)
    lines.append("")
    if ident.get("essay"):
        lines.append("## Meaning and life")
        for para in ident.get("essay") or []:
            lines.append("")
            lines.append(para)
        lines.append("")
    lines.append("## Facts")
    for fact in ident.get("facts") or []:
        lines.append("- **%s:** %s" % (fact.get("label"), fact.get("value")))
    lines.append("")
    lines.append("## Instagram caption")
    lines.append("")
    lines.append("```")
    lines.append(ident.get("caption") or "")
    lines.append("```")
    if ident.get("sources"):
        lines.append("")
        lines.append("## Sources")
        for src in ident["sources"]:
            lines.append("- %s: %s" % (src.get("label"), src.get("url")))
    lines.append("")
    return "\n".join(lines)


class ReportIndex(object):
    def __init__(self, plugin=None, writer=None):
        self.lock = threading.Lock()
        self.plugin = plugin or PLUGIN
        self.writer = writer
        self.mem = {}

    def _track_info(self, rel):
        for t in CATALOG.tracks():
            if t.get("name") == rel:
                return t
        ident = identity_from_path(rel)
        ident["name"] = rel
        return ident

    def _identity(self, rel, duration=0):
        rel, full = _join_rel(rel)
        info = self._track_info(rel) if rel else {}
        artist = info.get("artist") or ""
        title = info.get("title") or ""
        album = info.get("album") or ""
        genre = info.get("genre") or ""
        if artist == UNKNOWN_ARTIST:
            artist = ""
        if album == UNKNOWN_ALBUM:
            album = ""
        year = _local_year(full) if full else ""
        length = _fmt_time(duration)
        return {
            "name": rel,
            "title": title,
            "artist": artist,
            "album": album or UNKNOWN_ALBUM,
            "genre": genre,
            "year": year,
            "length": length,
            "duration": duration,
        }

    def _payload(self, ident, research=None, researched=False):
        rec = (research or {}).get("recording") or {}
        artist_info = (research or {}).get("artist_info") or {}
        wiki_song = (research or {}).get("wiki_song") or {}
        wiki_artist = (research or {}).get("wiki_artist") or {}
        if rec.get("year") and not ident.get("year"):
            ident = dict(ident)
            ident["year"] = rec.get("year")
        story = _story(ident, rec, wiki_song, wiki_artist)
        facts = _facts(ident, rec, artist_info)
        tags = _hashtags(ident, rec, artist_info)
        payload = {
            "ok": True,
            "researched": bool(researched),
            "name": ident.get("name") or "",
            "title": ident.get("title") or "",
            "artist": ident.get("artist") or "",
            "album": ident.get("album") or "",
            "genre": ident.get("genre") or "",
            "year": ident.get("year") or "",
            "length": ident.get("length") or "",
            "story": story,
            "essay": [],
            "essay_source": "",
            "facts": facts,
            "hashtags": tags,
            "caption": _caption(ident, story, tags),
            "sources": (research or {}).get("sources") or [],
            "image": (wiki_song or {}).get("image") or (wiki_artist or {}).get("image") or "",
        }
        if researched:
            essay, kind = write_essay(_essay_ctx(ident, payload, research), writer=self.writer)
            payload["essay"] = essay or []
            payload["essay_source"] = kind or ""
        payload["markdown"] = _markdown(payload)
        if not researched:
            payload["hint"] = "Local tags only. Research pulls MusicBrainz, Wikipedia, and a meaning essay."
        else:
            payload["hint"] = "Cached with this track. Deleting the file also deletes this report."
        return payload

    def lookup(self, rel, fetch=False, duration=0):
        rel, full = _join_rel(rel)
        if not rel or not full or not os.path.isfile(full):
            return {"ok": False, "error": "not found", "name": rel, "story": [], "facts": [], "sources": []}
        if os.path.splitext(full)[1].lower() not in AUDIO_EXT:
            return {"ok": False, "error": "not found", "name": rel, "story": [], "facts": [], "sources": []}
        ident = self._identity(rel, duration)
        if not fetch:
            cached = self._read_cache(rel)
            if cached:
                return cached
            return self._payload(ident, researched=False)
        album = ident.get("album") or ""
        if album == UNKNOWN_ALBUM:
            album = ""
        research = self.plugin.gather(ident.get("artist") or "", ident.get("title") or "", album)
        payload = self._payload(ident, research=research, researched=True)
        if not research.get("ok"):
            payload["error"] = research.get("error") or "research failed"
            payload["researched"] = False
            payload["hint"] = "Research did not land. Check that the S2 can reach MusicBrainz and Wikipedia."
            return payload
        if not payload["sources"]:
            payload["hint"] = "No public page matched. The report still uses local tags — edit artist/album in Library if they are wrong."
        self._write_cache(rel, payload)
        return payload

    def _read_cache(self, rel):
        path = _cache_path(rel)
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("ok") and data.get("name") == rel:
                data["researched"] = True
                return data
        except (OSError, ValueError, TypeError):
            return None
        return None

    def _write_cache(self, rel, payload):
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = _cache_path(rel)
        try:
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            os.replace(tmp, path)
        except OSError:
            pass
        with self.lock:
            self.mem[rel] = payload

    def drop_name(self, rel):
        rel, _full = _join_rel(rel)
        if not rel:
            return 0
        victims = set([_cache_path(rel)])
        try:
            listing = os.listdir(REPORT_DIR)
        except OSError:
            listing = []
        for fn in listing:
            if not fn.endswith(".json"):
                continue
            path = os.path.join(REPORT_DIR, fn)
            try:
                with open(path, "r") as fh:
                    data = json.load(fh)
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(data, dict) and data.get("name") == rel:
                victims.add(path)
        removed = 0
        for path in victims:
            for extra in (path, path + ".tmp"):
                try:
                    os.remove(extra)
                    removed += 1
                except OSError:
                    pass
        with self.lock:
            self.mem.pop(rel, None)
        return removed


REPORTS = ReportIndex()
