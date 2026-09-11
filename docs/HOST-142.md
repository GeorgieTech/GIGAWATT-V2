# Host hardware — 192.168.1.142 (first SHC-2000)

Factory product: **Savant SHC-S2-00** (SHC-2000 class Quad). Same CRYPT web UI as the DualLite S2 at **192.168.1.179** (V1.1.9).

Do **not** use **192.168.1.40**, **192.168.1.178**, or **192.168.1.180**. Do not `dd` the DualLite S2 eMMC onto this chassis.

## Identity

| Field | Value |
|---|---|
| IP | `192.168.1.142/24` |
| Factory hostname | `sav-001aae0739db0000` |
| CRYPT hostname | `crypt-001aae0739db0000` |
| UID | `001AAE0739DB0000` |
| U-Boot / device tree model | `SHC-S2-00` |
| SSH user | `RPM` |

## Machine

- NXP i.MX6 **Quad**, 4× Cortex-A9
- **2 GB** RAM + zram swap (~2 GB)
- eMMC: `/` on `mmcblk0p8` (1.7 GB), **`/data` on `mmcblk0p3`** (3.2 GB)
- Ethernet `eth0` `192.168.1.142`
- Audio: Pulse sink `alsa_output.platform-sound-spdif.stereo-fallback` (TOSLINK / `imx-spdif`)
- Python 3.8.17 stdlib, ffmpeg 4.2.2, paplay / Pulse 13

Converted 2026-09-09: Savant `startupManager` + `nginx` masked, default `multi-user.target`, `crypt-hostname` / `crypt-pulse` / `crypt-web` enabled. Library listing is the DualLite shelf at **192.168.1.179** (`/data/crypt/peers.json`). Files stay on `.179`. Play on this box copies a track here first. Caches stay under `/data/crypt`.

Live UI: [http://192.168.1.142/](http://192.168.1.142/)

Fleet role (worker vs TOSLINK playback) is not assigned yet. See [CLUSTER.md](CLUSTER.md).
