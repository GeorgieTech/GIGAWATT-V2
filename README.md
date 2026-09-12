# Gigawatt V2.2.12

Repo: [`GIGAWATT-V2`](https://github.com/GeorgieTech/GIGAWATT-V2)

A local TOSLINK music player on recycled Savant S2 hosts (SHC-S2-00 Quad). Library on disk, web UI on port 80, optical out.

**Current release: [V2.2.12](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.12)** (`v2.2.12`). Previous: [V2.2.11](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.11) · [V2.2.10](https://github.com/GeorgieTech/GIGAWATT-V2/releases/tag/v2.2.10).

This project is **not affiliated with Savant Systems**.

Live target: **192.168.1.142** (SHC-S2-00 Quad, master music server). A second SHC-2000 will join later. Do not use 192.168.1.40 (live Carrillos Resident), 192.168.1.178 (Gigawatt V1), 192.168.1.179 (retired DualLite mule), or 192.168.1.180 (Giggwatt Beta1).

Lineage: this is the V2 rewrite of the CRYPT DualLite/Quad lab player (`savant-host-s2-smart-home-processor-BETA1`). Wire discovery is still CRYPT/1 so a later host can **Link library** the same way.

## What V2.2.0 does

- **Album covers from Cover Art Archive** (same source as the Jellyfin Cover Art Archive plugin). Local `cover.jpg` / embedded art first, then MusicBrainz release → coverartarchive.org. Playing shows the cover when found, otherwise the visualizer. Library thumbnails do the same.

- **This jack or this browser.** Settings → Playback. TOSLINK is the default. This browser plays on the phone or laptop that opened the page (HTML5 audio from `/api/media`). Only one at a time.
- **AirPlay 1 to this host.** Settings → AirPlay. Each chassis advertises its own name (`Gigawatt 39DB`, …). You can rename it. iPhone/Mac → Pulse → TOSLINK. Same armv7 `shairport-sync` as Gigawatt Beta 2.
- **Link shares libraries only.** Linked hosts merge catalogs both ways. Play copies the file onto *this* host, then this TOSLINK. Hosts do not play as a group and do not Unison.
- **Unlink splits libraries.** Confirming Unlink drops the shelf, forgets that catalog, and removes copies that were pulled here from that host. This jack then lists only files that live on this disk. Home files are not deleted. Unlink stays unlinked until you tap **Link library**.
- **Identical clone.** `scripts/push-host.sh <ip>` installs this tag on another converted S2. Every host on the fleet should report the same `version` from `/api/status`.
- Play a track that lives on the other host: copy-then-play onto this jack. No ffmpeg HTTP stream.
- Dark Playing and Library UI, Karaoke, Report, 31-band TOSLINK EQ
- Settings: LAN discovery by Savant UID. **Live** is heard on the wire; **Linked** merges libraries. Do not trust Live for IGMP — `beacon.igmp_ok` / `igmp_error` stay sticky if `IP_ADD_MEMBERSHIP` failed
- Discovery uses multicast `239.18.20.1:41880` with JSON broadcast as fallback. Library merge treats advertised **libver** as an ETag
- Play through the S2 **TOSLINK** jack (`ffmpeg` → `paplay` → Pulse → `imx-spdif`)
- Host Time Clock so waveform, FFT, and karaoke follow audible TOSLINK time

No Spotify, DLNA, NAS, or SSC expanders. Group / Unison play is out of this version and will be revisited later. AirPlay 1 is on; AirPlay 2 is not.

Live UI: [http://192.168.1.142/](http://192.168.1.142/)

On a phone: open the UI in Safari/Chrome, then **Add to Home Screen**.

| Piece | Path |
|---|---|
| Code | `/data/www` |
| Library | `/data/music` |
| Pulse | `crypt-pulse.service` using `/etc/pulse/savant-vcd.pa` |

## Host

- Hardware (master SHC-2000): [docs/HOST-142.md](docs/HOST-142.md)
- Retired DualLite mule: [docs/HOST.md](docs/HOST.md)
- Deploy: [docs/DEPLOY.md](docs/DEPLOY.md)
- Fleet plan: [docs/CLUSTER.md](docs/CLUSTER.md)
- Wire: [docs/PEER-PROTOCOL.md](docs/PEER-PROTOCOL.md)

## License

[MIT](LICENSE) © 2026 George Carrillo.
