#!/bin/sh
# savant-init rewrites sav-<uid> every boot. Pin crypt-<uid> after that.
HOSTUID=$(hostname | sed 's/^sav-//;s/^crypt-//;s/^GWH-//')
NAME="crypt-$HOSTUID"
if [ "$(hostname)" != "$NAME" ]; then
  echo "$NAME" > /etc/hostname
  hostname "$NAME"
fi
# Keep the AR6004 radio on so Settings can join the house Wi-Fi for AirPlay.
connmanctl enable wifi >/dev/null 2>&1 || true
# fec ethernet IRQs default to CPU0 with ffmpeg/paplay. Move them to CPU3.
for n in 60 61; do
  if [ -w "/proc/irq/$n/smp_affinity" ]; then
    echo 8 > "/proc/irq/$n/smp_affinity" 2>/dev/null || true
  fi
done
exit 0
