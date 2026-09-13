# AirPlay runtime (Gigawatt V2)

armv7 `shairport-sync` **3.3.7** plus extra libs this Yocto image does not ship. Same binary as Gigawatt Beta2.

Installed on the host as `/data/opt/airplay`. Settings starts and stops it.

This is **AirPlay 1** (ALAC) to Pulse, then TOSLINK. Stuffing matches Beta2 (`interpolation = "basic"`, host volume). Before audio, `toslink-airplay-begin.sh` opens imx-spdif at 44.1 kHz so Pulse does not resample into the 96 kHz library jack. After the session, `toslink-airplay-end.sh` restores 96 kHz for Host Time Clock.

Each chassis advertises its own name (`Gigawatt E409`, `Gigawatt 39DB`, …) and you can rename it on Settings.

Metadata pipe: `/tmp/gigawatt-airplay.meta` (XML from 3.3.7).
