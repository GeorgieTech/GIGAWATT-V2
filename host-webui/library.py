#!/usr/bin/env python3
"""Library catalog: tags, artist/album browse, playlists. Python 3.8 stdlib."""
from __future__ import print_function

import json
import os
import re
import subprocess
import threading
import time
import uuid

from player import MUSIC_DIR

STATE_DIR = os.environ.get("CRYPT_STATE", "/data/crypt")
META_FILE = os.path.join(STATE_DIR, "library-meta.json")
PLAYLIST_FILE = os.path.join(STATE_DIR, "playlists.json")
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")
UNKNOWN_ARTIST = "Unknown artist"
UNKNOWN_ALBUM = "Unknown album"
GENRES = (
    "Trance",
    "House",
    "Techno",
    "Drum & Bass",
    "Dubstep",
    "Electronic",
    "Ambient",
    "Pop",
    "Rock",
    "Hip-Hop",
    "R&B",
    "Jazz",
    "Classical",
    "Metal",
    "Country",
    "Soundtrack",
    "Other",
)
DISC_RE = re.compile(r"^(disc|disk|cd)\s*\d+$", re.I)
TRACK_PREFIX_RE = re.compile(r"^(\d{1,3})\s*[-.)]\s*")
PAIR_RE = re.compile(r"\s+-\s+")

_PROBE_CMD = [
    "ffprobe",
    "-v",
    "error",
    "-show_entries",
    "format_tags=title,artist,album,album_artist,albumartist,track,genre",
    "-show_entries",
    "stream_tags=title,artist,album,track",
    "-of",
    "json",
]


def _pretty_title(name):
    base = os.path.splitext(os.path.basename(name or ""))[0]
    base = base.replace("_", " ").replace("\uff5c", "—").replace("|", "—")
    prev = None
    while prev != base:
        prev = base
        base = TRACK_PREFIX_RE.sub("", base)
    return re.sub(r"\s+", " ", base).strip() or (name or "Track")


def _parse_filename_pair(title):
    if " - " not in (title or ""):
        return "", title
    artist, rest = title.split(" - ", 1)
    artist = artist.strip()
    rest = rest.strip()
    if artist and rest:
        return artist, rest
    return "", title


def _path_meta(rel):
    parts = [p for p in (rel or "").replace("\\", "/").split("/") if p]
    if not parts:
        return "", "", ""
    title = _pretty_title(parts[-1])
    folders = parts[:-1]
    while folders and DISC_RE.match(folders[-1]):
        folders.pop()
    artist = folders[0] if folders else ""
    album = folders[1] if len(folders) > 1 else ""
    return artist, album, title


def _tag_get(maps, *keys):
    wanted = set(k.lower() for k in keys)
    for mapping in maps:
        if not isinstance(mapping, dict):
            continue
        for key, value in mapping.items():
            short = str(key).split(":")[-1].lower()
            if short in wanted:
                text = str(value or "").strip()
                if text:
                    return text
    return ""


def _track_no(tag, rel):
    if tag:
        m = re.match(r"(\d+)", str(tag).strip())
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    base = os.path.splitext(os.path.basename(rel or ""))[0]
    m = TRACK_PREFIX_RE.match(base)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return 0


def _probe_key(rel, size, mtime):
    return "%s|%s|%s" % (rel or "", int(size or 0), int(mtime or 0))


def probe_file(full):
    info = {"title": "", "artist": "", "album": "", "track": 0, "genre": ""}
    try:
        raw = subprocess.check_output(_PROBE_CMD + [full], stderr=subprocess.DEVNULL, timeout=4)
        data = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        return info
    tags = []
    fmt = data.get("format") or {}
    if isinstance(fmt.get("tags"), dict):
        tags.append(fmt.get("tags"))
    for stream in data.get("streams") or []:
        if isinstance(stream.get("tags"), dict):
            tags.append(stream.get("tags"))
    info["title"] = _tag_get(tags, "title")
    info["artist"] = _tag_get(tags, "artist", "album_artist", "albumartist")
    info["album"] = _tag_get(tags, "album")
    info["genre"] = _tag_get(tags, "genre")
    info["track"] = _track_no(_tag_get(tags, "track"), os.path.basename(full))
    return info


def identity_from_path(rel, probed=None, override=None):
    probed = probed or {}
    override = override if isinstance(override, dict) else {}
    path_artist, path_album, path_title = _path_meta(rel)
    fn_artist, fn_title = _parse_filename_pair(path_title)
    artist = (override.get("artist") or probed.get("artist") or path_artist or fn_artist or "").strip()
    album = (override.get("album") or probed.get("album") or path_album or "").strip()
    title = (override.get("title") or probed.get("title") or "").strip()
    if not title:
        title = fn_title if fn_artist else path_title
    if not title:
        title = _pretty_title(rel)
    track = int(probed.get("track") or 0) or _track_no("", rel)
    genre = (override.get("genre") if "genre" in override else probed.get("genre") or "").strip()
    return {
        "title": title,
        "artist": artist or UNKNOWN_ARTIST,
        "album": album or UNKNOWN_ALBUM,
        "track": track,
        "genre": genre,
        "edited": bool(override),
    }


class Library(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.edits = {}
        self.scanning = False
        self._dirty = 0
        self._load()
        t = threading.Thread(target=self._scan_loop, name="lib-scan", daemon=True)
        t.start()

    def _load(self):
        try:
            with open(META_FILE, "r") as fh:
                data = json.load(fh)
            probes = data.get("probes") if isinstance(data, dict) else None
            if isinstance(probes, dict):
                self.cache = probes
            edits = data.get("edits") if isinstance(data, dict) else None
            if isinstance(edits, dict):
                self.edits = edits
        except (OSError, ValueError, TypeError):
            self.cache = {}
            self.edits = {}

    def _save(self):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            tmp = META_FILE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"probes": self.cache, "edits": self.edits}, fh, separators=(",", ":"))
            os.replace(tmp, META_FILE)
            self._dirty = 0
        except OSError:
            pass

    def walk(self):
        base = os.path.realpath(MUSIC_DIR)
        out = []
        if not os.path.isdir(base):
            return out
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if os.path.splitext(fn)[1].lower() not in AUDIO_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, base).replace("\\", "/")
                try:
                    st = os.stat(full)
                    size, mtime = st.st_size, int(st.st_mtime)
                except OSError:
                    size, mtime = 0, 0
                out.append({"name": rel, "full": full, "size": size, "mtime": mtime})
        return out

    def tracks(self):
        files = self.walk()
        out = []
        missing = 0
        with self.lock:
            cache = self.cache
            for item in files:
                key = _probe_key(item["name"], item["size"], item["mtime"])
                probed = cache.get(key)
                override = self.edits.get(item["name"]) or {}
                ident = identity_from_path(item["name"], probed, override)
                rec = {
                    "name": item["name"],
                    "size": item["size"],
                    "mtime": item["mtime"],
                    "title": ident["title"],
                    "artist": ident["artist"],
                    "album": ident["album"],
                    "track": ident["track"],
                    "genre": ident["genre"],
                    "tagged": bool(probed),
                    "edited": ident.get("edited") or False,
                }
                out.append(rec)
                if probed is None:
                    missing += 1
        out.sort(
            key=lambda t: (
                t["artist"].lower(),
                t["album"].lower(),
                t["track"] or 9999,
                t["title"].lower(),
                t["name"].lower(),
            )
        )
        if missing and not self.scanning:
            pass
        return out

    def names(self):
        return [t["name"] for t in self.tracks()]

    def _scan_loop(self):
        while True:
            try:
                files = self.walk()
                todo = []
                with self.lock:
                    for item in files:
                        key = _probe_key(item["name"], item["size"], item["mtime"])
                        if key not in self.cache:
                            todo.append((key, item["full"]))
                if not todo:
                    self.scanning = False
                    time.sleep(8)
                    continue
                self.scanning = True
                key, full = todo[0]
                info = probe_file(full)
                with self.lock:
                    self.cache[key] = info
                    self._dirty += 1
                    if self._dirty >= 6:
                        self._save()
                time.sleep(0.05)
            except Exception:
                time.sleep(1)

    def drop_name(self, name):
        prefix = (name or "") + "|"
        with self.lock:
            drop = [k for k in self.cache if k.startswith(prefix)]
            for k in drop:
                self.cache.pop(k, None)
            if name in self.edits:
                self.edits.pop(name, None)
                drop.append(name)
            if drop:
                self._save()

    def apply_edits(self, mapping):
        if not isinstance(mapping, dict):
            raise ValueError("edits must be a map of track names")
        changed = 0
        with self.lock:
            for raw_name, fields in mapping.items():
                name = str(raw_name or "").replace("\\", "/").lstrip("/")
                if not name or not isinstance(fields, dict):
                    continue
                cur = dict(self.edits.get(name) or {})
                for key in ("artist", "album", "genre", "title"):
                    if key not in fields:
                        continue
                    val = str(fields.get(key) or "").strip()[:80]
                    if val:
                        cur[key] = val
                    else:
                        cur.pop(key, None)
                if cur:
                    self.edits[name] = cur
                else:
                    self.edits.pop(name, None)
                changed += 1
            if changed:
                self._save()
        return changed


class Playlists(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.items = []
        self._load()

    def _load(self):
        try:
            with open(PLAYLIST_FILE, "r") as fh:
                data = json.load(fh)
            items = data.get("playlists") if isinstance(data, dict) else data
            if not isinstance(items, list):
                items = []
        except (OSError, ValueError, TypeError):
            items = []
        clean = []
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()[:80]
            tracks = item.get("tracks") if isinstance(item.get("tracks"), list) else []
            if not pid or not name:
                continue
            clean.append(
                {
                    "id": pid,
                    "name": name,
                    "tracks": [str(n) for n in tracks if n][:200],
                }
            )
        self.items = clean

    def _save_locked(self):
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            tmp = PLAYLIST_FILE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"playlists": self.items}, fh, indent=2)
                fh.write("\n")
            os.replace(tmp, PLAYLIST_FILE)
        except OSError:
            pass

    def list(self, valid_names=None):
        valid = set(valid_names) if valid_names is not None else None
        out = []
        changed = False
        with self.lock:
            for item in self.items:
                tracks = list(item["tracks"])
                if valid is not None:
                    keep = [n for n in tracks if n in valid]
                    if keep != tracks:
                        item["tracks"] = keep
                        tracks = keep
                        changed = True
                out.append(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "tracks": list(tracks),
                        "count": len(tracks),
                    }
                )
            if changed:
                self._save_locked()
        return out

    def get(self, pid):
        pid = str(pid or "").strip()
        with self.lock:
            for item in self.items:
                if item["id"] == pid:
                    return {
                        "id": item["id"],
                        "name": item["name"],
                        "tracks": list(item["tracks"]),
                        "count": len(item["tracks"]),
                    }
        return None

    def create(self, name):
        name = (name or "").strip()[:80]
        if not name:
            raise ValueError("need a playlist name")
        with self.lock:
            if len(self.items) >= 40:
                raise ValueError("playlist limit")
            pid = uuid.uuid4().hex[:8]
            self.items.append({"id": pid, "name": name, "tracks": []})
            self._save_locked()
            return {"id": pid, "name": name, "tracks": [], "count": 0}

    def rename(self, pid, name):
        name = (name or "").strip()[:80]
        if not name:
            raise ValueError("need a playlist name")
        with self.lock:
            for item in self.items:
                if item["id"] == pid:
                    item["name"] = name
                    self._save_locked()
                    return self._public(item)
        raise KeyError("unknown playlist")

    def delete(self, pid):
        with self.lock:
            before = len(self.items)
            self.items = [p for p in self.items if p["id"] != pid]
            if len(self.items) == before:
                raise KeyError("unknown playlist")
            self._save_locked()
        return True

    def add(self, pid, name):
        name = (name or "").strip()
        if not name:
            raise ValueError("need a track")
        with self.lock:
            for item in self.items:
                if item["id"] == pid:
                    if name not in item["tracks"]:
                        if len(item["tracks"]) >= 200:
                            raise ValueError("playlist is full")
                        item["tracks"].append(name)
                        self._save_locked()
                    return self._public(item)
        raise KeyError("unknown playlist")

    def remove_track(self, pid, name):
        name = (name or "").strip()
        with self.lock:
            for item in self.items:
                if item["id"] == pid:
                    item["tracks"] = [n for n in item["tracks"] if n != name]
                    self._save_locked()
                    return self._public(item)
        raise KeyError("unknown playlist")

    def remove_everywhere(self, name):
        name = (name or "").strip()
        with self.lock:
            changed = False
            for item in self.items:
                keep = [n for n in item["tracks"] if n != name]
                if keep != item["tracks"]:
                    item["tracks"] = keep
                    changed = True
            if changed:
                self._save_locked()

    def _public(self, item):
        return {
            "id": item["id"],
            "name": item["name"],
            "tracks": list(item["tracks"]),
            "count": len(item["tracks"]),
        }


CATALOG = Library()
PLAYLISTS = Playlists()
