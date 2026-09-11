# CRYPT/1 — host-to-host protocol (deploy this)

Status: **Gigawatt V2.1.0** — linked hosts share libraries only. Unlink is sticky and **splits catalogs**: this jack lists only home files; copies pulled from that host are removed here. No auto-relink from Settings probe or boot hello. Copy-then-play onto **this** jack. Group play / Unison / CLOCK fan-out are retired and will be revisited later. Discovery is still CRYPT/1 multicast `239.18.20.1:41880` plus JSON broadcast fallback. `beacon.igmp_ok` / `igmp_error` stay sticky. libver is the catalog ETag. BEACON still has a unison bit; V2 always sends it false. Install the **same tag** on every host (`scripts/push-host.sh`).

Targets: **192.168.1.179** (DualLite mule, UID `001AAE10E4090000`) and **192.168.1.142** (SHC-2000 Quad, UID `001AAE0739DB0000`). Never **.40 / .178 / .180**.

Python 3.8 **stdlib only**. No apt. No extra daemons. Copy-then-play stays. Unique by Savant UID.

This file is the contract for the next grok **build + deploy**. The code in this branch already contains the wire codec and the dual-stack path; deploy both chassis in one window so one host is never speaking only JSON while the other has already dropped broadcast.

## What we measured

This cloud agent cannot complete a two-host LAN conversation. UDP probes to `:41880` on `.179` and `.142` from the agent VM time out (no path onto the lab subnet). Evidence is therefore:

1. Unit tests on V1.1.10 `host-webui/test_peers.py` — **14 passed**.
2. Static runtime of `peers.py` + `unison.py` as shipped in V1.1.10.
3. New `host-webui/test_crypt_wire.py` round-trips for CRYPT/1.

Lab confirmation after deploy — first-class check on **both** hosts (as `RPM`). `ss` plus a join-group recv of `CRPT` is required; send-to-group does not prove membership (`IP_MULTICAST_LOOP` is 0). Settings must show `beacon.igmp_error` if `IP_ADD_MEMBERSHIP` failed.

```sh
ss -ulnp | grep 41880
# should show crypt-web / python bound 0.0.0.0:41880

python3 - <<'PY'
import socket, struct, time
G,P="239.18.20.1",41880
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(("0.0.0.0",P))
mreq=struct.pack("4s4s", socket.inet_aton(G), socket.inet_aton("0.0.0.0"))
s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
s.settimeout(6)
print("waiting")
print(s.recvfrom(512))
PY
```

You should see a `CRPT` binary beacon within 2 s, and (until we drop it) a JSON beacon to `192.168.1.255`.

## V1.1.10 as shipped — how the two hosts talk today

```
.179 DualLite                              .142 Quad
─────────────                              ────────
UDP JSON every 4s  ──broadcast .255:41880──►  (and reverse)
GET /api/hello     ◄──────── HTTP ────────►  Settings “On the LAN”
GET /api/library?local=1  (full catalog, 8 s TTL, 2 MiB cap)
GET /api/media     ── copy 256 KiB chunks, 30 s timeout ──► /data/music
POST play/pause    ── Unison fan-out (HTTP, 4 s timeout)
GET /api/clock     ── follower poll every 350 ms (~3 Hz)
```

Discovery is **UDP broadcast JSON** (`SO_BROADCAST` to `192.168.1.255:41880`). Identity is **Savant UID**. Link is two-way `peers.json` shelves. Play is **copy then local ffmpeg**. Unison TOSLINK is optional: HTTP commands plus HTTP clock poll.

That works for two boxes on a quiet lab LAN. It does not scale, and it burns DualLite CPU for the wrong reasons.

## What is slow or fragile (root causes)

### 1. Broadcast is the wrong bus

`192.168.1.255` wakes every IPv4 stack on the VLAN (phones, Savant, printers). Cheap switches sometimes rate-limit or drop directed broadcast. There is no group: a third CRYPT host cannot join without the whole LAN hearing it. JSON text is ~180 bytes plus `json.loads` on DualLite every packet.

**Fix:** administratively scoped **multicast** `239.18.20.1:41880`, TTL **1**, IGMP join on `eth0`. Only CRYPT members receive it. Binary CRYPT/1 is ~100 bytes and checksummed.

### 2. One thread both sends and blocks on `recvfrom`

V1.1.10 uses a 1 s socket timeout and a 4 s send period. While `recvfrom` blocks, send is delayed. Settings `probe=1` then hammers every candidate with HTTP hello.

**Fix:** 250 ms recv timeout, beacon every **2 s**, probe stays off unless the Settings page asks. Binary + JSON both go out for one release so a mixed pair still sees each other.

### 3. Unison clock is HTTP at 3 Hz

Follower `GET /api/clock` every 0.35 s, 2 s timeout, JSON parse, then `follow_heard()`. That is a full HTTP transaction per tick on a 1 GB DualLite, and 350 ms is coarse for optical PLL steer (the Time Clock already thinks in milliseconds).

**Fix:** conductor emits a **CLOCK** datagram on the same multicast group every **50 ms** while Unison is on and it is playing. Follower applies `follow_heard()` from UDP. HTTP `/api/clock` remains the fallback if no CLOCK packet arrives for 250 ms (mixed-version or IGMP miss).

Play/Pause/Seek/Stop stay HTTP for now. Those are rare. Clock is the hot path. CLOCK silence is **not** pause (Wi‑Fi blips must not false-pause). If CLOCK is quiet, the follower GETs `/api/clock`: pause or stop local paplay only when the conductor reports `playing: false` while this host is Unison-following and still playing; if `/api/clock` is unreachable, hold last state.

### 3b. V1.1.11 Unison still slapped — follower was seeking, not riding CLOCK

Lab pair, same `Fade Away.flac`, Unison on, both TOSLINKs audible from one spot:

| | DualLite .179 follower | Quad .142 conductor |
|---|---|---|
| Time Clock `lat_ms` | 407 | 409 |
| PLL | still locking | locked |
| Unison `drift_ms` | hunts, median ~370 ms, −50..+440 | — |

The two **path delays match**. Each room alone is fine. Overlap hears two performances because **heard positions were not held**.

Grok’s V1.1.11 ship (`e6413fa`) did **not** change `follow_heard()`. It kept V1.1.10 policy: **seek when |err| ≥ 80 ms**, cooldown **2 s**, and `seek(target_heard + lat)`. A seek **kills ffmpeg+paplay**, sets `_clock_on = False`, and fills ~400 ms of Pulse again. CLOCK is 20 Hz, so during that fill `_clock_locked` clamps `heard` to the new `offset` (~`lat` ahead). The next tick sees ~400 ms error and, after 2 s, seeks again. DualLite never finishes the 6-sample latency lock. Nudges wrote `_play_corr`, which the decoder PLL immediately undoes — display-only, **not** the optical jack.

That is the slap-back, not paplay vs paplay.

**Fix (this drop):**

- While the pipe is warming (`t0 + lat + 120 ms` after every play/seek), **hold**. A ~400 ms clamp is not a CLOCK error.
- Catch-up seek at most every **8 s**, and only if |err| ≥ **120 ms**. Jumps ≥ **1.25 s** still seek (user seek / late join).
- |err| < 18 ms: hold. Local **ahead** 18–80 ms: brief SIGSTOP (no ffmpeg restart). Local **behind** in that band: hold — a seek would cost a full path delay.
- Do not steal `_play_corr` from the decoder PLL.
- Turning Unison **on** while the conductor is already playing fans the current **playback** position so the follower does not start the file at 0.

Deploy `player.py`, `unison.py`, `server.py` on **both** hosts, restart `crypt-web`. Expect follower PLL to reach **locked**, `drift_ms` to sit still near 0 (tens of ms, not hundreds), and no 400 ms snaps in the hallway.

### 4. Library merge refetches the whole catalog

`fetch_shelf()` pulls `GET /api/library?local=1` (up to 2 MiB JSON). Library page, play, and owner lookup all hit that.

**Fix:** each beacon carries a 64-bit **libver** (FNV-1a of `name:size:mtime` rows). libver is the ETag: skip HTTP only when it matches the last successful fetch. A new advertised libver bypasses the 8 s success TTL and refetches immediately. Error retries stay on a 2 s backoff. First fetch still happens; file changes flip libver.

### 5. Copy path has no resume and no verify

`ensure()` uses a 30 s `urlopen`, 256 KiB chunks, no `Range`, no hash. A DualLite hiccup leaves `.part` deleted and retries from byte 0.

**Fix (phase 2, after CRYPT/1 is live):** `Range` resume on `.part`, compare `Content-Length` / size from the catalog row, keep copy-then-play (never stream into ffmpeg). Not required to ship CLOCK/beacon.

### 6. Hello gossip grows

`/api/hello` returns `shelves` plus up to 12 `seen` rows. Fine for two hosts. At four SHC-2000s it becomes a mesh of HTTP copies of the same roster.

**Fix (phase 2):** hello returns self + libver + linked UIDs only. Roster comes from multicast beacons. Do not expand gossip in this drop.

## CRYPT/1 datagram (already in `host-webui/crypt_wire.py`)

UDP, max **512** bytes, port **41880** (same as today).

```
offset  size  field
0       4     magic     "CRPT"
4       1     version   1
5       1     type      1=BEACON  2=CLOCK  3=LIBVER  4=ACK
6       1     flags     bit0 linked (this host has any shelves)  bit1 unison  bit2 playing
7       1     uid_len   1..16
8       4     seq       uint32 big-endian
12      1     checksum  sum of all bytes with this field zeroed, mod 256
13      3     pad       0
16      n     uid       ASCII hex, no colons, upper case
16+n    …     payload   type-specific
```

Checksum is **not** crypto. It only drops corruption. Lab LAN is trusted; blocked IPs still never join (`192.168.1.40/178/180`, off-LAN, localhost).

### BEACON payload

`port u16 | tracks u16 | libver u64 | ip | model | version` (see `encode_beacon`). Sent to **`239.18.20.1`** every 2 s. JSON broadcast to `192.168.1.255` is still sent in this release (`decode_any` accepts both).

### CLOCK payload

`heard_us i64 | mono_us i64 | path_us i64 | state u8`  
Times are microseconds (`-1` = unknown). `heard` is Host Time Clock heard position, same meaning as `GET /api/clock` → `player.clock.heard`. Sent every 50 ms by the Unison conductor (the host that is not following).

### LIBVER payload

Optional later: `libver u64 | tracks u16` when the catalog changes, so peers do not wait for the next beacon. BEACON already carries libver; this type is for a burst after a rip/upload.

## Why this is better

| Path | V1.1.10 | CRYPT/1 |
|---|---|---|
| Who hears discovery | Entire `192.168.1.0/24` | IGMP members of `239.18.20.1` |
| Beacon size / parse | JSON, `json.loads` | ~100 bytes, `struct` |
| Beacon period | 4 s, 1 s recv block | 2 s, 250 ms recv |
| Unison clock | HTTP 3 Hz + JSON | UDP 20 Hz, HTTP fallback |
| Catalog refresh | Full JSON every 8 s | HTTP only when libver changes |
| DualLite CPU | HTTP + JSON on the audio box | Datagrams; HTTP for rare commands |
| Third / fourth host | More broadcast + more hello | Same group, UID still unique |

Copy-then-play is unchanged on purpose. Streaming into ffmpeg would fight the Time Clock and the optical jack. CLUSTER.md’s four-host farm still wants a separate console later; this protocol is what the chassis speak **to each other** until that console exists.

Multicast is the right default on this VLAN. Unicast CLOCK to the linked peer IP is a fine extra (lower loss on cheap Wi-Fi) but both hosts are wired `eth0` today — group send is enough.

## Files grok must ship

| File | Role |
|---|---|
| `host-webui/crypt_wire.py` | **New.** Encode/decode, FNV libver, IGMP join. |
| `host-webui/peers.py` | Dual-stack beacon, libver short-circuit on `fetch_shelf`, `send_dgram`. Join failure is `beacon.igmp_*` and is not cleared by send. |
| `host-webui/unison.py` | CLOCK emit 50 ms; UDP `note_clock`; HTTP `/api/clock` if UDP goes quiet. Snapshot `via` is `udp` or `http-clock`. |
| `host-webui/settings.html` | Paints `beacon.igmp_error` so Settings can show join failed while send still looks Live. |
| `host-webui/server.py` | `PEERS.note_local_catalog()` so beacons carry a real libver. |
| `host-webui/test_crypt_wire.py` | Wire tests. |
| `host-webui/test_peers.py` | Includes libver skip test. |

Do **not** add pip packages, systemd units, or a second UDP port.

## Deploy (both hosts, same session)

Stdlib files only. SSH user `RPM`. `scp -O` from macOS. Password not in git.

From repo root (add `crypt_wire.py` to the existing V1.1.10 copy list in [DEPLOY.md](DEPLOY.md)):

```sh
scp -O host-webui/crypt_wire.py host-webui/peers.py host-webui/unison.py host-webui/server.py \
  host-webui/settings.html \
  RPM@192.168.1.179:/tmp/ RPM@192.168.1.142:/tmp/
```

On **each** host, as root via `sudo env bash`:

```sh
cp /tmp/crypt_wire.py /tmp/peers.py /tmp/unison.py /tmp/server.py /tmp/settings.html /data/www/
chown RPM:RPM /data/www/crypt_wire.py /data/www/peers.py /data/www/unison.py /data/www/server.py /data/www/settings.html
systemctl restart crypt-web.service
```

Restart **.179 and .142 within a minute of each other**. Pulse / hostname units stay.

### Checks

1. `systemctl is-active crypt-web` is `active` on both.
2. On **both** hosts: `ss -ulnp | grep 41880` shows crypt-web bound `0.0.0.0:41880`, and the join-group recv snippet above prints a `CRPT` datagram within 6 s. Optional: `grep 239.18.20.1 /proc/net/igmp`. Send success alone is not membership — Settings must show an IGMP join error if join failed, even when blades are Live via JSON broadcast.
3. Settings → On the LAN still shows the other UID (JSON beacon covers mixed seconds).
4. After both are up, `python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1/api/hello').read()[:200])"` still returns `crypt:1`.
5. Link remains two-way. Play a shelf track: still copy then TOSLINK.
6. Optional Unison, same track, both optical jacks in earshot: follower PLL should **lock**. `drift_ms` should hold near 0, not hunt ±400 ms. A hallway between zones should not sound like two bands. Unison snapshot `via` is `udp` while CLOCK arrives; `http-clock` if no UDP CLOCK for >250 ms.

### Rollback

Copy the V1.1.10 `peers.py` / `unison.py` / `server.py` back and **delete** `/data/www/crypt_wire.py` only after those three files no longer import it. Restart `crypt-web`.

## What grok should not change in this drop

- Blocked IPs and HTTP-only (no HTTPS) URL guard.
- Copy-then-play / no ffmpeg HTTP input.
- UID uniqueness and two-way `peers.json`.
- Relays / SSC (removed on purpose in V1.1.2).
- Time Clock PLL math inside `player.py` except consuming CLOCK `heard`.
- Scanning the whole disk every beacon — libver comes from the last `/api/library` local list.

## Phase 2 (do not block this deploy)

- Drop JSON broadcast once both hosts have been on CRYPT/1 for a week.
- HTTP `Range` resume on `ensure()`.
- Slim `/api/hello` (no gossip `seen` blob).
- Prefetch **next** hot-cache file on the listening host (CLUSTER.md).
- Optional unicast CLOCK to the linked IPv4 in addition to the group.

## Tests before deploy

```sh
python3 host-webui/test_crypt_wire.py
python3 host-webui/test_peers.py
python3 host-webui/test_clock.py
python3 host-webui/test_unison.py
```
