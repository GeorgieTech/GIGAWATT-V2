# Gigawatt V2.2.43

Repo: [`GIGAWATT-V2`](https://github.com/GeorgieTech/GIGAWATT-V2)

A local TOSLINK music player on a recycled Savant S2 host (SHC-S2-00 Quad). Library on this disk, web UI on port 80, optical out.

**Current release: [V2.2.43](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.43)** (`v2.2.43`). Previous: [V2.2.42](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.42) · [V2.2.41](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.41).

This project is **not affiliated with Savant Systems**.

There is **no cluster**, linked library, Unison, or host-to-host discovery. Each box plays files that live in `/data/music` on that chassis.

## Finding a unit on your LAN

Plug Ethernet. The host takes an address from **DHCP**. A shipped unit will **not** be `192.168.1.142` unless that is what your router assigns.

1. Look up the lease on your router. Hostname is `crypt-<uid>` (Settings also shows it).
2. Open `http://<that-ip>/` from a phone or laptop on the same LAN.
3. On a phone: Safari/Chrome → **Add to Home Screen**.

Settings → This host shows the live Ethernet (and Wi-Fi) address.

## Lab host (this repo)

The chassis used to build and test this firmware is **192.168.1.142** (`crypt-001aae0739db0000`, SHC-S2-00 Quad). Deploy examples use that address. `scripts/push-host.sh` takes the IP of **one** Gigawatt chassis — for a shipped unit, pass whatever DHCP gave it.

Lab UI (this development jack only): [http://192.168.1.142/](http://192.168.1.142/)

## What it does

- **Album covers** from Cover Art Archive (local/embedded first). Playing shows the cover when found, otherwise the visualizer.
- **This jack or this browser.** Settings → Playback. TOSLINK is the default.
- **AirPlay 1** to this host. Settings → AirPlay (`Gigawatt 39DB`, …). iPhone/Mac → Pulse → TOSLINK. Pulse resamples 44.1 kHz onto 48 kHz so this jack actually plays.
- Dark Playing and Library UI, Karaoke, Report, 31-band TOSLINK EQ (in Settings)
- Play through the S2 **TOSLINK** jack (`ffmpeg` → `paplay` → Pulse → `imx-spdif`)
- **NAS** SMB share from Settings. Library can browse it; playback reads the share (files stay on the NAS). NAS lyrics stay on-demand (Karaoke → Fetch). Tracks on this disk fetch lyrics in the background; Library shows a progress bar.
- **Savant** RacePoint profile (`docs/savant/georgietech_gigawatt.xml`): TOSLINK media server, telnet **:5004**. Inspector IP is this chassis’ current LAN address. Not SMS-102A.

No Spotify, DLNA, SSC expanders, AirPlay 2, or multi-host linking.

| Piece | Path |
|---|---|
| Code | `/data/www` |
| Library | `/data/music` |
| Caches / state | `/data/crypt` |
| Pulse | `crypt-pulse.service` |

Host directory map (no track names): [docs/LAYOUT.md](docs/LAYOUT.md).

## Docs

- Hardware (lab chassis): [docs/HOST-142.md](docs/HOST-142.md)
- Directories: [docs/LAYOUT.md](docs/LAYOUT.md)
- Deploy (lab or any unit): [docs/DEPLOY.md](docs/DEPLOY.md)
- Savant RacePoint: [docs/SAVANT.md](docs/SAVANT.md)
