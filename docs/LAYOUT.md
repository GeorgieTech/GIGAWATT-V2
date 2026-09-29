# Host directories — 192.168.1.142

Live chassis: **crypt-001aae0739db0000** (SHC-S2-00 Quad). Gigawatt code, library, and caches live on **`/data`**. Factory Savant is still on `/` and `/usr/local`; those images are not deleted.

Do **not** use **192.168.1.40**, **192.168.1.178**, **192.168.1.179**, or **192.168.1.180**.

Do not commit the RPM password, NAS password, or `rclone.conf`. SSH user is `RPM`.

## Disks

| Mount | Device | Size | Role |
|---|---|---|---|
| `/` | eMMC root (`mmcblk0p8`) | 1.7 GB | Yocto + factory Savant |
| `/data` | `mmcblk0p3` | 3.1 GB | Gigawatt + leftover Savant state |
| `/update` | `mmcblk0p2` | 486 MB | Factory update partition |

## `/` (root)

| Path | What it is |
|---|---|
| `/bin` `/sbin` `/lib` `/usr` `/etc` | Yocto userspace |
| `/home/RPM` | Symlink to `/data/RPM` |
| `/opt/dotnet` | Factory leftover |
| `/tmp` | Last `push-host.sh` copies + ffmpeg/rclone logs |
| `/usr/local` | Factory Savant daemons (`rpm`, `edm`, `hosttools`, …) |
| `/var/log` | Symlink to `/data/volatile/log` |
| `/www` | Factory Savant web UI (not Gigawatt) |
| `/data` | This product |

Units: `/etc/systemd/system/crypt-web.service`, `crypt-pulse.service`, `crypt-hostname.service`.

## `/data` (Gigawatt)

```
/data
├── music/                 library audio + sidecar lyrics (see below)
├── www/                   Gigawatt process (this repo’s host-webui/)
├── crypt/                 state and per-track caches
├── nas/                   rclone FUSE mount of the SMB share
├── opt/airplay/           vendored shairport-sync 3.3.7
├── opt/nas/               vendored rclone + fusermount
├── RPM/                   SSH user home
├── lib/autonomic/         leftover Savant XML
├── savant/                leftover Savant note
├── ssh/                   host SSH keys
├── var/lib/               connman + bluetooth
├── volatile/              logs and tmp (`/var/log` points here)
├── tmp/
└── lost+found/
```

Also on `/data`: `.factory-defaults`, `.rpm`, `fw_printenv.lock`.

### Library — `/data/music`

This is where **tracks on this host** live. Audio files (mp3/flac/opus/ogg/wav/m4a/aac) sit here, flat or in artist/album folders. Matching sidecar `.lrc` / `.txt` lyrics sit next to the file. Empty album folders, leftover `cover.jpg`, and orphan `.lrc` are removed when the last audio in that folder is deleted.

Files on a NAS share are **not** copied here. Playback reads them through `/data/nas`.

### Code — `/data/www`

Installed from `host-webui/` by `scripts/push-host.sh`. One process: `server.py` on port 80.

| File | Role |
|---|---|
| `VERSION` | Release string |
| `server.py` | HTTP + library + routing |
| `player.py` | ffmpeg → paplay TOSLINK |
| `library.py` | Catalog, playlists, leftover sweep |
| `cover.py` | Cover Art Archive + folder/embedded art |
| `lyrics.py` | Sidecar / tags / lrclib cache |
| `wave.py` | Waveform cache |
| `report.py` `research.py` `essay.py` | Track report |
| `airplay.py` `nas.py` `wifi.py` `playback.py` `queueing.py` `savant.py` `identity.py` | Features |
| `index.html` `library.html` `karaoke.html` `report.html` `settings.html` `eq.html` | Pages |
| `crypt.css` `manifest.webmanifest` `favicon.svg` `icon.png` `apple-touch-icon.png` | UI |
| `gigawatt-pulse.pa` `pin-hostname.sh` | Pulse + hostname pin |
| `__pycache__/` | Runtime `.pyc` (wiped on install) |

### State — `/data/crypt`

| Path | Role | Dies with the track? |
|---|---|---|
| `covers/` | Album art `.img` + `index.json` | Yes, if no sibling still uses that album. `extract-*.img` always |
| `lyrics/` | Lyrics JSON | Yes (sidecars next to the file too) |
| `waves/` | Waveform JSON | Yes |
| `reports/` | Report JSON | Yes |
| `library-meta.json` | Probe/edit rows | Yes |
| `savant-recents.json` | RacePoint recents | Local rows yes; NAS rows stay |
| `playlists.json` | Playlists | Track names dropped from lists |
| `clock.json` `eq.json` `playback.json` | Jack state | No |
| `nas.json` `rclone.conf` | NAS login | No (do not commit) |
| `rclone-vfs/` | rclone FUSE cache | Cleared on NAS disconnect |

Boot prunes cache rows whose files are no longer in `/data/music`. HTTP pages are an allowlist under `/data/www`. `/api/media` only serves audio under `/data/music` or `/data/nas`.

### NAS — `/data/nas` and `/data/opt/nas`

rclone FUSE mount of the SMB share. SSH often cannot list `/data/nas` (`Permission denied`) while it is mounted. Tools: `/data/opt/nas/rclone`, `fusermount`, `libfuse`. Cache dir `/data/crypt/rclone-vfs`.

### AirPlay — `/data/opt/airplay`

`shairport-sync`, `run-shairport`, `shairport-sync.conf`, and the vendored `.so` files.

### Leftover Savant on `/data`

Not used by Gigawatt. Left in place on purpose:

- `/data/RPM/GNUstep/` RacePoint plists, certs, status sqlite
- `/data/lib/autonomic/`
- `/data/savant/`
- `/data/ssh/` factory host keys

## `/tmp` after a deploy

`push-host.sh` copies `FILES` plus `gigawatt-airplay/` and `gigawatt-nas/` here, then `install-on-host.sh` installs them. Runtime logs: `/tmp/crypt-ffmpeg.log`, `/tmp/crypt-ff.progress`, `/tmp/crypt-rclone.log`.

## `/www` (factory)

Savant Liteware UI (`html/`, `cgi-bin/`, `devices/`). Nginx is masked. Gigawatt UI is **`/data/www`** on port 80, not this tree.
