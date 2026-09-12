# Future plan — four SHC-2000 Gigawatt engines

Status: **Gigawatt V2.2.1 on one live chassis + the original farm plan**. Master music server is SHC-2000 **192.168.1.142**. DualLite mule **192.168.1.179** is **retired from this lab** — do not SSH, deploy, or link it. Link / unlink is unchanged and will be used when a second SHC-2000 joins. Group play / Unison is out of V2. Path A multicast (`239.18.20.1:41880`) is proven: GS752TPP core `.10` is the IGMP querier. Clone another converted host with `scripts/push-host.sh` from tag **v2.2.1** so versions stay identical. The wire is [PEER-PROTOCOL.md](PEER-PROTOCOL.md).

Goal: three SHC-2000 hosts are **library + job workers**. A fourth SHC-2000 is the **TOSLINK playback cache** — it lists the whole fleet library, but only keeps a few files on its own eMMC while they are about to play, playing, or just played. A **separate application** (not this host UI) sits in front, owns the fleet catalog, copies bytes when needed, fans research jobs out, and consumes the JSON those four hosts produce.

This is a job farm plus a sharded disk on the lab LAN. It is not Kubernetes, not Savant clustering, not one shared TOSLINK, not streaming, and not NAS/DLNA.

Do **not** use **192.168.1.40** (Carrillos Resident), **192.168.1.178** (Gigawatt V1), **192.168.1.179** (retired DualLite), or **192.168.1.180** (Giggwatt Beta1). Do not spoof Carrillos UID `001AAE1C6F5F0000`.

## Picture

```
Separate app we build  (phone / Mac / future CRYPT console)
        │  fleet catalog + HTTP JSON
        ▼
┌────────────────────────────────────────────────────────┐
│  Playback SHC-2000  — TOSLINK, Playing, EQ, Time Clock     │
│  Hot cache only: now + next + last in /data/music          │
│  Source of truth for “what is audible right now”           │
└────────────────────────────────────────────────────────┘
        ▲
        │  copy-then-play  (never stream into ffmpeg / Pulse)
        │  jobs / results  (same CRYPT APIs)
        │
┌────────────────┬────────────────┬────────────────┐
│ Worker A      │ Worker B      │ Worker C      │
│ SHC-2000      │ SHC-2000      │ SHC-2000      │
│ shard of      │ shard of      │ shard of      │
│ /data/music   │ /data/music   │ /data/music   │
│ Report/essay  │ Wave/beat     │ Lyrics +      │
│ research      │ analyze       │ overflow      │
│ (full CRYPT)  │ (full CRYPT)  │ (full CRYPT)  │
└────────────────┴────────────────┴────────────────┘
```

Each of the four hosts runs **the same** CRYPT web UI (`/data/www`, port 80, Python 3.8 stdlib). They do not share `/data`, Pulse, or RAM. The new app is the only piece that knows the fleet.

## Why playback cannot just “play a file on worker B”

`HostPlayer.play()` only opens a real file under **this** host’s `/data/music`, then runs local `ffmpeg` → `paplay` → Pulse → `imx-spdif`. There is no URL/stream path.

Streaming a worker file into playback ffmpeg is rejected:

- Extra daemon / protocol on a Yocto image (stdlib only, no apt).
- LAN jitter would fight Host Time Clock (PLL already locks to **this** box’s paplay/Pulse latency).
- The room hears **playback’s** optical jack only. Playing on worker B’s TOSLINK is the wrong DAC.

Workaround: **copy, then play**. Worker B keeps the home copy. Playback gets a temporary local copy, plays that, then evicts it from the hot cache.

## Hardware

| Role | Chassis | Why |
|---|---|---|
| Playback | SHC-2000 / SHC-S2 Quad (2 GB, 4 cores) | TOSLINK to the room. Hot cache only. Keep Research off this box while music is up. |
| Worker A / B / C | Same SHC-2000 class | Quad + 2 GB is the engine **and** the shelf. |

Do **not** `dd` a DualLite image onto an SHC-2000 (`/data` partition layout differs: DualLite `mmcblk0p2` vs Quad `p3`). Convert each SHC-2000 the same way we converted `.142`, then install Gigawatt from this repo.

Keep them on `192.168.1.0/24` with this project’s existing “never .40 / .178 / .179 / .180” rule.

| Name | IP | Chassis | Notes |
|---|---|---|---|
| Master music server | 192.168.1.142 | SHC-S2-00 Quad | Live. Hostname `crypt-001aae0739db0000` (stamp **39DB**). Full Gigawatt + TOSLINK. See [HOST-142.md](HOST-142.md). |
| DualLite mule | 192.168.1.179 | SHR-S2-00 DualLite | **Retired.** Do not deploy or link. UID `001AAE10E4090000`. See [HOST.md](HOST.md). |
| Next SHC-2000 | TBD | SHC-2000 | Not on the bench yet. Link library after it is on the same tag. |

## Shipped so far vs the brainstorm

This file was written as a **four-host job farm** before the second chassis was even converted. The first path was two hosts talking, sharing a library, and playing. DualLite is now retired. The farm plan is not cancelled. It is not what is running tonight.

### The brainstorm (still the target)

```
Separate funnel app  (not this host UI)
        │
        ▼
Playback SHC-2000 — one TOSLINK to the room, hot cache now/next/last
        ▲
        │  copy-then-play, job JSON
┌───────┴────────┬────────────────┬────────────────┐
│ Worker A      │ Worker B      │ Worker C      │
│ shard of files│ shard of files│ shard of files│
│ Report/essay  │ Wave/beat     │ Lyrics        │
└───────────────┴────────────────┴────────────────┘
```

- DualLite `.179` is **retired from this lab**, not a farm member.
- `.142` is the live master and the first of **four** SHC-2000s. Role (playback vs worker) assigned later.
- One listening room, **one** optical jack. Workers do not make the DAC.
- Files **sharded**: each `name` has one owner. Playback disk is a tiny hot cache, not a second library.
- A **new app** owns the fleet catalog, copies bytes, fans Report / Wave / Lyrics to A/B/C.
- No NAS, no ffmpeg HTTP, no Kubernetes, no Savant clustering.

### What is actually live (V2.2.1)

```
Phone / laptop browser
        │  Gigawatt UI on :80
        ▼
┌──────────────────────┐
│ Quad .142            │
│ SHC-S2-00  2 GB      │
│ stamp 39DB           │
│ master music server  │
│ TOSLINK              │
└──────────────────────┘
```

A second SHC-2000 is not on the LAN yet. **Link library** is still the way two hosts share catalogs when that chassis is converted.

| Brainstorm | Shipped today |
|---|---|
| Separate funnel app owns the catalog | **No app yet.** This host’s Library page lists files on this disk. Linked shelves merge when a second host is linked (`GET /api/library`, `?local=1` so they do not recurse). |
| Four SHC-2000s, DualLite not in the farm | **One chassis:** Quad `.142`. DualLite `.179` retired. Three Quads still missing. |
| One playback TOSLINK; workers silent | **One TOSLINK** on `.142`. Group play / Unison is out of V2. |
| Files sharded across three worker eMMCs | **One shelf.** Home copies live on `.142` (39DB). |
| Playback `/data/music` is now/next/last only | **Copy-then-play exists** for a linked peer, but we do **not** yet evict to a 3-file cache or prefetch next. |
| `CRYPT_PEERS` later for delete fan-out | **Two-way link** in `/data/crypt/peers.json` when a peer is linked. Delete is still **owner-only** (no proxy delete, no fleet cache drop). |
| Discovery somehow in the app | **Settings → On the LAN.** UID-unique blades, Live vs Linked. A later host shows as its own row. |
| HTTP JSON between app and hosts | **CRYPT/1** binary multicast (`239.18.20.1:41880`) for beacon. JSON broadcast still on as fallback. HTTP for hello, library, media copy, Play/Pause/Seek. |
| Report / wave / lyrics fanned to A/B/C | **Still local** on `.142`. No job dispatcher. |
| Funnel UI is a new codebase | **Same Gigawatt web UI** on each converted host. |

Version trail:

| Tag | What landed |
|---|---|
| V1.1.8 | One-way shelf: `.142` lists `.179`. Play copies, then local ffmpeg. |
| V1.1.9 | Settings discovery (UID blades, Live / Linked). |
| V1.1.10 | Link is two-way. Merged catalog with `home_stamp`. Unison TOSLINK (HTTP clock). |
| V1.1.11 | CRYPT/1 multicast + libver so merge is not a full JSON refetch every 8 s. |
| V1.1.12 | Unison **rides CLOCK** instead of seeking the ~400 ms path delay (that seek was the hallway echo). |
| V1.1.13 | Sticky `beacon.igmp_*` (#41). libver is an ETag; BEACON advertises playing/unison (#43). Unison pause/stop confirms over HTTP `/api/clock` (#47). Lab Path A: GS752TPP `.10` querier + snooping on `.10`/`.11`; peer `CRPT` PASS; `igmp_ok` true. Unison earshot still not a hold. |
| V1.1.14 | Dark YouTube Music Playing + Library UI (#52). Protocol unchanged from 1.1.13. |
| V1.1.15 | Library boot `tick` restored; linked merge no longer deadlocks on `APP.lock` + `?local=1`. |
| V1.1.16 | Soft ahead-slew; no catch-seek when the follower is ahead (#56). |
| V1.1.17 | Play-to groups: local jack until you add a linked host. No ffmpeg HTTP stream. |
| V2.0.0 | Project renamed Gigawatt. Link = library share only. Unlink is sticky (no auto-relink). Unison / group play removed. |
| V2.0.1 | Unlink splits libraries: drop remote catalog + hot copies, keep home files. `scripts/push-host.sh` clones the same tag onto another host. |
| V2.0.2 | Unlinked hosts purge leftover copies at boot so Library is home-only until you link again. |
| V2.1.0 | Browser playback and AirPlay 1 (unique renameable name per host). Same shairport-sync as Gigawatt Beta 2. |
| V2.1.1 | AirPlay skip fix: auto/soxr stuffing, 0.5 s buffer, no 1 Hz pactl into Pulse. |
| V2.1.2 | Pulse was suspending TOSLINK (idle timeout 0) and ffmpeg-resampling 44.1→96 kHz. Hold the sink, speex resample, longer ALSA fragments. |
| V2.2.0 | Cover Art Archive album art. Found cover on Playing/Library; visualizer if missing. |
| V2.2.1 | Cover lookup no longer walks the whole library on every clock/status tick. Waveform keeps RAM to 4 caches. |
| V2.2.2 | Playing waveform + Time Clock keep painting when cover art is shown. Status refresh is async; cover defers instead of marking missing during wave analyze. |
| V2.2.3 | Cover defer actually requeues while the worker holds busy; CAA is tried once per album. Status refresh is single-flight under the app lock. |
| V2.2.4 | Time Clock lock: keep SPDIF at 96 kHz (`alternate-sample-rate`), clamp paplay buffer spikes, lock at 16 ms jitter. |
| V2.2.5 | Host hygiene: pactl not 1 Hz once clock is locked; Pulse logs notice; persistent sshd; fec IRQ off CPU0; mask failed journal-upload. |

Hard rules that did **not** change: no Spotify / DLNA / NAS; no ffmpeg HTTP; stdlib only; never `.40` / `.178` / `.179` / `.180`; do not `dd` DualLite eMMC onto a Quad; do not spoof Carrillos UID. AirPlay 1 is on this host; AirPlay 2 is not.

### Still ahead (brainstorm not started)

- Convert two more SHC-2000 workers and a dedicated playback Quad.
- Assign `.142` a farm role (it is “full CRYPT + TOSLINK” until then).
- Shard new uploads (least-full / hash) so `.142` is not the only archive.
- Hot-cache eviction (now / next / last) and prefetch of queue +1.
- Delete fan-out: owner, then drop hot copies and `/data/crypt/*` JSON everywhere.
- Funnel app: one catalog, copy-then-play onto **one** playback jack, Report×3, Wave on owner, Lyrics on C, MusicBrainz token bucket 1/s.
- Drop JSON broadcast after CRYPT/1 has been on both hosts for a while ([PEER-PROTOCOL.md](PEER-PROTOCOL.md) phase 2 / issue #8).
- Stop Settings 4 s `fleet?probe=1` poll (PR #45) so a host does not time out hello while linking.
- Range-resume on `ensure()` copies (PR #42).
- Group play / Unison, if we bring it back later. Not in V2.

Until those four chassis exist, keep shipping Gigawatt on `.142` and treat the Picture at the top as the architecture we are walking toward, not what is racked today.

## Library model — shard on workers, cache on playback

Canonical audio files live on the **workers**, sharded so each `name` has **one owner**. That is how three eMMC shelves become more space than one box. Do **not** copy the whole library onto every worker; that spends three disks on one collection.

Playback `/data/music` is **not** the archive. It is a hot cache of at most:

- **now** — the file ffmpeg is decoding
- **next** (and optionally **next+1**) — already copied before the current track ends
- **last** — so Prev / play-again does not re-copy

Playback’s Library page lists the **fleet catalog** (union of all workers), not a scan of its own `/data/music`. A row can be in the library and still absent from playback disk until play is requested.

### Fleet catalog row

| Field | Why |
|---|---|
| `name` | Stable id. Same string on every host. |
| `owner` | `crypt-work-a` / `b` / `c` — home copy lives here |
| `size` + hash | Two different files must not share a `name` |
| tags | artist / title / album / year / genre — Library, Report, Lyrics without pulling bytes |
| `present_on_play` | Whether playback currently has a hot copy |
| `available` | Owner is up; otherwise show the row as unplayable, not a ghost |

V1.1.8: `GET /api/library` on a viewer host merges shelves from `/data/crypt/peers.json` (with `?local=1` so shelves do not recurse). Play copies the file from the owner via `GET /api/media` then runs local ffmpeg. That is how `.142` used to list DualLite `.179`; DualLite is no longer a shelf.

V1.1.9: Settings → **On the LAN** lists every CRYPT chassis we hear, unique by Savant UID. UDP beacon on port 41880 plus `GET /api/hello`. **Live** = answering. **Linked** = this host lists it as a shelf. A later host shows up as its own blade; Link as shelf writes `peers.json`. `.40` / `.178` / `.179` / `.180` never appear.

V1.1.10: A link is two-way (unison catalog). Each library row is stamped with the chassis that holds the file (`home_stamp`). Play still copies onto the listening host, then local ffmpeg → TOSLINK. Optional **Unison TOSLINK** fans Play/Pause/Seek/Next to linked hosts; the follower steers its Time Clock toward the conductor’s heard clock. No streaming.

V1.1.11: CRYPT/1 multicast on `239.18.20.1:41880` (binary beacon + Unison CLOCK at 20 Hz). JSON broadcast stays as fallback. Library merge skips HTTP when the advertised **libver** matches. See [PEER-PROTOCOL.md](PEER-PROTOCOL.md).

V1.1.12: Unison follower **rides CLOCK**. Do not seek on the ~400 ms path-delay error (that restart is the hallway echo). Hold while the pipe fills, catch-up seek at most every 8 s, brief pause if slightly ahead. Turning Unison on mid-track fans the conductor’s current playback position.

V1.1.13: Settings `beacon.igmp_ok` / `igmp_error` are not cleared by a successful send (#41). Advertised **libver** is the catalog ETag; BEACON flags include playing / unison (#43). Follower pause/stop only after HTTP `/api/clock` says the conductor is not playing — CLOCK silence is not pause (#47). Lab Path A (not in git): Carrillos Core Switch GS752TPP `192.168.1.10` is the VLAN 1 IGMP querier; SW2 `.11` snoops only; CRYPT hosts on `.11` g25 (DualLite) and g9 (Quad); uplink `.10` g1 ↔ `.11` g48. Do not trust Live for IGMP. JSON broadcast (issue #8) is still on. Settings still polls `/api/fleet?probe=1` every 4 s (PR #45 not merged) — DualLite can miss a 4 s hello when both Settings tabs are open.

V1.1.14: Dark YouTube Music–inspired Playing + Library (#52). Same wire as 1.1.13. Unison earshot still not a hold (#56).

V1.1.15: #52 dropped Library `tick()` so the catalog never fetched (empty list). Linked hosts also deadlocked: `GET /api/library` held `APP.lock` while HTTP-fetching the peer, and `?local=1` still called `refresh()`/merge. Local catalog paints first; merge timeout 6 s.

V1.1.16: Lab #56 — Quad `uni_drift` −439 ms while both `clock.locked`. Catch-seek on an *ahead* error restarted paplay (~400 ms slap). Now hold 18–50 ms lead, slew ≤24 ms, catch only when *behind*. Earshot still not a hold.

V1.1.17: Global Unison-on hijacked every linked jack. Play-to group defaults to this TOSLINK; add a linked stamp to copy-then-CLOCK that room. Streaming PCM/HTTP is not this drop (DualLite 1 GB, copy-then-play stays).

### Copy-then-play

1. User picks a row owned by worker B.
2. If playback already has that `name` + matching size/hash in the hot cache, skip the copy.
3. Else **push or pull** B → playback: existing `GET` media on B, existing `POST` upload on playback (400 MB cap), or `scp`. No mount.
4. Refresh playback catalog. Only then `POST /api/play` `{name}` **on playback**.
5. While it plays, prefetch queue item +1 (and +2 if you want a safer gap).
6. On end: start the prefetched next file, **then** evict the previous file if the cache is full. Never unlink `self.media` while ffmpeg/paplay still has that path (EQ rebuild and seek re-open it).

Phone / laptop uploads land on the **least-full worker**, then the catalog row appears on playback. Do not park new FLACs on the TOSLINK box as the home copy.

Delete hits the **owner worker** first, then drops any hot copy on playback and caches on every host that has that `name` (`POST /api/delete` or a future `/api/drop-cache`). No dead `/data/crypt/*` JSON.

### Job files vs play files

| Work | Needs the audio file on that host? |
|---|---|
| TOSLINK play, seek, EQ rebuild | **Yes, on playback**, only while it is in the hot cache |
| Wave / beat analyze | **Yes, on worker B** (owner already has it; no extra copy if B owns the track) |
| Report / essay / MusicBrainz / Wikipedia | **No** — tags from the catalog are enough |
| Lyrics / karaoke timing | Sidecar / cache on C; audio file only if C must decode. Clock still comes from playback |

If wave runs on B and B is the owner, there is nothing to copy. If a non-owner must decode, copy onto that worker for the job, then delete the temp copy when the job ends.

## What the separate app consumes

The funnel app does not re-implement ffmpeg, Pulse, Wikipedia, or EQ. It calls the APIs we already ship:

| Need | API | Prefer host |
|---|---|---|
| What TOSLINK is emitting | `GET /api/status`, `GET /api/clock` | **Playback** |
| Transport | `POST /api/play` `{name,start}`, pause / resume / next / seek / volume / EQ | **Playback** (after the hot copy exists) |
| Fleet library | union of worker `GET /api/library` + catalog | **App** (not playback’s local scan) |
| Pull bytes for the cache | `GET` media / `POST` upload | Owner worker → playback |
| Track report + meaning essay | `POST /api/report` `{name, fetch:true}` | **Worker A** (overflow B/C) |
| Lyrics / karaoke | `GET` or `POST /api/lyrics` | **Worker C** |
| 3-band waveform + beat grid | `GET /api/wave?name=` | **Worker B** |
| EQ curve | `GET` / `POST /api/eq` | **Playback** (it is in the TOSLINK chain) |

## Data movement (no NAS, no stream)

Hard rule: no AirPlay, Spotify, DLNA, NAS, NFS, SMB, or ffmpeg HTTP input.

1. Home copy of each track lives on **exactly one worker** `/data/music`.
2. Playback receives a **copy** of now / next / last only.
3. Research workers get `{artist, title, album, year, genre}` from the app, plus optional sidecar `.lrc` bytes if we add a small upload later.
4. Caches stay **per host** and **attached to the track name**, same as V1.1.3–V1.1.7:
   - `/data/crypt/waves`
   - `/data/crypt/lyrics`
   - `/data/crypt/reports`
5. Waveform **JSON** may stay on B (or be copied to the app). Playback does not need to keep the FLAC after eviction in order to show a cached wave.

Optional later: a `CRYPT_PEERS` list so playback can fan `drop_name` itself. Not required for v1 of the funnel app.

## Speed: what three workers buy

| Work | One Quad today | Four SHC-2000s + app |
|---|---|---|
| Library size | One Quad eMMC | Up to three worker eMMCs (sharded, not mirrored) |
| Instagram reports for a **batch** of tracks | One Research at a time (~8–20 s) | Up to three reports in flight |
| Waveform analyze | One ffmpeg job | Dedicated Quad; owner already has the file |
| Wikipedia / essay HTTP | Sequential on the playback CPU | Off the TOSLINK box |
| First play of a cold track | Instant (file already local) | LAN copy, then play. Prefetch hides this for queue item +1 |
| **One** MusicBrainz lookup | ~1 req/s | Still ~1 req/s if all four share the home WAN IP |
| TOSLINK audio | One optical jack | Still one jack **on playback**. Workers do not make the DAC faster. |

MusicBrainz wants about one request per second **per public IP**. Three workers on one router do not triple that. They **do** triple Wikipedia, local tags, waveform work, and “research three different tracks at once.” They also triple **shelf space** when files are sharded.

The coordinator should own a **global MusicBrainz token bucket** (1/s) so workers do not 503 the API. Wikipedia can run in parallel. Essay (SpaceXAI) is one HTTPS call per track; put `XAI_API_KEY` only on the research worker(s) in `/data/crypt/xai.env` (never git).

## Fleet rules

- Same CRYPT build on all four (`/data/www` from this repo). Pin a release tag when the farm goes live.
- Stdlib only. No `apt`. No extra daemons beyond `crypt-web`, `crypt-pulse`, `crypt-hostname`.
- Pulse/TOSLINK **enabled** on playback. Pulse can stay installed but unused on workers (or run, but nothing listens to their optical jacks for the main room).
- Playback is the only host the listening room cares about. Workers may still bind :80 for the app and for lab debug.
- Do not merge Savant UIDs. Each chassis keeps its own `001AAE…` hostname pin.
- The funnel app is a **new** codebase (Mac or one more small service). It is not stuffed into `server.py`.
- Never point playback ffmpeg at `http://crypt-work-b/…`. Copy first.

## Phases

### 0 — Lab mule (done, then retired)

CRYPT on DualLite `.179` proved status, clock, report, lyrics, wave, upload, media GET, delete-with-cache. That chassis is **out of this project**. Do not SSH, deploy, or link it. A later SHC-2000 takes the second-host role.

### 1 — Convert three SHC-2000 workers

First Quad is up at **192.168.1.142** (`crypt-001aae0739db0000`) as the master music server, not an empty worker. Convert two more the same way (do not clone DualLite eMMC). Install Gigawatt. Give each a name and a lab IP. Confirm `GET /api/status`. No TOSLINK required on workers. Seed each worker with a **distinct** shard of test files.

### 2 — Convert the fourth as playback

Empty-ish `/data/music` (cache, not archive). TOSLINK into the room. EQ and Time Clock live here only. Confirm Playing / EQ with a file that was uploaded or copied onto this box first.

### 3 — Funnel app v1 (catalog + copy-then-play)

- Config: four base URLs.
- Build the fleet catalog from the three worker libraries.
- Play path: ensure hot copy on playback → `POST /api/play` → prefetch next.
- Evict last-minus-one when cache holds now + next + last.
- Dispatch: report → worker A (round-robin A/B/C if busy); wave → worker B (skip copy if B owns the file); lyrics → worker C.
- Timeout: report 60 s, wave 150 s (existing analyze deadline), lyrics 15 s, copy bounded by file size / LAN.
- UI: one packet per track (identity, owner, essay, caption, waveform handle, clock, `present_on_play`).
- If a worker is down, mark its rows unavailable.

### 4 — Placement and delete fan-out

New uploads → least-full worker. Deletes → owner + playback hot copy + caches on A/B/C. Optional `CRYPT_PEERS` later.

### 5 — Batch Instagram queue

Playlist or folder in → N reports out, three at a time. Persist results in the app (not on the playback host). Playback is never blocked by the queue. Research does not pull FLACs onto A.

## Success

- Room hears **only** playback TOSLINK. Workers do not glitch paplay when Research runs.
- Playback `/data/music` stays a small hot cache, not a third copy of the whole library.
- Library UI on the app shows every sharded track; a cold play copies from the owner, then TOSLINK starts.
- Queue advances without a hole: next file is on playback before `on_end`.
- Three reports in flight return faster than three serial reports on one Quad.
- Delete on the owner is followed by cache drops everywhere so no dead `/data/crypt/*` JSON.
- WAN MusicBrainz stays ≤ 1 req/s fleet-wide.
- `.40` / `.178` / `.179` / `.180` never appear in the fleet list.

## Out of scope

- Shared mounts, SMB, NFS, DLNA, AirPlay, Spotify.
- ffmpeg / Pulse streaming from one host to another.
- SSC expanders / Relays (removed in V1.1.2).
- Treating three optical jacks as one DAC.
- Mirroring the full library onto every worker.
- Running the funnel app **on** the playback host.

## Open choices (decide when hardware is on the bench)

- Exact lab IPs and hostnames for the four SHC-2000s.
- Shard rule (least-free space vs hash-mod-3 vs manual folders).
- Whether to keep a second replica of each file on another worker later (space vs a down owner).
- Whether playback itself may run Report when idle, or never.
- Whether the funnel app is a local Mac tool first, or another rack host later.

Until those four chassis exist, keep shipping Gigawatt on `.142` and treat the Picture at the top as the target architecture. The live host is documented under **Shipped so far vs the brainstorm**.
