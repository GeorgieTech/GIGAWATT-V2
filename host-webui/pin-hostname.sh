#!/bin/sh
# savant-init rewrites sav-<uid> every boot. Pin crypt-<uid> after that.
HOSTUID=$(hostname | sed 's/^sav-//;s/^crypt-//;s/^GWH-//')
NAME="crypt-$HOSTUID"
if [ "$(hostname)" != "$NAME" ]; then
  echo "$NAME" > /etc/hostname
  hostname "$NAME"
fi
exit 0
