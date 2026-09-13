#!/bin/sh
# After AirPlay, put TOSLINK back at 96 kHz so the next library paplay
# matches Host Time Clock. Safe: AirPlay audio has already stopped.
export PULSE_SERVER="${PULSE_SERVER:-unix:/var/run/pulse/native}"
SINK="@DEFAULT_SINK@"

got=`pactl list sinks 2>/dev/null | sed -n 's/.*Sample Specification:.* \([0-9][0-9]*\)Hz.*/\1/p' | head -n 1`
if [ "$got" = "96000" ]; then
  exit 0
fi

pactl suspend-sink "$SINK" 1 >/dev/null 2>&1 || true
sleep 0.2
pactl suspend-sink "$SINK" 0 >/dev/null 2>&1 || true
sleep 0.1
dd if=/dev/zero bs=30720 count=1 2>/dev/null | \
  paplay --device="$SINK" --raw --format=s16le --rate=96000 --channels=2 \
    --latency-msec=50 --client-name=TOSLINK-RATE >/dev/null 2>&1 || true
exit 0
