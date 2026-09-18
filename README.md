# Gigawatt V2.2.39

Repo: [`GIGAWATT-V2`](https://github.com/GeorgieTech/GIGAWATT-V2)

A local TOSLINK music player on a recycled Savant S2 host (SHC-S2-00 Quad). Library on this disk, web UI on port 80, optical out.

**Current release: [V2.2.39](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.39)** (`v2.2.39`). Previous: [V2.2.38](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.38) · [V2.2.37](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.37).

This project is **not affiliated with Savant Systems**.

Live target: **192.168.1.142** (SHC-S2-00 Quad). Do not use 192.168.1.40 (live Carrillos Resident), 192.168.1.178 (Gigawatt V1), 192.168.1.179 (retired DualLite mule), or 192.168.1.180 (Giggwatt Beta1).

There is **no cluster**, linked library, Unison, or host-to-host discovery. This box plays files that live in `/data/music` on this chassis.

## What it does

- **Album covers** from Cover Art Archive (local/embedded first). Playing shows the cover when found, otherwise the visualizer.
- **This jack or this browser.** Settings → Playback. TOSLINK is the default.
- **AirPlay 1** to this host. Settings → AirPlay (`Gigawatt 39DB`, …). iPhone/Mac → Pulse → TOSLINK. Pulse resamples 44.1 kHz onto 48 kHz so this jack actually plays.
- Dark Playing and Library UI, Karaoke, Report, 31-band TOSLINK EQ (in Settings)
- Play through the S2 **TOSLINK** jack (`ffmpeg` → `paplay` → Pulse → `imx-spdif`)
- **NAS** SMB share from Settings. Library can browse it; playback reads the share (files stay on the NAS). NAS lyrics stay on-demand (Karaoke → Fetch). Tracks on this disk fetch lyrics in the background; Library shows a progress bar.
- **Savant** RacePoint profile (`docs/savant/georgietech_gigawatt.xml`): TOSLINK media server, telnet **:5004**. Not SMS-102A.

No Spotify, DLNA, SSC expanders, AirPlay 2, or multi-host linking.

Live UI: [http://192.168.1.142/](http://192.168.1.142/)

On a phone: open the UI in Safari/Chrome, then **Add to Home Screen**.

| Piece | Path |
|---|---|
| Code | `/data/www` |
| Library | `/data/music` |
| Pulse | `crypt-pulse.service` |

## Host

- Hardware: [docs/HOST-142.md](docs/HOST-142.md)
- Retired DualLite mule: [docs/HOST.md](docs/HOST.md)
- Deploy: [docs/DEPLOY.md](docs/DEPLOY.md)
