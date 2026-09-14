#!/usr/bin/env python3
"""Cover Art Archive lookup, same idea as jellyfin-plugin-coverartarchive.

Local folder art and embedded pictures first, then MusicBrainz release
MBID → coverartarchive.org front thumbnail. Python 3.8 stdlib only.
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
    from urllib.parse import quote, urlencode
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import quote, urlencode
    from urllib2 import Request, urlopen

from player import MUSIC_DIR
from library import CATALOG, UNKNOWN_ARTIST, UNKNOWN_ALBUM, identity_from_path

COVER_DIR = os.environ.get("CRYPT_COVERS", "/data/crypt/covers")
INDEX_FILE = os.path.join(COVER_DIR, "index.json")
MB = os.environ.get("CRYPT_MUSICBRAINZ", "https://musicbrainz.org/ws/2")
CAA = os.environ.get("CRYPT_CAA", "https://coverartarchive.org")
CLIENT = "CRYPT/2.2.31 (https://github.com/GeorgieTech/GIGAWATT-V2)"
MAX_BYTES = 400 * 1024
MISSING_TTL = 7 * 24 * 3600
SIDECARS = (
    "cover.jpg", "cover.jpeg", "cover.png",
    "folder.jpg", "folder.jpeg", "folder.png",
    "AlbumArt.jpg", "AlbumArt.jpeg", "album.jpg",
    "front.jpg", "Front.jpg",
)
try:
    PAUSE = max(0.0, min(2.0, float(os.environ.get("CRYPT_COVER_PAUSE", "1.05"))))
except ValueError:
    PAUSE = 1.05


def album_key(artist, album, name=""):
    a = re.sub(r"\s+", " ", str(artist or "").strip().lower())
    b = re.sub(r"\s+", " ", str(album or "").strip().lower())
    if a in ("unknown artist",):
        a = ""
    if b in ("unknown album",):
        b = ""
    raw = ("%s|%s" % (a, b)).strip("|")
    if not raw:
        raw = str(name or "").replace("\\", "/").lstrip("/").lower()
    if not raw:
        return ""
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def pick_image(data):
    """Choose a Cover Art Archive front thumbnail, not the original scan."""
    if not isinstance(data, dict):
        return ""
    images = data.get("images") if isinstance(data.get("images"), list) else []
    fronts = []
    rest = []
    for item in images:
        if not isinstance(item, dict):
            continue
        types = item.get("types") or []
        if not isinstance(types, list):
            types = []
        if any(str(t).lower() == "front" for t in types) or item.get("front"):
            fronts.append(item)
        else:
            rest.append(item)
    for item in fronts or rest:
        thumbs = item.get("thumbnails") if isinstance(item.get("thumbnails"), dict) else {}
        for size in ("500", "large", "250", "small"):
            url = thumbs.get(size)
            if url:
                return str(url)
        url = item.get("image")
        if url:
            return str(url)
    return ""


def _ctype(raw):
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _http_json(url):
    try:
        req = Request(url, headers={"User-Agent": CLIENT, "Accept": "application/json"})
        fh = urlopen(req, timeout=10)
        try:
            raw = fh.read(250000)
        finally:
            fh.close()
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _http_bytes(url):
    try:
        req = Request(url, headers={"User-Agent": CLIENT, "Accept": "image/*,application/json"})
        fh = urlopen(req, timeout=14)
        try:
            raw = fh.read(MAX_BYTES + 1)
        finally:
            fh.close()
        if not raw or len(raw) > MAX_BYTES:
            return b"", ""
        kind = _ctype(raw)
        if not kind:
            return b"", ""
        return raw, kind
    except Exception:
        return b"", ""


def _ident(rel, artist="", album="", title=""):
    rel = (rel or "").replace("\\", "/").lstrip("/")
    artist = artist or ""
    album = album or ""
    title = title or ""
    if artist and album and title:
        return rel, artist, album, title
    probed = {}
    _rel, full = _join(rel)
    if full:
        try:
            from library import _probe_key
            st = os.stat(full)
            key = _probe_key(rel, st.st_size, int(st.st_mtime))
            with CATALOG.lock:
                probed = dict(CATALOG.cache.get(key) or {})
        except Exception:
            probed = {}
    ident = identity_from_path(rel, probed)
    return (
        rel,
        artist or ident.get("artist") or "",
        album or ident.get("album") or "",
        title or ident.get("title") or "",
    )


def _join(rel):
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return "", ""
    full = os.path.realpath(os.path.join(MUSIC_DIR, rel))
    base = os.path.realpath(MUSIC_DIR)
    if full != base and not full.startswith(base + os.sep):
        return rel, ""
    return rel, full


class CoverIndex(object):
    def __init__(self, folder=None, http_json=None, http_bytes=None, pause=None):
        self.folder = folder or COVER_DIR
        self.http_json = http_json or _http_json
        self.http_bytes = http_bytes or _http_bytes
        self.pause = PAUSE if pause is None else pause
        self.lock = threading.Lock()
        self.index = {}
        self.queue = []
        self.busy = set()
        self._caa_tried = set()
        self._load()
        self._alive = True
        self._thread = threading.Thread(target=self._loop, name="cover-caa")
        self._thread.daemon = True
        self._thread.start()

    def _path(self, key):
        return os.path.join(self.folder, key + ".img")

    def _load(self):
        try:
            with open(os.path.join(self.folder, "index.json"), "r") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                self.index = raw
        except (OSError, ValueError, TypeError):
            self.index = {}

    def _save(self):
        try:
            os.makedirs(self.folder, exist_ok=True)
            tmp = os.path.join(self.folder, "index.json.tmp")
            with open(tmp, "w") as fh:
                json.dump(self.index, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, os.path.join(self.folder, "index.json"))
        except OSError:
            pass

    def snapshot(self, rel, artist="", album="", title=""):
        rel, artist, album, title = _ident(rel, artist, album, title)
        key = album_key(artist, album, rel)
        row = self._row(key)
        found = bool(row.get("found") and os.path.isfile(self._path(key)))
        pending = rel in self.busy or rel in self.queue or (key and key in self.busy)
        return {
            "ok": True,
            "name": rel,
            "artist": artist,
            "album": album,
            "title": title,
            "id": key,
            "found": found,
            "pending": bool(pending and not found),
            "missing": bool(row.get("missing") and not found),
            "url": ("/api/cover/file?id=" + key) if found else "",
        }

    def decorate(self, tracks):
        out = []
        for t in tracks or []:
            row = dict(t)
            key = album_key(row.get("artist"), row.get("album"), row.get("name"))
            hit = self._row(key)
            if hit.get("found") and os.path.isfile(self._path(key)):
                row["cover"] = "/api/cover/file?id=" + key
            elif hit.get("missing"):
                row["cover_missing"] = True
            out.append(row)
        return out

    def file_for(self, key):
        key = re.sub(r"[^0-9a-f]", "", str(key or "").lower())
        if len(key) < 8:
            return "", ""
        path = self._path(key)
        if not os.path.isfile(path):
            return "", ""
        try:
            with open(path, "rb") as fh:
                raw = fh.read(16)
        except OSError:
            return "", ""
        return path, _ctype(raw) or "image/jpeg"

    def ensure(self, rel, front=False):
        rel = (rel or "").replace("\\", "/").lstrip("/")
        if not rel:
            return
        snap = self.snapshot(rel)
        if snap.get("found") or snap.get("missing"):
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

    def _row(self, key):
        if not key:
            return {}
        row = self.index.get(key)
        if not isinstance(row, dict):
            return {}
        if row.get("missing"):
            age = time.time() - float(row.get("at") or 0)
            if age > MISSING_TTL:
                return {}
        return row

    def _loop(self):
        while self._alive:
            rel = ""
            with self.lock:
                if self.queue:
                    rel = self.queue.pop(0)
                    self.busy.add(rel)
            if not rel:
                time.sleep(0.2)
                continue
            try:
                self._resolve(rel)
            except Exception:
                pass
            with self.lock:
                self.busy.discard(rel)
            if self.pause:
                time.sleep(self.pause)

    def _resolve(self, rel):
        rel, artist, album, title = _ident(rel)
        key = album_key(artist, album, rel)
        if not key:
            return
        if self._row(key).get("found") and os.path.isfile(self._path(key)):
            return
        raw, kind, deferred = self._local_bytes(rel)
        mbid = ""
        if not raw and key not in self._caa_tried:
            raw, kind, mbid = self._caa_bytes(artist, album, title)
            self._caa_tried.add(key)
        if raw and kind:
            self._caa_tried.discard(key)
            self._store(key, raw, kind, mbid, found=True)
            return
        if deferred:
            with self.lock:
                if rel not in self.queue:
                    self.queue.append(rel)
            return
        self._caa_tried.discard(key)
        self._store(key, b"", "", "", found=False)

    def _store(self, key, raw, kind, mbid, found):
        os.makedirs(self.folder, exist_ok=True)
        path = self._path(key)
        if found and raw:
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, path)
        elif not found:
            try:
                os.remove(path)
            except OSError:
                pass
        with self.lock:
            self.index[key] = {
                "found": bool(found),
                "missing": not bool(found),
                "ctype": kind,
                "mbid": mbid or "",
                "at": time.time(),
            }
            self._save()

    def _local_bytes(self, rel):
        """Return (bytes, ctype, deferred). deferred means ffmpeg skipped for wave CPU."""
        rel, full = _join(rel)
        if not full:
            return b"", "", False
        folder = os.path.dirname(full)
        for name in SIDECARS:
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as fh:
                    raw = fh.read(MAX_BYTES + 1)
            except OSError:
                continue
            if raw and len(raw) <= MAX_BYTES and _ctype(raw):
                return raw, _ctype(raw), False
        os.makedirs(self.folder, exist_ok=True)
        dest = os.path.join(self.folder, "extract-" + album_key("", "", rel) + ".img")
        try:
            from wave import WAVES
            with WAVES.lock:
                if WAVES.busy:
                    return b"", "", True
        except Exception:
            pass
        try:
            subprocess.check_call(
                [
                    "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", full, "-an", "-c:v", "copy", "-f", "image2", dest,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
            )
            with open(dest, "rb") as fh:
                raw = fh.read(MAX_BYTES + 1)
            kind = _ctype(raw)
            if raw and len(raw) <= MAX_BYTES and kind:
                return raw, kind, False
        except Exception:
            pass
        try:
            os.remove(dest)
        except OSError:
            pass
        return b"", "", False

    def _caa_bytes(self, artist, album, title):
        if (artist or "") in ("", UNKNOWN_ARTIST) and (album or "") in ("", UNKNOWN_ALBUM):
            return b"", "", ""
        mbid, group = self._musicbrainz_ids(artist, album, title)
        for kind, ident in (("release", mbid), ("release-group", group)):
            if not ident:
                continue
            data = self.http_json("%s/%s/%s" % (CAA.rstrip("/"), kind, ident))
            url = pick_image(data) if data else ""
            if not url:
                url = "%s/%s/%s/front-500" % (CAA.rstrip("/"), kind, ident)
            raw, ctype = self.http_bytes(url)
            if raw:
                return raw, ctype, ident
        return b"", "", mbid or group

    def _musicbrainz_ids(self, artist, album, title):
        q = []
        if album and album != UNKNOWN_ALBUM:
            q.append('release:"%s"' % album.replace('"', ""))
        elif title:
            q.append('recording:"%s"' % title.replace('"', ""))
        if artist and artist != UNKNOWN_ARTIST:
            q.append('artist:"%s"' % artist.replace('"', ""))
        if not q:
            return "", ""
        url = MB.rstrip("/") + "/release/?" + urlencode({
            "query": " AND ".join(q),
            "fmt": "json",
            "limit": "5",
        })
        data = self.http_json(url)
        rows = (data or {}).get("releases") if isinstance(data, dict) else None
        if not rows:
            return "", ""
        pick = rows[0]
        if album and album != UNKNOWN_ALBUM:
            al = album.lower()
            for row in rows:
                if al in str((row or {}).get("title") or "").lower():
                    pick = row
                    break
        mbid = str(pick.get("id") or "")
        group = ""
        rg = pick.get("release-group")
        if isinstance(rg, dict):
            group = str(rg.get("id") or "")
        return mbid, group


COVERS = CoverIndex()
