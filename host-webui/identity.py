#!/usr/bin/env python3
"""This chassis identity. No cluster, no peer discovery."""
from __future__ import print_function

import os
import socket
import time

VERSION = "2.2.37"
LAN_PREFIX = "192.168.1."
BLOCKED = ("192.168.1.40", "192.168.1.178", "192.168.1.179", "192.168.1.180")


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


def stamp(uid_or_id):
    uid = _uid_from(uid_or_id) or ""
    if not uid:
        uid = str(uid_or_id or "").strip().upper().replace(":", "")
    core = uid.rstrip("0") or uid
    if len(core) >= 4:
        return core[-4:]
    return uid[-4:] if len(uid) >= 4 else uid
