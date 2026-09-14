#!/usr/bin/env python3
"""SMB/NAS mount via rclone FUSE. Kernel CIFS is not on this Savant image.

Files stay on the share. Playback reads through /data/nas. Python 3.8 stdlib.
"""
from __future__ import print_function

import json
import os
import re
import signal
import subprocess
import threading
import time

NAS_DIR = os.environ.get("NAS_DIR", "/data/nas")
NAS_BIN = os.environ.get("NAS_BIN", "/data/opt/nas")
NAS_TRACK_CAP = 2000
AUDIO_EXT = (".mp3", ".flac", ".opus", ".ogg", ".wav", ".m4a", ".aac")
HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
SHARE_RE = re.compile(r"^[A-Za-z0-9._ $()-]{1,80}$")
FOLDER_RE = re.compile(r"^[A-Za-z0-9._ /$()-]{0,120}$")
USER_RE = re.compile(r"^[A-Za-z0-9._\\@-]{0,64}$")
DOMAIN_RE = re.compile(r"^[A-Za-z0-9._-]{0,64}$")
DISC_RE = re.compile(r"^(cd|disc|disk|dvd)\s*\d+$", re.I)
NAS_SKIP = {
    "@eadir",
    "#recycle",
    "#snapshot",
    "thumbs.db",
    "desktop.ini",
    ".ds_store",
    "albumart.jpg",
    "albumart.png",
    "folder.jpg",
    "folder.png",
    "cover.jpg",
    "cover.png",
}
NAS_UNKNOWN_ALBUM = {"unknownalbum", "unknown album", "unknown", "untitled"}


def _run(args, timeout=20, env=None):
    try:
        return subprocess.check_output(
            args, stderr=subprocess.STDOUT, timeout=timeout, env=env, universal_newlines=True
        )
    except subprocess.CalledProcessError as exc:
        out = exc.output or ""
        return out if isinstance(out, str) else ""
    except Exception as exc:
        return str(exc)


def _pretty_title(name):
    base = os.path.splitext(os.path.basename(name or ""))[0]
    base = base.replace("_", " ")
    return re.sub(r"\s+", " ", base).strip() or (name or "Track")


def _nas_skip(name):
    if not name or name in (".", "..") or name.startswith("."):
        return True
    return name.lower() in NAS_SKIP


def rel_ok(rel):
    rel = (rel or "").replace("\\", "/").strip("/")
    if not rel:
        return ""
    if rel in (".", "..") or ".." in rel.split("/"):
        return None
    return rel


def nas_abs(rel, mountpoint=None):
    rel = rel_ok(rel)
    if rel is None:
        return None
    root = os.path.realpath(mountpoint or NAS_DIR)
    full = os.path.realpath(os.path.join(root, rel)) if rel else root
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


def parse_nas_meta(rel):
    parts = [p for p in (rel or "").replace("\\", "/").split("/") if p]
    if not parts:
        return "", "", ""
    title = _pretty_title(parts[-1])
    folders = parts[:-1]
    while folders and DISC_RE.match(folders[-1]):
        folders.pop()
    artist = folders[0] if folders else ""
    album = folders[1] if len(folders) > 1 else ""
    if album and album.lower() in NAS_UNKNOWN_ALBUM:
        album = "Unknown album"
    return artist, album, title


def _album_label(name):
    if name and name.lower() in NAS_UNKNOWN_ALBUM:
        return "Unknown album"
    return name


def empty_catalog(rel=""):
    rel = rel or ""
    crumbs = [{"label": "NAS", "path": ""}]
    acc = []
    for part in [p for p in rel.split("/") if p]:
        acc.append(part)
        crumbs.append({"label": _album_label(part), "path": "/".join(acc)})
    parent = "/".join(acc[:-1]) if acc else ""
    return {
        "path": rel,
        "parent": parent,
        "crumbs": crumbs,
        "artists": [],
        "albums": [],
        "tracks": [],
        "error": "",
        "capped": False,
    }


def _nas_track(rel):
    artist, album, title = parse_nas_meta(rel)
    ext = os.path.splitext(rel)[1].lower()
    return {
        "name": rel,
        "title": title,
        "artist": artist or "Unknown artist",
        "album": album or "Unknown album",
        "ext": ext.lstrip("."),
        "origin": "nas",
        "local": False,
        "here": False,
    }


def _scandir(rel, mountpoint=None):
    full = nas_abs(rel, mountpoint)
    dirs = []
    files = []
    if not full or not os.path.isdir(full):
        return dirs, files, "folder not found"
    try:
        with os.scandir(full) as it:
            for entry in it:
                name = entry.name
                if _nas_skip(name):
                    continue
                child = (rel + "/" + name) if rel else name
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    dirs.append((name, child))
                elif is_file:
                    files.append((name, child))
    except OSError as exc:
        return [], [], str(exc)
    dirs.sort(key=lambda item: item[0].lower())
    files.sort(key=lambda item: item[0].lower())
    return dirs, files, ""


def list_tracks(rel="", cap=None, mountpoint=None):
    cap = NAS_TRACK_CAP if cap is None else cap
    rel = rel_ok(rel)
    if rel is None:
        return [], False
    full = nas_abs(rel, mountpoint)
    tracks = []
    if not full or not os.path.isdir(full):
        return tracks, False
    root = os.path.realpath(mountpoint or NAS_DIR)
    capped = False
    try:
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames[:] = [name for name in dirnames if not _nas_skip(name)]
            dirnames.sort(key=lambda name: name.lower())
            filenames.sort(key=lambda name: name.lower())
            for filename in filenames:
                if _nas_skip(filename):
                    continue
                ext = os.path.splitext(filename)[1].lower()
                if ext not in AUDIO_EXT:
                    continue
                child = os.path.relpath(os.path.join(dirpath, filename), root).replace("\\", "/")
                tracks.append(_nas_track(child))
                if len(tracks) >= cap:
                    capped = True
                    break
            if capped:
                break
    except OSError:
        pass
    return tracks, capped


def browse(rel="", deep=False, mountpoint=None):
    root = mountpoint or NAS_DIR
    rel = rel_ok(rel)
    if rel is None:
        catalog = empty_catalog("")
        catalog["error"] = "path is not valid"
        return catalog
    catalog = empty_catalog(rel)
    if not os.path.isdir(root):
        catalog["error"] = "NAS is not mounted"
        return catalog
    dirs, files, err = _scandir(rel, root)
    if err:
        catalog["error"] = err
        return catalog
    parts = [p for p in rel.split("/") if p]
    depth = len(parts)
    disc_dirs = [(name, child) for name, child in dirs if DISC_RE.match(name)]
    other_dirs = [(name, child) for name, child in dirs if not DISC_RE.match(name)]
    if depth == 0:
        catalog["artists"] = [{"name": name, "path": child} for name, child in dirs]
    elif depth >= 2 and disc_dirs and not other_dirs:
        extra = []
        for _name, child in disc_dirs:
            more, _capped = list_tracks(child, cap=NAS_TRACK_CAP - len(extra), mountpoint=root)
            extra.extend(more)
            if len(extra) >= NAS_TRACK_CAP:
                catalog["capped"] = True
                break
        catalog["tracks"].extend(extra)
    else:
        artist_name = parts[0] if parts else ""
        catalog["albums"] = [
            {"name": _album_label(name), "path": child, "artist": artist_name}
            for name, child in dirs
        ]
    for name, child in files:
        ext = os.path.splitext(name)[1].lower()
        if ext not in AUDIO_EXT:
            continue
        catalog["tracks"].append(_nas_track(child))
        if len(catalog["tracks"]) >= NAS_TRACK_CAP:
            catalog["capped"] = True
            break
    if deep and not catalog["capped"] and depth == 1:
        nested, capped = list_tracks(rel, mountpoint=root)
        seen = {track["name"] for track in catalog["tracks"]}
        for track in nested:
            if track["name"] in seen:
                continue
            catalog["tracks"].append(track)
            seen.add(track["name"])
            if len(catalog["tracks"]) >= NAS_TRACK_CAP:
                capped = True
                break
        catalog["capped"] = catalog["capped"] or capped
        catalog["tracks"].sort(key=lambda track: ((track.get("album") or "").lower(), (track.get("name") or "").lower()))
    return catalog


class NasShare(object):
    def __init__(self, directory, mountpoint, state_dir):
        self.directory = directory
        self.mountpoint = mountpoint
        self.state_dir = state_dir
        self.lock = threading.Lock()
        self.proc = None
        self.error = ""
        self.cfg = {
            "host": "",
            "share": "",
            "folder": "",
            "username": "",
            "password": "",
            "domain": "",
            "enabled": False,
        }
        self._load()

    def available(self):
        return os.path.isfile(os.path.join(self.directory, "rclone"))

    def mounted(self):
        try:
            with open("/proc/mounts") as fh:
                for line in fh:
                    if " " + self.mountpoint + " " in line and "fuse" in line:
                        return True
        except Exception:
            pass
        return False

    def snapshot(self):
        with self.lock:
            running = self.proc is not None and self.proc.poll() is None
            if self.proc is not None and self.proc.poll() is not None:
                self.proc = None
                running = False
            mounted = self.mounted()
            if not mounted:
                running = False
            return {
                "available": self.available(),
                "mounted": bool(mounted),
                "enabled": bool(self.cfg.get("enabled") and mounted),
                "host": self.cfg.get("host") or "",
                "share": self.cfg.get("share") or "",
                "folder": self.cfg.get("folder") or "",
                "username": self.cfg.get("username") or "",
                "domain": self.cfg.get("domain") or "",
                "password_set": bool(self.cfg.get("password")),
                "path": "//%s/%s" % (self.cfg.get("host") or "—", self.cfg.get("share") or "—"),
                "mountpoint": self.mountpoint,
                "error": self.error,
                "running": running,
            }

    def apply(self, data):
        data = data or {}
        host = str(data.get("host") or "").strip()
        share = str(data.get("share") or "").strip().strip("/")
        folder = str(data.get("folder") or "").strip().strip("/")
        username = str(data.get("username") or "").strip()
        domain = str(data.get("domain") or "").strip()
        password = data.get("password")
        if host and not HOST_RE.match(host):
            self.error = "server must be a hostname or IP"
            return False
        if share and not SHARE_RE.match(share):
            self.error = "share name is not valid"
            return False
        if folder and (not FOLDER_RE.match(folder) or ".." in folder.split("/")):
            self.error = "folder path is not valid"
            return False
        if username and not USER_RE.match(username):
            self.error = "username is not valid"
            return False
        if domain and not DOMAIN_RE.match(domain):
            self.error = "domain is not valid"
            return False
        with self.lock:
            if host:
                self.cfg["host"] = host
            if "share" in data:
                self.cfg["share"] = share
            if "folder" in data:
                self.cfg["folder"] = folder
            if "username" in data:
                self.cfg["username"] = username
            if "domain" in data:
                self.cfg["domain"] = domain
            if password is not None and password != "":
                self.cfg["password"] = str(password)
            self._save_locked()
            self.error = ""
        return True

    def connect(self):
        if not self.available():
            self.error = "NAS tools missing on this host"
            return False
        with self.lock:
            host = self.cfg.get("host") or ""
            share = self.cfg.get("share") or ""
            if not host or not share:
                self.error = "enter the NAS server and share name"
                return False
            if self.mounted() and self.proc is not None and self.proc.poll() is None:
                self.cfg["enabled"] = True
                self._save_locked()
                self.error = ""
                return True
            self._unmount_locked()
            try:
                self._write_rclone_locked()
            except Exception as exc:
                self.error = str(exc)
                return False
            try:
                os.makedirs(self.mountpoint, exist_ok=True)
            except OSError:
                pass
            env = self._env()
            remote = self._remote_path_locked()
            cache_dir = os.path.join(self.state_dir, "rclone-vfs")
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except OSError:
                pass
            cmd = [
                os.path.join(self.directory, "rclone"),
                "mount",
                remote,
                self.mountpoint,
                "--config",
                self._conf_path(),
                "--vfs-cache-mode",
                "writes",
                "--vfs-read-ahead",
                "8M",
                "--dir-cache-time",
                "5m",
                "--attr-timeout",
                "10s",
                "--vfs-cache-max-size",
                "256M",
                "--cache-dir",
                cache_dir,
                "--timeout",
                "30s",
                "--contimeout",
                "12s",
                "--uid",
                str(os.getuid()),
                "--gid",
                str(os.getgid()),
                "--allow-other",
                "--log-file",
                "/tmp/crypt-rclone.log",
            ]
            try:
                self.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    preexec_fn=os.setsid,
                )
            except Exception as exc:
                self.error = str(exc)
                self.proc = None
                return False
            for _ in range(40):
                time.sleep(0.25)
                if self.proc.poll() is not None:
                    err = ""
                    try:
                        with open("/tmp/crypt-rclone.log") as fh:
                            lines = fh.read().strip().splitlines()
                        err = lines[-1] if lines else ""
                    except Exception:
                        pass
                    self.error = (err or "mount failed").strip()[:180]
                    self.proc = None
                    return False
                if self.mounted():
                    self.cfg["enabled"] = True
                    self._save_locked()
                    self.error = ""
                    return True
            self._unmount_locked()
            self.error = "NAS did not come online. Check server, share, and password."
            return False

    def disconnect(self):
        with self.lock:
            self.cfg["enabled"] = False
            self._save_locked()
            self._unmount_locked()
            self.error = ""
            return True

    def _remote_path_locked(self):
        share = (self.cfg.get("share") or "").strip("/")
        folder = (self.cfg.get("folder") or "").strip("/")
        path = share
        if folder:
            path = share + "/" + folder
        return "nas:" + path

    def _conf_path(self):
        return os.path.join(self.state_dir, "rclone.conf")

    def _cfg_path(self):
        return os.path.join(self.state_dir, "nas.json")

    def _env(self):
        env = os.environ.copy()
        env["PATH"] = self.directory + ":" + env.get("PATH", "/usr/bin:/bin")
        lib = os.path.join(self.directory, "lib")
        env["LD_LIBRARY_PATH"] = lib + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        return env

    def _obscure(self, password):
        rclone = os.path.join(self.directory, "rclone")
        out = _run([rclone, "obscure", password or ""], timeout=8, env=self._env())
        line = (out or "").strip().splitlines()
        return line[-1] if line else ""

    def _write_rclone_locked(self):
        obscured = self._obscure(self.cfg.get("password") or "")
        body = (
            "[nas]\n"
            "type = smb\n"
            "host = %s\n"
            "user = %s\n"
            "pass = %s\n"
            "domain = %s\n"
        ) % (
            self.cfg.get("host") or "",
            self.cfg.get("username") or "guest",
            obscured,
            self.cfg.get("domain") or "",
        )
        path = self._conf_path()
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(body)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _load(self):
        try:
            with open(self._cfg_path()) as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for key in self.cfg:
                    if key in data:
                        self.cfg[key] = data[key]
        except Exception:
            pass

    def _save_locked(self):
        os.makedirs(self.state_dir, exist_ok=True)
        path = self._cfg_path()
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.cfg, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _unmount_locked(self):
        proc = self.proc
        self.proc = None
        fuse = os.path.join(self.directory, "fusermount")
        env = self._env()
        if os.path.isfile(fuse):
            subprocess.call(
                [fuse, "-uz", self.mountpoint],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        subprocess.call(
            ["umount", "-l", self.mountpoint],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
