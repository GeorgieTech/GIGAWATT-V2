#!/usr/bin/env python3
"""Play-next order + requester names. Stdlib only."""
import re

REQUESTER_RE = re.compile(r"[A-Za-z0-9 .'\-]")


def sanitize_requester(name):
    raw = (name or "").strip()
    if not raw:
        return ""
    chars = [c for c in raw if REQUESTER_RE.match(c)]
    return "".join(chars)[:32].strip()


def insert_play_next(order, index, name):
    """Put `name` immediately after the current index. Names stay unique."""
    order = [str(n) for n in (order or [])]
    name = str(name or "").strip()
    if not name:
        return order, index
    cur = order[index] if 0 <= index < len(order) else ""
    if name == cur:
        return order, index
    order = [n for n in order if n != name]
    if cur:
        if cur not in order:
            insert_at = index if index >= 0 else 0
            if insert_at > len(order):
                insert_at = len(order)
            order.insert(insert_at, cur)
        idx = order.index(cur)
        order.insert(idx + 1, name)
        return order, idx
    order.insert(0, name)
    return order, -1
