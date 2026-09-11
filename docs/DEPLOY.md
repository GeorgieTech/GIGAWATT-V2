# Deploy notes — Gigawatt V2.0.1

Every host on this tag must run the **same** files. Do not mix 2.0.0 and 2.0.1. Convert a new SHC-2000 the same way, then push this checkout.

Targets so far: **192.168.1.179** (DualLite S2) and **192.168.1.142** (SHC-S2-00 Quad). Never 192.168.1.40 / .178 / .180.

Do not `dd` the S2 eMMC onto an SHC-2000. `/data` is `mmcblk0p2` on DualLite and `mmcblk0p3` on Quad.

SSH user: `RPM`. Do not commit the password. `scp -O` from modern macOS.

## Clone a new host (identical version)

On a converted chassis (Savant startup + nginx already masked, Pulse unit in place):

```sh
git clone https://github.com/GeorgieTech/GIGAWATT-V2.git
cd GIGAWATT-V2
git checkout v2.0.1
chmod +x scripts/push-host.sh host-webui/install-on-host.sh
scripts/push-host.sh 192.168.1.NEW
```

That copies `host-webui/FILES` to `/tmp` on the box and runs `install-on-host.sh`. Confirm:

```sh
curl -s http://192.168.1.NEW/api/status | python3 -c "import json,sys; print(json.load(sys.stdin).get('version'))"
```

It must print `2.0.1` on **every** host. If one box is behind, push the same tag again. Link libraries from Settings after both are on the same version.

## First-time unit (once per chassis)

1. Mask `savant-startup-manager.service` and `nginx.service`.
2. Stop them. Set default target to `multi-user.target`.
3. Stop leftover Pulse (`pulseaudio`) if Savant left one running.
4. Install files in `/data/www`, music dir `/data/music`.
5. Enable `crypt-hostname`, `crypt-pulse`, `crypt-web`.

Savant images on the eMMC are not deleted. Peer wire: [PEER-PROTOCOL.md](PEER-PROTOCOL.md).

Manual copy (same files as `scripts/push-host.sh`):

```sh
scp -O -o IPQoS=none $(sed '/^#/d;/^$/d' host-webui/FILES | sed 's|^|host-webui/|') RPM@192.168.1.179:/tmp/
ssh -o IPQoS=none RPM@192.168.1.179 sudo env bash /tmp/install-on-host.sh
```

Open http://192.168.1.179/

## Constraints

- No `apt`. Yocto image.
- Python 3.8 stdlib only.
- DualLite / 1 GB — library + TOSLINK. No extra daemons. No SSC expanders.
- No group play / Unison in V2. Link is library share only. Unlink splits catalogs and drops copies pulled from that host. Home files stay.
- Optional meaning essay: put `XAI_API_KEY=...` in `/data/crypt/xai.env` (not in git). The unit already reads that file. Without it, Research still writes a sourced essay from Wikipedia and local lyrics.
