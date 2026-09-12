#!/usr/bin/env bash
# Per-boot runtime init: bring up a headless PulseAudio daemon with a null
# "toslink" sink so the ffmpeg -> paplay playback path works without real
# TOSLINK hardware. Idempotent: safe to run on every boot.
set -euo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
sudo mkdir -p "$XDG_RUNTIME_DIR"
sudo chown "$(id -u):$(id -g)" "$XDG_RUNTIME_DIR"

# Start PulseAudio only if it is not already answering.
if ! pactl info >/dev/null 2>&1; then
  pulseaudio --start --exit-idle-time=-1 --log-target=stderr || true
  for _ in $(seq 1 20); do
    pactl info >/dev/null 2>&1 && break
    sleep 0.5
  done
fi

# Create the 96 kHz null sink that stands in for the imx-spdif TOSLINK jack.
if ! pactl list short sinks | grep -qw toslink; then
  pactl load-module module-null-sink sink_name=toslink rate=96000 channels=2 \
    sink_properties=device.description=TOSLINK >/dev/null
fi
pactl set-default-sink toslink || true

if pactl info >/dev/null 2>&1; then
  echo "start.sh: PulseAudio ready, default sink = $(pactl get-default-sink)"
else
  echo "start.sh: WARNING PulseAudio did not come up; playback will be unavailable" >&2
fi
