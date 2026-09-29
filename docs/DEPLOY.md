# Deploy notes — Gigawatt V2.2.43

SSH user: `RPM`. Do not commit the password. `scp -O` from modern macOS.

Lab chassis: **192.168.1.142** (SHC-S2-00 Quad). A shipped unit takes **DHCP** — pass that address, not the lab IP.

Host paths: [LAYOUT.md](LAYOUT.md). Hardware: [HOST-142.md](HOST-142.md).

## Lab

```sh
git clone https://github.com/GeorgieTech/GIGAWATT-V2.git
cd GIGAWATT-V2
git checkout v2.2.43
chmod +x scripts/push-host.sh host-webui/install-on-host.sh
scripts/push-host.sh 192.168.1.142
```

Confirm:

```sh
curl -s http://192.168.1.142/api/status | python3 -c "import json,sys; print(json.load(sys.stdin).get('version'))"
```

It must print `2.2.43`.

## Any unit (DHCP)

Find the lease (`crypt-<uid>` on the router, or Settings → This host). Then:

```sh
scripts/push-host.sh <current-ip>
curl -s http://<current-ip>/api/status | python3 -c "import json,sys; print(json.load(sys.stdin).get('version'))"
```

## After a push

Re-import `georgietech_gigawatt.xml` (v1.3) so Savant Media Audio Query is back. Host browse: BrowseTitles / BrowsePlaylists / BrowseFavorites. Inspector IP is **this chassis’ current LAN address**, port **5004**. Deleting a track on this host also drops its lyrics, waveform, report, recents row, and album art when no sibling still uses it. Boot prunes leftover `/data/crypt` caches.

## First-time unit (once per chassis)

1. Mask `savant-startup-manager.service` and `nginx.service`.
2. Stop them. Set default target to `multi-user.target`.
3. Stop leftover Pulse (`pulseaudio`) if Savant left one running.
4. Install files in `/data/www`, music dir `/data/music`.
5. Enable `crypt-hostname`, `crypt-pulse`, `crypt-web`.

Savant images on the eMMC are not deleted. Cluster / peer linking was removed in V2.2.25. Do not `dd` an image from a different Savant model onto this Quad.
