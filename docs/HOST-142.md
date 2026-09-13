# Host hardware — 192.168.1.142 (master music server)

Factory product: **Savant SHC-S2-00** (SHC-2000 class Quad). This is the live Gigawatt host. There is no cluster or linked library.

Do **not** use **192.168.1.40**, **192.168.1.178**, **192.168.1.179**, or **192.168.1.180**. Do not `dd` a DualLite S2 eMMC onto this chassis. DualLite `.179` is retired from this lab.

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

Converted 2026-09-09: Savant `startupManager` + `nginx` masked, default `multi-user.target`, `crypt-hostname` / `crypt-pulse` / `crypt-web` enabled. This jack’s library is the files on **this** disk (`/data/music`). Caches stay under `/data/crypt`.

Live UI: [http://192.168.1.142/](http://192.168.1.142/)

Fleet role (worker vs TOSLINK playback) is not assigned yet. See [CLUSTER.md](CLUSTER.md).
