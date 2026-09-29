# Lab host — 192.168.1.142

Factory product: **Savant SHC-S2-00** (SHC-2000 class Quad). This is the development chassis for Gigawatt V2. There is no cluster or linked library.

Shipped units are the same hardware. They take an address from **DHCP** and will not be `192.168.1.142` unless that is what the buyer’s router assigns. Deploy with `scripts/push-host.sh <current-ip>` — see [DEPLOY.md](DEPLOY.md).

## Identity

| Field | Value |
|---|---|
| Lab IP | `192.168.1.142/24` (reservation on this LAN, not a product default) |
| Factory hostname | `sav-001aae0739db0000` |
| CRYPT hostname | `crypt-001aae0739db0000` |
| UID | `001AAE0739DB0000` |
| U-Boot / device tree model | `SHC-S2-00` |
| SSH user | `RPM` |

## Machine

- NXP i.MX6 **Quad**, 4× Cortex-A9
- **2 GB** RAM + zram swap (~2 GB)
- eMMC: `/` on `mmcblk0p8` (1.7 GB), **`/data` on `mmcblk0p3`** (3.2 GB)
- Ethernet `eth0` (DHCP on a shipped unit; this lab jack is `192.168.1.142`)
- Audio: Pulse sink `alsa_output.platform-sound-spdif.stereo-fallback` (TOSLINK / `imx-spdif`)
- Python 3.8.17 stdlib, ffmpeg 4.2.2, paplay / Pulse 13

Converted 2026-09-09: Savant `startupManager` + `nginx` masked, default `multi-user.target`, `crypt-hostname` / `crypt-pulse` / `crypt-web` enabled. This jack’s library is the files on **this** disk (`/data/music`). Caches stay under `/data/crypt`.

Directory map: [LAYOUT.md](LAYOUT.md).

Lab UI: [http://192.168.1.142/](http://192.168.1.142/)

There is no cluster. See [CLUSTER.md](CLUSTER.md).
