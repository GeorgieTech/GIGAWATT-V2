#!/usr/bin/env python3
"""CRYPT/1 host-to-host datagrams. Python 3.8 stdlib only.

Keep JSON UDP beacons working for one release. New packets are binary,
multicast-scoped, sequenced, and small enough for DualLite.
"""
from __future__ import print_function

import socket
import struct
import time

MAGIC = b"CRPT"
VERSION = 1
# Lab-only administratively scoped group. TTL 1 — do not leave 192.168.1.0/24.
GROUP = "239.18.20.1"
PORT = 41880
MAX_DGRAM = 512

TYPE_BEACON = 1
TYPE_CLOCK = 2
TYPE_LIBVER = 3
TYPE_ACK = 4

FLAG_LINKED = 1 << 0
FLAG_UNISON = 1 << 1
FLAG_PLAYING = 1 << 2

# header: magic(4) ver(1) type(1) flags(1) uid_len(1) seq(4) chk(1) pad(3) = 16
_HDR = struct.Struct("!4sBBBB I B 3s")


def fnv1a64(data):
    """Stable 64-bit catalog fingerprint. Not a crypto hash."""
    h = 0xcbf29ce484222325
    if not isinstance(data, (bytes, bytearray)):
        data = str(data or "").encode("utf-8")
    for b in data:
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def libver(tracks):
    """Fingerprint of a shelf catalog. Skip full JSON fetch when this matches."""
    parts = []
    for t in tracks or []:
        name = str((t or {}).get("name") or "")
        if not name:
            continue
        size = int((t or {}).get("size") or 0)
        mtime = int((t or {}).get("mtime") or 0)
        parts.append("%s:%s:%s" % (name, size, mtime))
    parts.sort()
    return fnv1a64("\n".join(parts).encode("utf-8"))


def _chk(blob):
    c = 0
    for b in blob:
        c = (c + b) & 0xFF
    return c


def _uid_bytes(uid):
    s = str(uid or "").strip().upper().replace(":", "")
    raw = s.encode("ascii", "ignore")[:16]
    return raw


def encode(kind, uid, seq, payload=b"", flags=0):
    uid_b = _uid_bytes(uid)
    if len(payload) + 16 + len(uid_b) > MAX_DGRAM:
        raise ValueError("datagram too large")
    head = _HDR.pack(MAGIC, VERSION, int(kind) & 0xFF, int(flags) & 0xFF,
                     len(uid_b), int(seq) & 0xFFFFFFFF, 0, b"\x00\x00\x00")
    body = head + uid_b + payload
    chk = _chk(body)
    head = _HDR.pack(MAGIC, VERSION, int(kind) & 0xFF, int(flags) & 0xFF,
                     len(uid_b), int(seq) & 0xFFFFFFFF, chk, b"\x00\x00\x00")
    return head + uid_b + payload


def encode_beacon(uid, seq, ip="", model="", version="", tracks=0, libhash=0,
                  linked=False, unison=False, playing=False, port=80):
    flags = 0
    if linked:
        flags |= FLAG_LINKED
    if unison:
        flags |= FLAG_UNISON
    if playing:
        flags |= FLAG_PLAYING
    ip_b = str(ip or "").encode("ascii", "ignore")[:15]
    model_b = str(model or "").encode("utf-8", "replace")[:24]
    ver_b = str(version or "").encode("ascii", "ignore")[:12]
    payload = struct.pack(
        "!H H Q B 15s B 24s B 12s",
        int(port) & 0xFFFF,
        int(tracks) & 0xFFFF,
        int(libhash) & 0xFFFFFFFFFFFFFFFF,
        len(ip_b), ip_b.ljust(15, b"\x00"),
        len(model_b), model_b.ljust(24, b"\x00"),
        len(ver_b), ver_b.ljust(12, b"\x00"),
    )
    return encode(TYPE_BEACON, uid, seq, payload, flags=flags)


def encode_clock(uid, seq, heard, mono, path, state, playing=False, unison=False):
    flags = 0
    if playing:
        flags |= FLAG_PLAYING
    if unison:
        flags |= FLAG_UNISON

    def us(v):
        if v is None:
            return -1
        return int(round(float(v) * 1e6))

    payload = struct.pack("!q q q B", us(heard), us(mono), us(path), int(state) & 0xFF)
    return encode(TYPE_CLOCK, uid, seq, payload, flags=flags)


def encode_libver(uid, seq, libhash, tracks=0):
    payload = struct.pack("!Q H", int(libhash) & 0xFFFFFFFFFFFFFFFF, int(tracks) & 0xFFFF)
    return encode(TYPE_LIBVER, uid, seq, payload)


def decode(data):
    if not data or len(data) < 16:
        return None
    if data[:4] != MAGIC:
        return None
    try:
        magic, ver, kind, flags, uid_len, seq, chk, _pad = _HDR.unpack(data[:16])
    except struct.error:
        return None
    if magic != MAGIC or ver != VERSION:
        return None
    if uid_len > 16 or 16 + uid_len > len(data):
        return None
    body = bytearray(data)
    body[12] = 0
    if _chk(body) != chk:
        return None
    uid = data[16:16 + uid_len].decode("ascii", "replace")
    rest = data[16 + uid_len:]
    out = {
        "crypt": 1,
        "wire": 1,
        "type": kind,
        "flags": flags,
        "seq": seq,
        "uid": uid,
        "linked": bool(flags & FLAG_LINKED),
        "unison": bool(flags & FLAG_UNISON),
        "playing": bool(flags & FLAG_PLAYING),
    }
    if kind == TYPE_BEACON:
        if len(rest) < 66:
            return None
        port, tracks, libhash, iplen, ip_b, mlen, model_b, vlen, ver_b = struct.unpack(
            "!H H Q B 15s B 24s B 12s", rest[:66]
        )
        out.update({
            "kind": "beacon",
            "ip": ip_b[:iplen].decode("ascii", "replace"),
            "model": model_b[:mlen].decode("utf-8", "replace"),
            "v": ver_b[:vlen].decode("ascii", "replace"),
            "version": ver_b[:vlen].decode("ascii", "replace"),
            "tracks": tracks,
            "libver": libhash,
            "port": port,
            "id": "crypt-%s" % uid.lower() if uid else "",
        })
        return out
    if kind == TYPE_CLOCK:
        if len(rest) < 25:
            return None
        heard_us, mono_us, path_us, state = struct.unpack("!q q q B", rest[:25])
        out.update({
            "kind": "clock",
            "heard": None if heard_us < 0 else heard_us / 1e6,
            "mono": None if mono_us < 0 else mono_us / 1e6,
            "path": None if path_us < 0 else path_us / 1e6,
            "state": state,
        })
        return out
    if kind == TYPE_LIBVER:
        if len(rest) < 10:
            return None
        libhash, tracks = struct.unpack("!Q H", rest[:10])
        out.update({"kind": "libver", "libver": libhash, "tracks": tracks})
        return out
    if kind == TYPE_ACK:
        out["kind"] = "ack"
        return out
    return None


def decode_any(data):
    """Binary CRYPT/1, or the V1.1.10 JSON beacon."""
    pkt = decode(data)
    if pkt:
        return pkt
    try:
        text = data.decode("utf-8")
        if not text.lstrip().startswith("{"):
            return None
        import json
        raw = json.loads(text)
    except (ValueError, UnicodeDecodeError, TypeError):
        return None
    if not isinstance(raw, dict) or raw.get("crypt") != 1:
        return None
    raw["wire"] = 0
    raw["kind"] = "beacon"
    raw["type"] = TYPE_BEACON
    return raw


def join_group(sock, group=GROUP, iface="0.0.0.0"):
    """IGMP join. iface is the host LAN IP, not 127.0.0.1."""
    mreq = struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton(iface))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
    if iface and iface != "0.0.0.0":
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))


def now_seq():
    return int(time.time() * 1000) & 0xFFFFFFFF
