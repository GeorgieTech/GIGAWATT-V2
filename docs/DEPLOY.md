# Deploy notes — Gigawatt V2.0.0

Targets: **192.168.1.179** (DualLite S2) and **192.168.1.142** (SHC-S2-00 Quad). Never 192.168.1.40 / .178 / .180.

Do not `dd` the S2 eMMC onto an SHC-2000. Install Gigawatt files the same way on both; `/data` is `mmcblk0p2` on DualLite and `mmcblk0p3` on Quad.

SSH user: `RPM`. Do not commit the password. `scp -O` from modern macOS.

## First-time unit

1. Mask `savant-startup-manager.service` and `nginx.service`.
2. Stop them. Set default target to `multi-user.target`.
3. Stop leftover Pulse (`pulseaudio`) if Savant left one running.
4. Install files in `/data/www`, music dir `/data/music`.
5. Enable `crypt-hostname`, `crypt-pulse`, `crypt-web`.

Savant images on the eMMC are not deleted.

From the repo root. Peer wire: [PEER-PROTOCOL.md](PEER-PROTOCOL.md).

```sh
scp -O host-webui/index.html host-webui/library.html host-webui/eq.html host-webui/karaoke.html host-webui/report.html host-webui/settings.html host-webui/crypt.css \
  host-webui/server.py host-webui/player.py host-webui/library.py host-webui/wave.py host-webui/lyrics.py host-webui/research.py host-webui/report.py host-webui/essay.py host-webui/peers.py host-webui/crypt_wire.py \
  host-webui/manifest.webmanifest host-webui/favicon.svg \
  host-webui/icon.png host-webui/apple-touch-icon.png \
  host-webui/pin-hostname.sh \
  host-webui/crypt-web.service host-webui/crypt-pulse.service \
  host-webui/crypt-hostname.service \
  RPM@192.168.1.179:/tmp/
```

Then on the host, as root via `sudo env bash`:

```sh
mkdir -p /data/www /data/music
chown RPM:RPM /data/www /data/music
cp /tmp/index.html /tmp/library.html /tmp/eq.html /tmp/karaoke.html /tmp/report.html /tmp/settings.html /tmp/crypt.css \
  /tmp/server.py /tmp/player.py /tmp/library.py /tmp/wave.py /tmp/lyrics.py /tmp/research.py /tmp/report.py /tmp/essay.py /tmp/peers.py /tmp/crypt_wire.py /tmp/pin-hostname.sh \
  /tmp/manifest.webmanifest /tmp/favicon.svg /tmp/icon.png /tmp/apple-touch-icon.png \
  /data/www/
rm -f /data/www/unison.py
chmod +x /data/www/pin-hostname.sh /data/www/server.py
cp /tmp/crypt-web.service /tmp/crypt-pulse.service /tmp/crypt-hostname.service /etc/systemd/system/
systemctl mask savant-startup-manager.service nginx.service
systemctl stop savant-startup-manager.service nginx.service
systemctl stop pulseaudio.service 2>/dev/null || true
systemctl set-default multi-user.target
systemctl daemon-reload
systemctl enable crypt-hostname.service crypt-pulse.service crypt-web.service
systemctl restart crypt-hostname.service crypt-pulse.service crypt-web.service
```

Open http://192.168.1.179/

## Constraints

- No `apt`. Yocto image.
- Python 3.8 stdlib only.
- DualLite / 1 GB — library + TOSLINK. No extra daemons. No SSC expanders.
- No group play / Unison in V2. Link is library share only.
- Optional meaning essay: put `XAI_API_KEY=...` in `/data/crypt/xai.env` (not in git). The unit already reads that file. Without it, Research still writes a sourced essay from Wikipedia and local lyrics.
