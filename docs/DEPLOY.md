# Deploy notes — Gigawatt V2.2.31

Live target: **192.168.1.142** (SHC-S2-00 Quad). Never 192.168.1.40 / .178 / .179 / .180.

Do not `dd` a DualLite eMMC onto an SHC-2000. DualLite **192.168.1.179** is retired — `push-host.sh` refuses it.

SSH user: `RPM`. Do not commit the password. `scp -O` from modern macOS.

## Push this tag

```sh
git clone https://github.com/GeorgieTech/GIGAWATT-V2.git
cd GIGAWATT-V2
git checkout v2.2.31
chmod +x scripts/push-host.sh host-webui/install-on-host.sh
scripts/push-host.sh 192.168.1.142
```

Confirm:

```sh
curl -s http://192.168.1.142/api/status | python3 -c "import json,sys; print(json.load(sys.stdin).get('version'))"
```

It must print `2.2.31`. AirPlay binaries land in `/data/opt/airplay`. NAS tools land in `/data/opt/nas`. Time Clock UI is removed. Playing shows title/cover/queue; TrueNAS dataset paths split to the SMB share name.

## First-time unit (once per chassis)

1. Mask `savant-startup-manager.service` and `nginx.service`.
2. Stop them. Set default target to `multi-user.target`.
3. Stop leftover Pulse (`pulseaudio`) if Savant left one running.
4. Install files in `/data/www`, music dir `/data/music`.
5. Enable `crypt-hostname`, `crypt-pulse`, `crypt-web`.

Savant images on the eMMC are not deleted. Cluster / peer linking was removed in V2.2.25.
