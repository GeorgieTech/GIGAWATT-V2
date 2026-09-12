#!/usr/bin/env python3
"""Gigawatt host-to-host library shelf and LAN discovery.

A viewer host lists another host's catalog over HTTP. Files stay on the
shelf. Play copies the track onto this box first (no NAS, no ffmpeg HTTP).
Linked hosts share libraries only. They do not play as a group.

Discovery: CRYPT/1 multicast on 239.18.20.1:41880 plus JSON broadcast
fallback and HTTP hello. Hosts are unique by Savant UID. Python 3.8 stdlib only.
"""
from __future__ import print_function

import json
import os
import socket
import threading
import time

try:
    from urllib.parse import quote, urlparse
    from urllib.request import Request, urlopen
except ImportError:
    from urllib import quote
    from urlparse import urlparse
    from urllib2 import Request, urlopen

from player import MUSIC_DIR
import crypt_wire

VERSION = "2.2.24"
PEERS_FILE = os.environ.get("CRYPT_PEERS", "/data/crypt/peers.json")
SEEN_FILE = os.environ.get("CRYPT_SEEN", "/data/crypt/seen.json")
HOT_FILE = os.environ.get("CRYPT_HOT", "/data/crypt/hot.json")
CLIENT = "CRYPT/%s (peer)" % VERSION
BLOCKED = ("192.168.1.40", "192.168.1.178", "192.168.1.180")
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")
MAX_COPY = int(os.environ.get("MAX_UPLOAD", str(400 * 1024 * 1024)))
BEACON_PORT = int(os.environ.get("CRYPT_BEACON", "41880"))
BEACON_TTL = 12
PROBE_TTL = 5
LAN_PREFIX = "192.168.1."
BROADCAST = "192.168.1.255"


def _self_id():
    return os.environ.get("CRYPT_ID") or socket.gethostname() or "crypt"


def _blocked(host):
    host = (host or "").split("%")[0].strip().lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    for bad in BLOCKED:
        if host == bad or host.endswith(bad):
            return True
    if host.startswith(LAN_PREFIX):
        return False
    return True


def _clean_url(url):
    url = str(url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    parsed = urlparse(url)
    if parsed.scheme != "http":
        return ""
    host = parsed.hostname or ""
    if _blocked(host):
        return ""
    port = parsed.port or 80
    if port != 80:
        return "http://%s:%s" % (host, port)
    return "http://%s" % host


def _keys_of(item):
    """Stable ids for a shelf or host row (uid, url, ip, hostname)."""
    item = item or {}
    url = str(item.get("url") or "").strip()
    host = ""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    bits = [
        item.get("id"),
        item.get("uid"),
        url,
        host,
        item.get("ip"),
        _uid_from(item.get("id") or ""),
        _uid_from(item.get("uid") or ""),
    ]
    out = []
    seen = set()
    for bit in bits:
        key = str(bit or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _norm_keys(items):
    out = []
    seen = set()
    for item in items or []:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _valid_uid(s):
    s = str(s or "").strip().upper().replace(":", "")
    if len(s) < 12 or len(s) > 16:
        return ""
    for ch in s:
        if ch not in "0123456789ABCDEF":
            return ""
    return s


def _uid_from(name):
    s = str(name or "").strip()
    if not s:
        return ""
    low = s.lower()
    for prefix in ("sav-", "crypt-", "gwh-"):
        if low.startswith(prefix):
            return _valid_uid(s[len(prefix):])
    return _valid_uid(s)


def _model():
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as fh:
                raw = fh.read().split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
            if raw:
                return raw
        except OSError:
            pass
    return os.environ.get("CRYPT_MODEL") or "SHR-S2-00"


def _if_ip(name):
    try:
        import fcntl
        import struct
    except ImportError:
        return ""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        packed = struct.pack("256s", name.encode("utf-8")[:15])
        info = fcntl.ioctl(sock.fileno(), 0x8915, packed)
        return socket.inet_ntoa(info[20:24])
    except OSError:
        return ""
    finally:
        sock.close()


def _lan_ip():
    names = ["eth0"]
    try:
        names.extend(sorted(os.listdir("/sys/class/net")))
    except OSError:
        pass
    seen = set()
    for name in names:
        if not name or name in seen or name == "lo" or name.startswith("wlan") or name.startswith("dummy"):
            continue
        seen.add(name)
        ip = _if_ip(name)
        if ip and ip.startswith(LAN_PREFIX) and not _blocked(ip):
            return ip
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.168.1.1", 1))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
        if ip and ip.startswith(LAN_PREFIX) and not _blocked(ip):
            return ip
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip.startswith(LAN_PREFIX) and not _blocked(ip):
            return ip
    except OSError:
        pass
    return ""


_IDENT_TTL = 5.0
_ident_cache = {"t": 0.0, "row": None}


def identity():
    now = time.time()
    hit = _ident_cache.get("row")
    if hit and now - float(_ident_cache.get("t") or 0) < _IDENT_TTL:
        row = dict(hit)
        row["version"] = VERSION
        return row
    host = socket.gethostname() or "crypt"
    ip = _lan_ip()
    uid = _uid_from(host)
    row = {
        "crypt": 1,
        "id": _self_id(),
        "uid": uid,
        "host": host,
        "ip": ip,
        "url": ("http://%s" % ip) if ip else "",
        "model": _model(),
        "version": VERSION,
    }
    _ident_cache["t"] = now
    _ident_cache["row"] = dict(row)
    return row


def load_config(path=None):
    path = path or PEERS_FILE
    data = {}
    try:
        with open(path, "r") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            data = raw
    except (OSError, ValueError, TypeError):
        data = {}
    shelves = []
    seen = set()
    extra = os.environ.get("CRYPT_SHELVES") or ""
    listed = list(data.get("shelves") or [])
    if extra:
        listed.extend([{"url": bit} for bit in extra.split(",") if bit.strip()])
    for item in listed:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        url = _clean_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        sid = str(item.get("id") or urlparse(url).hostname or url)
        shelves.append({"id": sid, "url": url, "uid": str(item.get("uid") or _uid_from(sid))})
    return {
        "id": str(data.get("id") or _self_id()),
        "shelves": shelves,
        "declined": _norm_keys(data.get("declined")),
    }


def save_config(cfg, path=None):
    path = path or PEERS_FILE
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    payload = {
        "id": str((cfg or {}).get("id") or _self_id()),
        "shelves": [],
        "declined": _norm_keys((cfg or {}).get("declined")),
    }
    seen = set()
    for item in (cfg or {}).get("shelves") or []:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue
        url = _clean_url(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        sid = str(item.get("id") or urlparse(url).hostname or url)
        payload["shelves"].append({
            "id": sid,
            "url": url,
            "uid": str(item.get("uid") or _uid_from(sid)),
        })
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass
    return payload


def stamp(uid_or_id):
    uid = _uid_from(uid_or_id) or ""
    if not uid:
        uid = str(uid_or_id or "").strip().upper().replace(":", "")
    core = uid.rstrip("0") or uid
    if len(core) >= 4:
        return core[-4:]
    return uid[-4:] if len(uid) >= 4 else uid


def _http_send(url, timeout=4, data=None):
    headers = {"User-Agent": CLIENT, "Accept": "application/json"}
    raw = None
    if data is not None:
        raw = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=raw, headers=headers)
    fh = urlopen(req, timeout=timeout)
    try:
        body = fh.read(2 * 1024 * 1024)
    finally:
        fh.close()
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))


def _http_json(url, timeout=4):
    return _http_send(url, timeout=timeout)


def _http_post(url, data, timeout=8):
    return _http_send(url, timeout=timeout, data=data or {})


def _safe_rel(name):
    rel = (name or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return ""
    ext = os.path.splitext(rel)[1].lower()
    if ext not in AUDIO_EXT:
        return ""
    return rel


def _blank_host():
    return {
        "id": "",
        "uid": "",
        "host": "",
        "ip": "",
        "url": "",
        "model": "",
        "version": "",
        "self": False,
        "online": False,
        "linked": False,
        "sees_us": False,
        "lists_us": False,
        "tracks": 0,
        "playing": False,
        "unison": False,
        "now": "",
        "rtt_ms": None,
        "last_seen": 0,
        "via": [],
        "error": "",
    }


def _as_host(data, **extra):
    row = _blank_host()
    src = dict(data or {})
    src.update(extra)
    url = _clean_url(src.get("url") or "")
    ip = str(src.get("ip") or "")
    if not ip and url:
        ip = urlparse(url).hostname or ""
    if ip and _blocked(ip):
        return None
    if url and not ip:
        ip = urlparse(url).hostname or ""
    hid = str(src.get("id") or src.get("host") or "")
    uid = _uid_from(src.get("uid") or hid or src.get("host") or "")
    if not url and ip:
        url = "http://%s" % ip
    row["id"] = hid or uid or ip or url
    row["uid"] = uid
    row["host"] = str(src.get("host") or hid or "")
    row["ip"] = ip
    row["url"] = url
    row["model"] = str(src.get("model") or "")
    row["version"] = str(src.get("version") or "")
    row["self"] = bool(src.get("self"))
    row["online"] = bool(src.get("online"))
    row["linked"] = bool(src.get("linked"))
    row["sees_us"] = bool(src.get("sees_us"))
    row["lists_us"] = bool(src.get("lists_us"))
    try:
        row["tracks"] = int(src.get("tracks") or 0)
    except (TypeError, ValueError):
        row["tracks"] = 0
    row["playing"] = bool(src.get("playing"))
    row["unison"] = bool(src.get("unison"))
    row["now"] = str(src.get("now") or "")
    rtt = src.get("rtt_ms")
    try:
        row["rtt_ms"] = None if rtt in (None, "") else int(rtt)
    except (TypeError, ValueError):
        row["rtt_ms"] = None
    try:
        row["last_seen"] = float(src.get("last_seen") or 0)
    except (TypeError, ValueError):
        row["last_seen"] = 0
    via = src.get("via") or []
    if isinstance(via, str):
        via = [via]
    row["via"] = [str(v) for v in via if v]
    row["error"] = str(src.get("error") or "")
    return row


def _same(a, b):
    if not a or not b:
        return False
    if a.get("uid") and b.get("uid") and a["uid"] == b["uid"]:
        return True
    if a.get("id") and b.get("id") and a["id"] == b["id"]:
        return True
    if a.get("ip") and b.get("ip") and a["ip"] == b["ip"]:
        return True
    if a.get("url") and b.get("url") and a["url"] == b["url"]:
        return True
    return False


def _merge_host(dst, src):
    if not dst:
        return dict(src)
    if not src:
        return dst
    out = dict(dst)
    for key in ("id", "uid", "host", "ip", "url", "model", "version", "now", "error"):
        if src.get(key) and (not out.get(key) or key in ("model", "version", "now", "error")):
            if src.get(key):
                out[key] = src[key]
    for flag in ("self", "online", "linked", "sees_us", "lists_us"):
        out[flag] = bool(out.get(flag) or src.get(flag))
    # Live play flags: newest last_seen wins. Do not sticky-OR — a later
    # beacon with playing=0 must clear the roster bit.
    src_seen = float(src.get("last_seen") or 0)
    out_seen = float(out.get("last_seen") or 0)
    if src_seen >= out_seen:
        out["playing"] = bool(src.get("playing"))
        out["unison"] = bool(src.get("unison"))
    if int(src.get("tracks") or 0) > int(out.get("tracks") or 0):
        out["tracks"] = int(src.get("tracks") or 0)
    try:
        lv = int(src.get("libver") or 0)
        if lv:
            out["libver"] = lv
    except (TypeError, ValueError):
        pass
    rtt = src.get("rtt_ms")
    if rtt is not None and (out.get("rtt_ms") is None or rtt < out["rtt_ms"]):
        out["rtt_ms"] = rtt
    out["last_seen"] = max(float(out.get("last_seen") or 0), float(src.get("last_seen") or 0))
    via = []
    for item in list(out.get("via") or []) + list(src.get("via") or []):
        if item and item not in via:
            via.append(item)
    out["via"] = via
    if src.get("error") and not out.get("online"):
        out["error"] = src.get("error")
    if out.get("online"):
        out["error"] = ""
    return out


def _fold_hosts(rows):
    folded = []
    for row in rows:
        if not row:
            continue
        hit = None
        for existing in folded:
            if _same(existing, row):
                hit = existing
                break
        if hit is None:
            folded.append(dict(row))
        else:
            merged = _merge_host(hit, row)
            hit.clear()
            hit.update(merged)
    return folded


class PeerIndex(object):
    def __init__(self, path=None, http=None, seen_path=None, hot_path=None):
        self.path = path or PEERS_FILE
        self.seen_path = seen_path or SEEN_FILE
        self.hot_path = hot_path or HOT_FILE
        self.http = http or _http_json
        self.lock = threading.Lock()
        self._cfg = load_config(self.path)
        self._remote = {}
        self._seen = {}
        self._probe = {}
        self._candidates = set()
        self._hot = set()
        self._alive = False
        self._thread = None
        self._sock = None
        self.beacon_ok = False
        self.beacon_error = ""
        self.igmp_ok = False
        self.igmp_error = ""
        self.error = ""
        self._own_libver = 0
        self._own_tracks = 0
        self.player = None
        self._pending_evict = []
        self._load_seen()
        self._load_hot()
        self._scrub_declined()

    def reload(self):
        self._cfg = load_config(self.path)
        return self._cfg

    def config(self):
        return dict(self._cfg)

    def snapshot(self):
        cfg = self.config()
        rows = []
        for shelf in cfg.get("shelves") or []:
            rows.append({"id": shelf["id"], "url": shelf["url"], "uid": shelf.get("uid") or ""})
        return {"id": cfg.get("id"), "shelves": rows}

    def note_local_catalog(self, tracks):
        self._own_libver = crypt_wire.libver(tracks)
        self._own_tracks = len(tracks or [])
        return self._own_libver

    def hello(self, extra=None):
        me = identity()
        hid = self.config().get("id") or me["id"]
        payload = {
            "ok": True,
            "crypt": 1,
            "id": hid,
            "uid": me["uid"] or _uid_from(hid),
            "host": me["host"],
            "ip": me["ip"],
            "url": me["url"],
            "model": me["model"],
            "version": VERSION,
            "shelves": self.snapshot().get("shelves") or [],
            "seen": self.seen_public(),
        }
        extra = extra or {}
        for key in ("tracks", "playing", "now"):
            if key in extra:
                payload[key] = extra[key]
        return payload

    def _declined_keys(self):
        return set((self.config() or {}).get("declined") or [])

    def _is_declined(self, item):
        declined = self._declined_keys()
        if not declined:
            return False
        return any(bit in declined for bit in _keys_of(item))

    def seen_public(self):
        now = time.time()
        out = []
        with self.lock:
            rows = list(self._seen.values())
        for row in rows:
            if now - float(row.get("last_seen") or 0) > BEACON_TTL * 4:
                continue
            if _blocked(row.get("ip") or ""):
                continue
            if self._is_declined(row):
                continue
            out.append({
                "id": row.get("id") or "",
                "uid": row.get("uid") or "",
                "ip": row.get("ip") or "",
                "url": row.get("url") or "",
                "model": row.get("model") or "",
            })
            if len(out) >= 12:
                break
        return out

    def _load_seen(self):
        try:
            with open(self.seen_path, "r") as fh:
                raw = json.load(fh)
        except (OSError, ValueError, TypeError):
            return
        rows = raw.get("hosts") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return
        for item in rows:
            host = _as_host(item, via=["remembered"])
            if not host or not host.get("uid"):
                continue
            host["online"] = False
            self._remember(host, persist=False)

    def _load_hot(self):
        try:
            with open(self.hot_path, "r") as fh:
                raw = json.load(fh)
        except (OSError, ValueError, TypeError):
            self._hot = set()
            return
        names = raw.get("names") if isinstance(raw, dict) else raw
        if not isinstance(names, list):
            self._hot = set()
            return
        self._hot = set(str(n) for n in names if n)

    def _persist_hot(self):
        folder = os.path.dirname(self.hot_path)
        if folder:
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError:
                return
        tmp = self.hot_path + ".tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump({"names": sorted(self._hot)}, fh)
            os.replace(tmp, self.hot_path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def is_hot(self, name):
        rel = (name or "").replace("\\", "/").lstrip("/")
        return rel in self._hot

    def mark_hot(self, name):
        rel = (name or "").replace("\\", "/").lstrip("/")
        if not rel or rel in self._hot:
            return
        self._hot.add(rel)
        self._persist_hot()

    def drop_hot(self, name):
        rel = (name or "").replace("\\", "/").lstrip("/")
        if not rel or rel not in self._hot:
            return
        self._hot.discard(rel)
        self._persist_hot()

    def _persist_seen(self):
        folder = os.path.dirname(self.seen_path)
        if folder:
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError:
                return
        rows = []
        with self.lock:
            items = list(self._seen.values())
        declined = set((self.config() or {}).get("declined") or [])
        items.sort(key=lambda r: float(r.get("last_seen") or 0), reverse=True)
        for row in items:
            if any(bit in declined for bit in _keys_of(row)):
                continue
            if len(rows) >= 16:
                break
            rows.append({
                "id": row.get("id") or "",
                "uid": row.get("uid") or "",
                "ip": row.get("ip") or "",
                "url": row.get("url") or "",
                "model": row.get("model") or "",
                "last_seen": row.get("last_seen") or 0,
            })
        tmp = self.seen_path + ".tmp"
        try:
            with open(tmp, "w") as fh:
                json.dump({"hosts": rows}, fh)
            os.replace(tmp, self.seen_path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _remember(self, host, persist=True):
        if not host or host.get("self"):
            return
        ip = host.get("ip") or ""
        if ip and _blocked(ip):
            return
        host = dict(host)
        with self.lock:
            hit = None
            for existing in self._seen.values():
                if _same(existing, host):
                    hit = existing
                    break
            if hit is None:
                key = host.get("uid") or host.get("id") or host.get("ip") or host.get("url")
                if not key:
                    return
                self._seen[key] = host
            else:
                merged = _merge_host(hit, host)
                hit.clear()
                hit.update(merged)
        if persist and not self._is_declined(host):
            self._persist_seen()

    def note_client(self, ip, ua=""):
        ip = (ip or "").split("%")[0].strip()
        if _blocked(ip) or not str(ua or "").startswith("CRYPT/"):
            return
        me = identity()
        if ip == me.get("ip"):
            return
        with self.lock:
            self._candidates.add(ip)

    def note_beacon(self, payload, addr_ip, now=None):
        if not isinstance(payload, dict) or payload.get("crypt") != 1:
            return None
        ip = (addr_ip or "").split("%")[0].strip()
        if _blocked(ip):
            return None
        me = identity()
        uid = _uid_from(payload.get("uid") or payload.get("id") or payload.get("host") or "")
        if not uid:
            return None
        if ip == me.get("ip") or uid == me.get("uid"):
            return None
        host = _as_host({
            "id": payload.get("id"),
            "uid": uid,
            "host": payload.get("host"),
            "ip": ip,
            "url": "http://%s" % ip,
            "model": payload.get("model"),
            "version": payload.get("version") or payload.get("v"),
            "online": True,
            "last_seen": now if now is not None else time.time(),
            "via": ["beacon"],
            "tracks": payload.get("tracks") or 0,
            "playing": bool(payload.get("playing")),
            "unison": bool(payload.get("unison")),
        })
        if host is not None:
            try:
                host["libver"] = int(payload.get("libver") or 0)
            except (TypeError, ValueError):
                host["libver"] = 0
        self._remember(host)
        return host

    def fetch_shelf(self, shelf):
        url = shelf.get("url") or ""
        if not url:
            return [], "no url"
        now = time.time()
        host = urlparse(url).hostname or ""
        announced = None
        with self.lock:
            for row in self._seen.values():
                if row.get("url") == url or row.get("ip") == host:
                    try:
                        announced = int(row.get("libver") or 0) or None
                    except (TypeError, ValueError):
                        announced = None
                    break
        hit = self._remote.get(url)
        cached_ver = None
        if hit:
            try:
                cached_ver = hit[3]
            except (IndexError, TypeError):
                cached_ver = None
        if hit and announced and cached_ver == announced and not hit[2]:
            return hit[1], ""
        # libver is the ETag. A new advertised fingerprint bypasses the
        # success TTL so a catalog change is visible on the next poll.
        if announced and cached_ver is not None and cached_ver != announced:
            pass
        elif hit and now - hit[0] < (2 if hit[2] else 8):
            return hit[1], hit[2]
        try:
            try:
                data = self.http(url + "/api/library?local=1", timeout=6)
            except TypeError:
                data = self.http(url + "/api/library?local=1")
            err = ""
            tracks = []
            if not isinstance(data, dict) or not data.get("ok"):
                err = "bad library"
            else:
                tracks = data.get("tracks") or []
                if not isinstance(tracks, list):
                    tracks, err = [], "bad tracks"
        except Exception as exc:
            tracks, err = [], str(exc)
        fingerprint = crypt_wire.libver(tracks) if tracks else (announced or 0)
        self._remote[url] = (now, tracks, err, fingerprint)
        return tracks, err

    def url_for_owner(self, owner):
        owner = str(owner or "")
        if not owner:
            return ""
        cfg = self.config()
        if owner == cfg.get("id"):
            return ""
        for shelf in cfg.get("shelves") or []:
            host = urlparse(shelf.get("url") or "").hostname or ""
            if owner in (shelf.get("id"), shelf.get("url"), host, shelf.get("uid")):
                return shelf.get("url")
        return ""

    def _decorate(self, row, owner_id, owner_uid, here):
        row["owner"] = owner_id or ""
        row["owner_uid"] = owner_uid or _uid_from(owner_id) or ""
        row["home_stamp"] = stamp(row["owner_uid"] or owner_id)
        row["here"] = bool(here)
        return row

    def tag_local(self, tracks):
        cfg = self.config()
        me = identity()
        self_id = cfg.get("id") or me.get("id") or _self_id()
        self_uid = me.get("uid") or _uid_from(self_id)
        out = []
        for t in tracks or []:
            name = (t or {}).get("name")
            if not name:
                continue
            row = dict(t)
            home = not self.is_hot(name) if row.get("home") is None else bool(row.get("home"))
            row["local"] = True
            row["available"] = True
            row["home"] = home
            if home:
                self._decorate(row, self_id, self_uid, True)
            else:
                row["here"] = False
                row["owner"] = row.get("owner") or ""
                row["owner_uid"] = row.get("owner_uid") or ""
                row["home_stamp"] = stamp(row.get("owner_uid") or row.get("owner") or "")
            out.append(row)
        return out

    def merge(self, local_tracks):
        cfg = self.config()
        me = identity()
        self_id = cfg.get("id") or me.get("id") or _self_id()
        self_uid = me.get("uid") or _uid_from(self_id)
        by = {}
        for t in self.tag_local(local_tracks):
            by[t["name"]] = t
        errors = []
        for shelf in cfg.get("shelves") or []:
            tracks, err = self.fetch_shelf(shelf)
            if err:
                errors.append("%s: %s" % (shelf.get("id"), err))
                continue
            shelf_id = shelf.get("id") or shelf.get("url")
            shelf_uid = shelf.get("uid") or _uid_from(shelf_id)
            for t in tracks:
                name = (t or {}).get("name")
                if not name:
                    continue
                remote_home = True if t.get("home") is None else bool(t.get("home"))
                remote_owner = t.get("owner") or shelf_id
                remote_uid = t.get("owner_uid") or (shelf_uid if remote_owner in (shelf_id, shelf.get("url")) else _uid_from(remote_owner))
                if name in by:
                    cur = by[name]
                    cur["local"] = True
                    cur["available"] = True
                    if remote_home and not cur.get("home"):
                        self._decorate(cur, remote_owner, remote_uid, False)
                        cur["home"] = False
                    elif remote_home and cur.get("home"):
                        same_size = False
                        try:
                            same_size = int(cur.get("size") or 0) == int(t.get("size") or 0)
                        except (TypeError, ValueError):
                            same_size = False
                        if same_size and int(t.get("size") or 0) > 0:
                            # Linked display can stamp the shelf as home. Do not
                            # mark this chassis's own file hot — unlink must not
                            # delete originals that were uploaded here.
                            self._decorate(cur, remote_owner, remote_uid, False)
                            cur["home"] = False
                    if not cur.get("title") and t.get("title"):
                        cur["title"] = t.get("title")
                    if not cur.get("artist") and t.get("artist"):
                        cur["artist"] = t.get("artist")
                    if not cur.get("album") and t.get("album"):
                        cur["album"] = t.get("album")
                    continue
                row = dict(t)
                row["local"] = False
                row["available"] = True
                row["home"] = False
                if remote_home:
                    self._decorate(row, remote_owner, remote_uid, False)
                else:
                    self._decorate(row, remote_owner, remote_uid, False)
                by[name] = row
        self.error = "; ".join(errors)
        out = list(by.values())
        out.sort(key=lambda t: (
            str(t.get("artist") or "").lower(),
            str(t.get("album") or "").lower(),
            t.get("track") or 9999,
            str(t.get("title") or "").lower(),
            str(t.get("name") or "").lower(),
        ))
        return out

    def owner_url(self, name, owner=None):
        url = self.url_for_owner(owner)
        if url:
            return url
        cfg = self.config()
        for shelf in cfg.get("shelves") or []:
            tracks, err = self.fetch_shelf(shelf)
            if err:
                continue
            for t in tracks:
                if (t or {}).get("name") == name:
                    return shelf.get("url")
        return ""

    def ensure(self, name, owner=None):
        """Copy a remote track into MUSIC_DIR if it is not already here."""
        rel = _safe_rel(name)
        if not rel:
            return False
        dest = os.path.join(MUSIC_DIR, rel)
        if os.path.isfile(dest):
            return True
        url = self.owner_url(rel, owner=owner)
        if not url:
            return False
        folder = os.path.dirname(dest)
        if folder:
            os.makedirs(folder, exist_ok=True)
        media = url + "/api/media?name=" + quote(rel)
        tmp = dest + ".part"
        try:
            req = Request(media, headers={"User-Agent": CLIENT})
            fh = urlopen(req, timeout=30)
            try:
                written = 0
                with open(tmp, "wb") as out:
                    while True:
                        chunk = fh.read(256 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_COPY:
                            raise IOError("too large")
                        out.write(chunk)
            finally:
                fh.close()
            if written <= 0:
                raise IOError("empty")
            os.replace(tmp, dest)
            os.chmod(dest, 0o644)
            self.mark_hot(rel)
            return True
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def _mine(self, me):
        me = me or identity()
        cfg = self.config()
        return set(filter(None, [
            me.get("id"), me.get("uid"), me.get("ip"), me.get("host"), me.get("url"),
            cfg.get("id"),
        ]))

    def _lists_us_as_shelf(self, data, me):
        if not isinstance(data, dict):
            return False
        mine = self._mine(me)
        for shelf in data.get("shelves") or []:
            if not isinstance(shelf, dict):
                continue
            bits = [shelf.get("id"), shelf.get("uid"), shelf.get("url"), urlparse(shelf.get("url") or "").hostname]
            for bit in bits:
                if bit and bit in mine:
                    return True
        return False

    def _points_at_us(self, data, me):
        if self._lists_us_as_shelf(data, me):
            return True
        if not isinstance(data, dict):
            return False
        mine = self._mine(me)
        for seen in data.get("seen") or []:
            if not isinstance(seen, dict):
                continue
            bits = [seen.get("id"), seen.get("uid"), seen.get("ip"), seen.get("url")]
            for bit in bits:
                if bit and bit in mine:
                    return True
        return False

    def probe_url(self, url, now=None, force=False):
        url = _clean_url(url)
        if not url:
            return None, "bad url"
        now = now if now is not None else time.time()
        hit = self._probe.get(url)
        if not force and hit and now - hit[0] < PROBE_TTL:
            return hit[1], hit[2]
        t0 = time.time()
        try:
            data = self.http(url + "/api/hello")
            rtt = int((time.time() - t0) * 1000)
            if not isinstance(data, dict) or data.get("crypt") != 1:
                err = "not CRYPT"
                self._probe[url] = (now, None, err)
                return None, err
            me = identity()
            host = _as_host({
                "id": data.get("id"),
                "uid": data.get("uid"),
                "host": data.get("host"),
                "ip": urlparse(url).hostname or data.get("ip"),
                "url": url,
                "model": data.get("model"),
                "version": data.get("version"),
                "tracks": data.get("tracks"),
                "playing": data.get("playing"),
                "now": data.get("now"),
                "online": True,
                "sees_us": self._points_at_us(data, me),
                "lists_us": self._lists_us_as_shelf(data, me),
                "rtt_ms": rtt,
                "last_seen": now,
                "via": ["hello"],
            })
            self._remember(host)
            gossip = []
            for item in (data.get("seen") or []) + (data.get("shelves") or []):
                if not isinstance(item, dict):
                    continue
                other = _as_host(item, via=["gossip"], last_seen=now)
                if other and other.get("uid") and not _same(other, _as_host(me, self=True)):
                    gossip.append(other)
                    self._remember(other)
            host["_gossip"] = gossip
            self._probe[url] = (now, host, "")
            return host, ""
        except Exception as exc:
            err = str(exc)
            self._probe[url] = (now, None, err)
            return None, err

    def roster(self, probe=False, extra=None, force=False):
        now = time.time()
        me = identity()
        extra = extra or {}
        cfg = self.config()
        self_row = _as_host(me, self=True, online=True, last_seen=now, via=["self"],
                            tracks=extra.get("tracks") or 0,
                            playing=extra.get("playing") or False,
                            now=extra.get("now") or "")
        self_row["id"] = cfg.get("id") or self_row.get("id")
        rows = [self_row]
        for shelf in cfg.get("shelves") or []:
            rows.append(_as_host(shelf, linked=True, via=["shelf"]))
        declined = set(cfg.get("declined") or [])
        with self.lock:
            remembered = [dict(v) for v in self._seen.values()]
        for row in remembered:
            age = now - float(row.get("last_seen") or 0)
            row["online"] = age <= BEACON_TTL
            if declined and any(bit in declined for bit in _keys_of(row)):
                if age > BEACON_TTL:
                    continue
            rows.append(row)
        urls = []
        if probe:
            for row in rows:
                if row.get("self"):
                    continue
                url = row.get("url") or ""
                if url and url not in urls:
                    urls.append(url)
            with self.lock:
                cands = list(self._candidates)
            for ip in cands:
                url = "http://%s" % ip
                if url not in urls:
                    urls.append(url)
            confirmed = set()
            for url in urls:
                found, err = self.probe_url(url, now=now, force=force)
                if found:
                    rows.append(found)
                    confirmed.add(urlparse(url).hostname or "")
                    for item in found.get("_gossip") or []:
                        rows.append(item)
                elif err:
                    host = urlparse(url).hostname or ""
                    linked = any((r.get("url") == url or r.get("ip") == host) and r.get("linked") for r in rows)
                    if linked:
                        rows.append(_as_host({"url": url, "ip": host, "error": err, "via": ["hello"], "online": False}))
            with self.lock:
                self._candidates = set(ip for ip in self._candidates if ip not in confirmed)
        folded = _fold_hosts(rows)
        shelf_keys = set()
        for item in cfg.get("shelves") or []:
            shelf_keys.update(_keys_of(item))
        out = []
        for row in folded:
            row.pop("_gossip", None)
            if row.get("self"):
                row["online"] = True
                row["linked"] = False
                out.append(row)
                continue
            row["linked"] = any(k in shelf_keys for k in _keys_of(row))
            age = now - float(row.get("last_seen") or 0)
            confirmed = bool(row.get("uid") or row.get("linked") or "beacon" in (row.get("via") or []) or "hello" in (row.get("via") or []))
            if not confirmed:
                continue
            if age <= BEACON_TTL and ("beacon" in (row.get("via") or []) or "hello" in (row.get("via") or [])):
                row["online"] = True
            elif age > BEACON_TTL:
                row["online"] = False
            out.append(row)
        out.sort(key=lambda r: (
            0 if r.get("self") else 1,
            0 if r.get("linked") else 1,
            0 if r.get("online") else 1,
            str(r.get("uid") or r.get("id") or "").lower(),
        ))
        return out

    def summary(self, extra=None):
        hosts = self.roster(probe=False, extra=extra)
        return {
            "online": sum(1 for h in hosts if h.get("online")),
            "linked": sum(1 for h in hosts if h.get("linked") and not h.get("self")),
            "count": len(hosts),
        }

    def fleet(self, probe=False, extra=None, force=False):
        hosts = self.roster(probe=probe, extra=extra, force=force)
        return {
            "ok": True,
            "crypt": 1,
            "version": VERSION,
            "self": identity(),
            "hosts": hosts,
            "online": sum(1 for h in hosts if h.get("online")),
            "linked": sum(1 for h in hosts if h.get("linked") and not h.get("self")),
            "beacon": {
                "port": BEACON_PORT,
                "listening": bool(self.beacon_ok),
                "error": self.beacon_error,
                "igmp_ok": bool(self.igmp_ok),
                "igmp_error": self.igmp_error,
            },
            "error": self.error,
        }

    def link(self, url, notify=True):
        url = _clean_url(url)
        if not url:
            return False, "blocked or bad url"
        me = identity()
        if urlparse(url).hostname in (me.get("ip"), "127.0.0.1"):
            return False, "cannot link this chassis"
        found, err = self.probe_url(url, now=time.time())
        sid = (found or {}).get("id") or urlparse(url).hostname or url
        uid = (found or {}).get("uid") or _uid_from(sid)
        cfg = load_config(self.path)
        shelves = []
        seen = set()
        for item in cfg.get("shelves") or []:
            item_url = item.get("url")
            if item_url in seen:
                continue
            seen.add(item_url)
            shelves.append(item)
        added = url not in seen
        if added:
            shelves.append({"id": sid, "url": url, "uid": uid})
        drop_keys = set(_keys_of({"id": sid, "url": url, "uid": uid, "ip": urlparse(url).hostname}))
        declined = [bit for bit in (cfg.get("declined") or []) if bit not in drop_keys]
        cfg["id"] = cfg.get("id") or me.get("id")
        cfg["shelves"] = shelves
        cfg["declined"] = declined
        save_config(cfg, self.path)
        self.reload()
        if found:
            found["linked"] = True
            self._remember(found)
        if notify and added:
            our = me.get("url") or (("http://%s" % me["ip"]) if me.get("ip") else "")
            if our:
                try:
                    _http_post(url + "/api/fleet", {"action": "link", "url": our, "notify": False}, timeout=6)
                except Exception:
                    pass
        return True, ""

    def hot_copies_for_shelf(self, shelf, last=False):
        """Names copied here from a shelf. Last remaining shelf: every hot copy."""
        names = set(self._hot)
        if last:
            return sorted(names)
        url = (shelf or {}).get("url")
        hit = self._remote.get(url) if url else None
        remote = set()
        if hit and isinstance(hit[1], list):
            for t in hit[1]:
                if t and t.get("name"):
                    remote.add(t.get("name"))
        if remote:
            return sorted(n for n in names if n in remote)
        return []

    def take_pending_evict(self):
        names = list(self._pending_evict or [])
        self._pending_evict = []
        return names

    def purge_unlinked_hot(self):
        """If no shelves, every hot copy is foreign leftover. Queue them for eviction."""
        if self.config().get("shelves"):
            return []
        names = sorted(self._hot)
        self._pending_evict = names
        return names

    def forget_pair(self, item):
        """Drop discovery + catalog memory for an unlinked host. Files on disk are evicted separately."""
        item = item or {}
        keys = set(_keys_of(item))
        url = str(item.get("url") or "").strip()
        ip = str(item.get("ip") or "").strip()
        if not ip and url:
            try:
                ip = urlparse(url).hostname or ""
            except Exception:
                ip = ""
        if ip:
            keys.add(ip)
            if not url:
                url = "http://%s" % ip
        with self.lock:
            drop = []
            for k, host in list(self._seen.items()):
                if k in keys or any(bit in keys for bit in _keys_of(host)):
                    drop.append(k)
            for k in drop:
                self._seen.pop(k, None)
            if ip:
                self._candidates.discard(ip)
            for probe_url in list(self._probe.keys()):
                host = urlparse(probe_url).hostname or ""
                if probe_url == url or host == ip or probe_url in keys:
                    self._probe.pop(probe_url, None)
            for remote_url in list(self._remote.keys()):
                host = urlparse(remote_url).hostname or ""
                if remote_url == url or host == ip or remote_url in keys:
                    self._remote.pop(remote_url, None)
        self._persist_seen()

    def _scrub_declined(self):
        declined = self._declined_keys()
        if not declined:
            return
        with self.lock:
            ghosts = [dict(h) for h in self._seen.values() if any(bit in declined for bit in _keys_of(h))]
        for item in ghosts:
            self.forget_pair(item)

    def unlink(self, key, notify=True):
        key = str(key or "").strip()
        if not key:
            return False, "need id or url"
        cfg = load_config(self.path)
        kept = []
        dropped = None
        for item in cfg.get("shelves") or []:
            if key in _keys_of(item):
                dropped = item
                continue
            kept.append(item)
        if not dropped:
            return False, "not linked"
        last = not kept
        copies = self.hot_copies_for_shelf(dropped, last=last)
        declined = list(cfg.get("declined") or [])
        for bit in _keys_of(dropped) + [key]:
            if bit and bit not in declined:
                declined.append(bit)
        cfg["shelves"] = kept
        cfg["declined"] = declined
        save_config(cfg, self.path)
        self.reload()
        self._pending_evict = copies
        self.forget_pair(dropped)
        if notify and dropped.get("url"):
            me = identity()
            our = me.get("url") or (("http://%s" % me["ip"]) if me.get("ip") else "")
            try:
                _http_post(dropped["url"] + "/api/fleet", {
                    "action": "unlink",
                    "id": me.get("uid") or me.get("id") or cfg.get("id") or "",
                    "uid": me.get("uid") or "",
                    "url": our,
                    "notify": False,
                }, timeout=6)
            except Exception:
                pass
        return True, ""

    def _local_play_flags(self):
        """Playing flag for CRYPT/1 BEACON. Unison/group play is retired."""
        playing = False
        player = getattr(self, "player", None)
        if player is not None and hasattr(player, "snapshot"):
            try:
                playing = bool((player.snapshot() or {}).get("playing"))
            except Exception:
                playing = False
        return playing, False

    def _beacon_payload(self):
        me = identity()
        playing, unison = self._local_play_flags()
        return json.dumps({
            "crypt": 1,
            "v": VERSION,
            "id": me["id"],
            "uid": me["uid"],
            "host": me["host"],
            "ip": me["ip"],
            "model": me["model"],
            "tracks": int(self._own_tracks or 0),
            "libver": int(self._own_libver or 0),
            "playing": playing,
            "unison": unison,
        }, separators=(",", ":")).encode("utf-8")

    def _beacon_bin(self, seq):
        me = identity()
        cfg = self.config()
        # FLAG_LINKED means this host has any shelves, not "I list you".
        linked = bool(cfg.get("shelves"))
        playing, unison = self._local_play_flags()
        return crypt_wire.encode_beacon(
            me.get("uid") or "",
            seq,
            ip=me.get("ip") or "",
            model=me.get("model") or "",
            version=VERSION,
            tracks=int(self._own_tracks or 0),
            libhash=int(self._own_libver or 0),
            linked=linked,
            playing=playing,
            unison=unison,
        )

    def _beacon_loop(self):
        last_send = 0
        seq = crypt_wire.now_seq()
        while self._alive:
            now = time.time()
            sock = self._sock
            if sock is None:
                time.sleep(0.5)
                continue
            if now - last_send >= 2:
                seq = (seq + 1) & 0xFFFFFFFF
                try:
                    sock.sendto(self._beacon_bin(seq), (crypt_wire.GROUP, BEACON_PORT))
                    sock.sendto(self._beacon_payload(), (BROADCAST, BEACON_PORT))
                    self.beacon_ok = True
                    # Send does not require IGMP membership. Do not clear a join failure.
                    self.beacon_error = ""
                except Exception as exc:
                    self.beacon_error = str(exc)
                last_send = now
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except Exception as exc:
                self.beacon_error = str(exc)
                time.sleep(0.5)
                continue
            payload = crypt_wire.decode_any(data)
            if not payload:
                continue
            kind = payload.get("kind") or "beacon"
            if kind == "clock":
                continue
            if kind != "beacon":
                continue
            self.note_beacon(payload, addr[0] if addr else "")

    def start(self):
        if BEACON_PORT <= 0 or self._alive:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (OSError, AttributeError):
            pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.25)
        try:
            sock.bind(("0.0.0.0", BEACON_PORT))
        except OSError as exc:
            self.beacon_error = str(exc)
            sock.close()
            return
        try:
            crypt_wire.join_group(sock, iface=_lan_ip() or "0.0.0.0")
        except OSError as exc:
            self.igmp_ok = False
            self.igmp_error = str(exc)
        else:
            self.igmp_ok = True
            self.igmp_error = ""
        self._sock = sock
        self._alive = True
        self._thread = threading.Thread(target=self._beacon_loop, name="crypt-beacon")
        self._thread.daemon = True
        self._thread.start()

    def send_dgram(self, blob, dest=None):
        sock = self._sock
        if sock is None or not blob:
            return False
        dest = dest or (crypt_wire.GROUP, BEACON_PORT)
        try:
            sock.sendto(blob, dest)
            return True
        except Exception:
            return False

    def stop(self):
        self._alive = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


PEERS = PeerIndex()
