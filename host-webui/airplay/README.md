# AirPlay runtime (Gigawatt V2)

armv7 `shairport-sync` **3.3.7** plus extra libs this Yocto image does not ship.

Installed on the host as `/data/opt/airplay`. Settings starts and stops it.

This is **AirPlay 1** (ALAC) to Pulse, then TOSLINK. Each chassis advertises its own name (`Gigawatt E409`, `Gigawatt 39DB`, …) and you can rename it on Settings.

AirPlay arrives at **44.1 / 48 kHz**. The Savant `imx-spdif` TOSLINK word clock is fixed at **96 kHz**. Pulse remaps once at the sink (`speex-float-1`, `default-sample-rate=96000`, `alternate-sample-rate=48000`). Host Time Clock stays on library paplay only — it does not steer AirPlay.

Metadata pipe: `/tmp/gigawatt-airplay.meta` (XML from 3.3.7).
