#!/bin/bash
# Install the Gigawatt files already in /tmp onto this chassis.
# Same script on every host. Does not touch /data/music home files.
set -e
mkdir -p /data/www /data/music /data/crypt
cp /tmp/VERSION /tmp/index.html /tmp/library.html /tmp/eq.html /tmp/karaoke.html /tmp/report.html /tmp/settings.html /tmp/crypt.css \
  /tmp/server.py /tmp/player.py /tmp/library.py /tmp/wave.py /tmp/lyrics.py /tmp/research.py /tmp/report.py /tmp/essay.py /tmp/peers.py /tmp/crypt_wire.py \
  /tmp/airplay.py /tmp/playback.py /tmp/cover.py /tmp/wifi.py /tmp/gigawatt-pulse.pa \
  /tmp/pin-hostname.sh /tmp/manifest.webmanifest /tmp/favicon.svg /tmp/icon.png /tmp/apple-touch-icon.png /data/www/
rm -f /data/www/unison.py
chmod +x /data/www/pin-hostname.sh /data/www/server.py /data/www/player.py
APSRC=""
if [ -x /tmp/gigawatt-airplay/shairport-sync ]; then
  APSRC=/tmp/gigawatt-airplay
elif [ -x /tmp/gigawatt-airplay/airplay/shairport-sync ]; then
  APSRC=/tmp/gigawatt-airplay/airplay
elif [ -x /tmp/airplay/shairport-sync ]; then
  APSRC=/tmp/airplay
fi
if [ -n "$APSRC" ]; then
  rm -rf /data/opt/airplay
  mkdir -p /data/opt
  cp -a "$APSRC" /data/opt/airplay
  chmod +x /data/opt/airplay/run-shairport /data/opt/airplay/shairport-sync || true
  chown -R RPM:RPM /data/opt/airplay
fi
chown -R RPM:RPM /data/www /data/music /data/crypt
if [ -f /etc/pulse/daemon.conf ]; then
  if grep -q 'GIGAWATT-AUDIO' /etc/pulse/daemon.conf; then
    sed -i '/# GIGAWATT-AUDIO/,$d' /etc/pulse/daemon.conf
  fi
  cat >> /etc/pulse/daemon.conf << 'EOF'

# GIGAWATT-AUDIO
resample-method = speex-float-1
avoid-resampling = yes
default-sample-rate = 96000
alternate-sample-rate = 44100
default-fragments = 8
default-fragment-size-msec = 50
high-priority = yes
EOF
fi
cp /tmp/crypt-web.service /tmp/crypt-pulse.service /tmp/crypt-hostname.service /etc/systemd/system/
systemctl mask savant-startup-manager.service nginx.service systemd-journal-upload.service || true
systemctl disable --now systemd-journal-upload.service 2>/dev/null || true
# Persistent sshd: socket-activated sshd can drop kex when ffmpeg is on CPU0.
if [ -x /usr/sbin/sshd ]; then
  cat > /etc/systemd/system/sshd.service << 'EOF'
[Unit]
Description=OpenSSH server daemon
After=network.target sshdgenkeys.service
Wants=sshdgenkeys.service
Conflicts=sshd.socket

[Service]
Type=simple
ExecStartPre=/bin/mkdir -p /var/run/sshd
ExecStartPre=/usr/sbin/sshd -t
ExecStart=/usr/sbin/sshd -D
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
fi
journalctl --vacuum-size=8M >/dev/null 2>&1 || true
for f in /var/log/syslog.1 /var/log/daemon.log.1 /var/log/kern.log.1; do
  if [ -f "$f" ]; then
    : > "$f"
  fi
done
timeout 8 systemctl stop nginx.service || true
timeout 8 systemctl stop savant-startup-manager.service || true
pkill -9 -f startupManager || true
pkill -9 -f '/usr/local/bin/avc' || true
pkill -9 nginx || true
timeout 5 systemctl stop pulseaudio.service || true
killall -9 pulseaudio || true
sleep 1
systemctl set-default multi-user.target
systemctl daemon-reload
systemctl enable crypt-hostname.service crypt-pulse.service crypt-web.service
systemctl restart crypt-hostname.service || true
systemctl restart crypt-pulse.service
sleep 2
systemctl restart crypt-web.service
sleep 2
if [ -f /etc/systemd/system/sshd.service ] && /usr/sbin/sshd -t 2>/dev/null; then
  systemctl stop sshd.socket 2>/dev/null || true
  if systemctl start sshd.service; then
    systemctl enable sshd.service
    systemctl disable sshd.socket 2>/dev/null || true
  else
    systemctl start sshd.socket 2>/dev/null || true
  fi
fi
echo STATUS
systemctl is-active crypt-web.service || true
systemctl is-active crypt-pulse.service || true
systemctl is-active crypt-hostname.service || true
hostname
python3 -c "import sys; sys.path.insert(0, '/data/www'); import peers; print('version', peers.VERSION)"
test ! -e /data/www/unison.py
ss -tln | grep -E ':80|:443' || true
systemctl status crypt-web.service --no-pager -l | head -20 || true
