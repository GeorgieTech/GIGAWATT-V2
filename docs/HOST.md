# Host hardware — 192.168.1.179 (CRYPT V1.1.7)

Factory product: **Savant S2 Host Rack Mountable, SHR-S2-00**.

Do **not** use **192.168.1.40**, **192.168.1.178**, or **192.168.1.180**.

## Identity

| Field | Value |
|---|---|
| IP | 192.168.1.179/24 |
| Factory hostname | `sav-001aae10e4090000` |
| CRYPT hostname | `crypt-001aae10e4090000` |
| UID | `001AAE10E4090000` |
| Serial | `ES2191100924` |
| Part number | `068-0728-11_02` |
| U-Boot model (`mn`) | `SHR-S2-00` |
| Device tree | `SHR-S2-00` / `fsl,imx6dl-savant-s2sm` |
| Userspace | 32-bit `armv7l` |

## Machine

- NXP i.MX6 **DualLite**, 2× Cortex-A9 @ ~1 GHz
- **1 GB** RAM + zram swap (~980 MB)
- eMMC 14.7 GB: `/` on `mmcblk0p7` (3 GB), `/data` on `mmcblk0p2` (7.3 GB)
- Ethernet `eth0` MAC `00:1A:AE:10:E4:09`
- Wi-Fi `wlan0` TI wl18xx (unused in V1.1.7)
- Audio: Pulse sink `alsa_output.platform-sound-spdif.stereo-fallback` (TOSLINK / `imx-spdif`, 24-bit 96 kHz)

This is **not** the SHC-2000 / SHC-S2 Quad (2 GB, 4 cores, `/data` on p3). Do not `dd` images between them. The four-host SHC-2000 farm (three workers + one TOSLINK playback) is planned in [CLUSTER.md](CLUSTER.md). It is not this DualLite.

## Software image (as converted)

- Kernel 4.14.78
- Savant Embedded Linux 20.04, build 697
- Python 3.8.17 (stdlib only, no apt)
- ffmpeg 4.2.2, paplay / PulseAudio 13
- OpenSSH 8.2, user `RPM`
- `sudo` NOPASSWD includes `/usr/bin/env` and `/bin/systemctl`

Savant `startupManager` and `nginx` are **masked**. Default target is `multi-user.target`.
