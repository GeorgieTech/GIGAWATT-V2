#!/usr/bin/env bash
# Idempotent repository bootstrap for the Gigawatt V2 web UI.
# The app itself is Python 3 stdlib only (no pip deps). This prepares the
# system tools and the writable /data layout the server expects.
set -euo pipefail

# System tools: ffmpeg drives the TOSLINK decode path, paplay/pactl talk to
# PulseAudio. ffmpeg is usually already in the base image; pulseaudio is not.
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v paplay >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    ffmpeg pulseaudio pulseaudio-utils
fi

# Writable data layout mirroring the on-host /data used in production.
sudo mkdir -p /data
sudo chown -R "$(id -u):$(id -g)" /data
mkdir -p /data/music /data/crypt

# Seed a small sample library so the UI has playable content out of the box.
cd /data/music
if [ ! -f "Test Tone A - 440Hz.flac" ]; then
  ffmpeg -y -loglevel error -f lavfi -i "sine=frequency=440:duration=12" \
    -ac 2 -ar 44100 "Test Tone A - 440Hz.flac"
fi
if [ ! -f "Test Tone B - 220Hz.flac" ]; then
  ffmpeg -y -loglevel error -f lavfi -i "sine=frequency=220:duration=15" \
    -ac 2 -ar 44100 "Test Tone B - 220Hz.flac"
fi
if [ ! -f "Test Tone C - Chord.mp3" ]; then
  ffmpeg -y -loglevel error -f lavfi \
    -i "aevalsrc=0.3*sin(2*PI*261.63*t)+0.3*sin(2*PI*329.63*t)+0.3*sin(2*PI*392*t):d=10:s=44100" \
    -ac 2 "Test Tone C - Chord.mp3"
fi

echo "install.sh: ready ($(ls -1 /data/music | wc -l) sample tracks in /data/music)"
