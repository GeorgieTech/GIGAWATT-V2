#!/bin/sh
# shairport-sync runs this with wait_for_completion=yes BEFORE audio.
# Gigawatt Beta2 never locked TOSLINK at 96 kHz, so AirPlay 44.1 played
# straight into Pulse. V2 library paplay holds imx-spdif at 96 kHz; if we
# leave it, Pulse resamples 44.1→96 and the jack skips. Open 44.1 first.
# Never call this after the AirPlay stream is already flowing.
export PULSE_SERVER="${PULSE_SERVER:-unix:/var/run/pulse/native}"
SINK="@DEFAULT_SINK@"

sink_rate() {
  pactl list sinks 2>/dev/null | sed -n 's/.*Sample Specification:.* \([0-9][0-9]*\)Hz.*/\1/p' | head -n 1
}

kick() {
  rate="$1"
  if [ "$rate" = "44100" ]; then
    bytes=14112
  else
    bytes=15360
  fi
  dd if=/dev/zero bs="$bytes" count=1 2>/dev/null | \
    paplay --device="$SINK" --raw --format=s16le --rate="$rate" --channels=2 \
      --latency-msec=50 --client-name=TOSLINK-RATE >/dev/null 2>&1 || true
}

# Library paplay holds the 96 kHz sink. Stop it so Pulse can reopen SPDIF.
pkill -f -- '--client-name=CRYPT' >/dev/null 2>&1 || true
sleep 0.15

got=`sink_rate`
if [ "$got" = "44100" ]; then
  exit 0
fi

pactl suspend-sink "$SINK" 1 >/dev/null 2>&1 || true
sleep 0.2
pactl suspend-sink "$SINK" 0 >/dev/null 2>&1 || true
sleep 0.1

for rate in 44100 48000; do
  got=`sink_rate`
  if [ "$got" = "$rate" ]; then
    exit 0
  fi
  kick "$rate"
  sleep 0.12
  got=`sink_rate`
  if [ "$got" = "$rate" ]; then
    exit 0
  fi
done
exit 0
