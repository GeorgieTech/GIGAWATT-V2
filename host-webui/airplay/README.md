# AirPlay runtime (Gigawatt V2)

armv7 `shairport-sync` **3.3.7** plus extra libs this Yocto image does not ship. Same binary as Gigawatt Beta2.

Installed on the host as `/data/opt/airplay`. Settings starts and stops it.

This is **AirPlay 1** (ALAC) to Pulse, then TOSLINK. Stuffing matches Beta2 (`interpolation = "basic"`, host volume). Pulse sits at 48 kHz like Beta2 so AirPlay 44.1 is resampled onto a rate this jack actually plays. Do **not** open imx-spdif at 44.1 kHz — that rate reports RUNNING with 0 µs latency and the optical is silent. Library paplay still runs 96 kHz.

The Pulse stream starts corked. This TOSLINK path is ~800 ms late, which is far past shairport-sync’s 50 ms resync window, so it used to flush+cork forever (UI said Playing, jack silent). Resync mute is off; latency offset matches the jack.

Each chassis advertises its own name (`Gigawatt E409`, `Gigawatt 39DB`, …) and you can rename it on Settings.

Metadata pipe: `/tmp/gigawatt-airplay.meta` (XML from 3.3.7).
