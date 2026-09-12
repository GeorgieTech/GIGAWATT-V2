# AirPlay runtime (Gigawatt V2)

armv7 `shairport-sync` **3.3.7** plus extra libs this Yocto image does not ship.

Installed on the host as `/data/opt/airplay`. Settings starts and stops it.

This is **AirPlay 1** (ALAC) to Pulse, then TOSLINK. Each chassis advertises its own name (`Gigawatt E409`, `Gigawatt 39DB`, …) and you can rename it on Settings.

Metadata pipe: `/tmp/gigawatt-airplay.meta` (XML from 3.3.7).
