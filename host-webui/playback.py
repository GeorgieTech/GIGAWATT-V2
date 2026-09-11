#!/usr/bin/env python3
"""Jack vs browser output and AirPlay name. Python 3.8 stdlib."""
from __future__ import print_function

import json
import os

from airplay import default_name, sanitize_name

PLAYBACK_FILE = os.environ.get("CRYPT_PLAYBACK", "/data/crypt/playback.json")
OUTPUTS = ("jack", "browser")


def load_playback(path=None):
    path = path or PLAYBACK_FILE
    data = {}
    try:
        with open(path, "r") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            data = raw
    except (OSError, ValueError, TypeError):
        data = {}
    output = data.get("output")
    if output not in OUTPUTS:
        output = "jack"
    name = sanitize_name(data.get("airplay_name")) or default_name()
    airplay = True if "airplay" not in data else bool(data.get("airplay"))
    return {
        "output": output,
        "airplay": airplay,
        "airplay_name": name,
    }


def save_playback(output=None, airplay=None, airplay_name=None, path=None):
    path = path or PLAYBACK_FILE
    current = load_playback(path)
    if output in OUTPUTS:
        current["output"] = output
    if airplay is not None:
        current["airplay"] = bool(airplay)
    if airplay_name is not None:
        clean = sanitize_name(airplay_name)
        if not clean:
            return current, "name must be 1-50 letters, numbers, space, dot, underscore, or dash"
        current["airplay_name"] = clean
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(current, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    return current, ""
