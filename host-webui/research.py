#!/usr/bin/env python3
"""Internet research plugin for CRYPT track reports.

Looks up MusicBrainz and Wikipedia for the playing artist / song / album.
Python 3.8 stdlib only. No API keys. MusicBrainz asks for 1 request/sec.
"""
from __future__ import print_function

import json
import os
import re
import time

try:
    from urllib.parse import quote, urlencode
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import quote, urlencode
    from urllib2 import Request, urlopen

CLIENT = "CRYPT/2.1.0 (https://github.com/GeorgieTech/GIGAWATT-V2)"
MB = os.environ.get("CRYPT_MUSICBRAINZ", "https://musicbrainz.org/ws/2")
WIKI = os.environ.get("CRYPT_WIKI", "https://en.wikipedia.org")
try:
    PAUSE = max(0.0, min(2.0, float(os.environ.get("CRYPT_RESEARCH_PAUSE", "1.05"))))
except ValueError:
    PAUSE = 1.05


def _http_json(url, extra_headers=None):
    headers = {
        "User-Agent": CLIENT,
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    try:
        req = Request(url, headers=headers)
        fh = urlopen(req, timeout=8)
        try:
            raw = fh.read(250000)
        finally:
            fh.close()
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _year(text):
    m = re.search(r"(19|20)\d{2}", str(text or ""))
    return m.group(0) if m else ""


def _clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def sentences(text, n=2):
    text = _clean(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for part in parts:
        if part:
            out.append(part)
        if len(out) >= n:
            break
    return " ".join(out)


def _tag_names(items, limit=6):
    names = []
    seen = set()
    rows = items if isinstance(items, list) else []
    rows = sorted(rows, key=lambda t: -int((t or {}).get("count") or 0))
    for item in rows:
        name = _clean((item or {}).get("name"))
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
        if len(names) >= limit:
            break
    return names


class ResearchPlugin(object):
    """Fetch public facts about a recording. Inject `http` in tests."""

    def __init__(self, http=None, pause=None):
        self.http = http or _http_json
        self.pause = PAUSE if pause is None else pause

    def _get(self, url, extra=None):
        try:
            if extra:
                return self.http(url, extra)
            return self.http(url)
        except TypeError:
            return self.http(url)

    def _wait(self):
        if self.pause:
            time.sleep(self.pause)

    def gather(self, artist, title, album=""):
        artist = _clean(artist)
        title = _clean(title)
        album = _clean(album)
        if not title:
            return {"ok": False, "error": "no title", "sources": []}
        recording = self._recording(title, artist, album)
        self._wait()
        mb_artist = self._artist(artist) if artist else {}
        wiki_song = self._wikipedia(self._song_queries(title, artist, album))
        wiki_artist = self._wikipedia(self._artist_queries(artist)) if artist else {}
        sources = []
        for item in (recording, mb_artist, wiki_song, wiki_artist):
            url = (item or {}).get("url")
            label = (item or {}).get("source")
            if url and label:
                sources.append({"label": label, "url": url})
        return {
            "ok": True,
            "recording": recording,
            "artist_info": mb_artist,
            "wiki_song": wiki_song,
            "wiki_artist": wiki_artist,
            "sources": sources,
        }

    def _recording(self, title, artist, album):
        q = 'recording:"%s"' % title.replace('"', "")
        if artist:
            q += ' AND artist:"%s"' % artist.replace('"', "")
        url = MB.rstrip("/") + "/recording/?" + urlencode({
            "query": q,
            "fmt": "json",
            "limit": "5",
        })
        data = self._get(url)
        rows = (data or {}).get("recordings") if isinstance(data, dict) else None
        if not rows:
            return {}
        pick = rows[0]
        if album:
            al = album.lower()
            for row in rows:
                for rel in row.get("releases") or []:
                    if al in str((rel or {}).get("title") or "").lower():
                        pick = row
                        break
        releases = []
        for rel in pick.get("releases") or []:
            name = _clean((rel or {}).get("title"))
            date = _clean((rel or {}).get("date"))
            if name:
                releases.append({"title": name, "date": date, "year": _year(date)})
        mbid = pick.get("id") or ""
        year = _year(pick.get("first-release-date")) or (releases[0]["year"] if releases else "")
        length_ms = pick.get("length") or 0
        try:
            length_ms = int(length_ms)
        except (TypeError, ValueError):
            length_ms = 0
        return {
            "source": "MusicBrainz recording",
            "title": _clean(pick.get("title")) or title,
            "mbid": mbid,
            "year": year,
            "first_release": _clean(pick.get("first-release-date")),
            "length_ms": length_ms,
            "releases": releases[:4],
            "tags": _tag_names(pick.get("tags")),
            "url": ("https://musicbrainz.org/recording/" + mbid) if mbid else url,
        }

    def _artist(self, artist):
        url = MB.rstrip("/") + "/artist/?" + urlencode({
            "query": 'artist:"%s"' % artist.replace('"', ""),
            "fmt": "json",
            "limit": "3",
        })
        data = self._get(url)
        rows = (data or {}).get("artists") if isinstance(data, dict) else None
        if not rows:
            return {}
        pick = rows[0]
        area = ((pick.get("begin-area") or {}) if isinstance(pick.get("begin-area"), dict) else {})
        life = pick.get("life-span") or {}
        mbid = pick.get("id") or ""
        return {
            "source": "MusicBrainz artist",
            "name": _clean(pick.get("name")) or artist,
            "mbid": mbid,
            "type": _clean(pick.get("type")),
            "country": _clean(pick.get("country")),
            "begin_area": _clean(area.get("name")),
            "born": _year((life or {}).get("begin")),
            "ended": _year((life or {}).get("end")),
            "disambiguation": _clean(pick.get("disambiguation")),
            "tags": _tag_names(pick.get("tags")),
            "url": ("https://musicbrainz.org/artist/" + mbid) if mbid else url,
        }

    def _song_queries(self, title, artist, album):
        queries = []
        if artist:
            queries.append('%s %s song' % (title, artist))
            queries.append('"%s" (%s song)' % (title, artist))
        queries.append('%s song' % title)
        if album:
            queries.append('%s %s' % (title, album))
        return queries

    def _artist_queries(self, artist):
        return [
            '%s musician' % artist,
            '%s rapper' % artist,
            '%s singer' % artist,
            artist,
        ]

    def _wikipedia(self, queries):
        seen = set()
        for query in queries:
            query = _clean(query)
            if not query or query.lower() in seen:
                continue
            seen.add(query.lower())
            title = self._wiki_search(query)
            if not title:
                continue
            page = self._wiki_summary(title)
            if page:
                long_text = self._wiki_extract(page.get("title") or title)
                if long_text and len(long_text) > len(page.get("extract") or ""):
                    page["extract_long"] = long_text
                else:
                    page["extract_long"] = page.get("extract") or ""
                return page
        return {}

    def _wiki_search(self, query):
        url = WIKI.rstrip("/") + "/w/api.php?" + urlencode({
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": "5",
            "format": "json",
            "utf8": "1",
        })
        data = self._get(url)
        rows = ((data or {}).get("query") or {}).get("search") if isinstance(data, dict) else None
        if not rows:
            return ""
        for row in rows:
            title = _clean((row or {}).get("title"))
            snippet = _clean((row or {}).get("snippet"))
            blob = (title + " " + snippet).lower()
            if "disambiguation" in blob:
                continue
            if title:
                return title
        return _clean((rows[0] or {}).get("title"))

    def _wiki_summary(self, title):
        url = WIKI.rstrip("/") + "/api/rest_v1/page/summary/" + quote(title.replace(" ", "_"), safe="")
        data = self._get(url)
        if not isinstance(data, dict):
            return {}
        kind = str(data.get("type") or "")
        if kind == "disambiguation":
            return {}
        extract = _clean(data.get("extract"))
        if not extract:
            return {}
        page = ((data.get("content_urls") or {}).get("desktop") or {}).get("page") or ""
        thumb = ((data.get("thumbnail") or {}) if isinstance(data.get("thumbnail"), dict) else {})
        return {
            "source": "Wikipedia",
            "title": _clean(data.get("title")) or title,
            "description": _clean(data.get("description")),
            "extract": extract,
            "extract_long": extract,
            "url": page or url,
            "image": _clean(thumb.get("source")),
        }

    def _wiki_extract(self, title):
        url = WIKI.rstrip("/") + "/w/api.php?" + urlencode({
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "exsectionformat": "plain",
            "titles": title,
            "format": "json",
            "utf8": "1",
        })
        data = self._get(url)
        pages = ((data or {}).get("query") or {}).get("pages") if isinstance(data, dict) else None
        if not isinstance(pages, dict):
            return ""
        for page in pages.values():
            text = _clean((page or {}).get("extract"))
            if text:
                return text[:8000]
        return ""


PLUGIN = ResearchPlugin()
