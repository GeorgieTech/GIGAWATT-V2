# Savant RacePoint — Gigawatt TOSLINK

Gigawatt is the player on this chassis. Savant OS stays **off** (`savant-startup-manager` masked). RacePoint talks telnet to this host on **port 5004**.

Profile file: [`savant/georgietech_gigawatt.xml`](savant/georgietech_gigawatt.xml)

Inspector IP is **this chassis’ current LAN address** (DHCP on a shipped unit). The lab jack used in examples is **192.168.1.142**. Do not unmask Savant on the Gigawatt host.

Do **not** import `savant_sms-102a.xml` for this host. That profile is obsolete on OS 11, needs `SavantMediaQuery`, HDMI/VGA, and radio services this box does not run.

## What you import

| Field | Value |
|---|---|
| Manufacturer | GeorgieTech |
| Model | Gigawatt |
| Class | Media_server |
| Jack | **TOSLINK** (`optical_digital`) |
| Resource | `AV_EXTERNALMEDIASERVER_SOURCE` + `AV_LIVEMEDIAQUERY_SAVANTMEDIA_SOURCE` + volume |
| Control | IP telnet **5004**, CR/LF |
| Volume | 0–50 (host maps to 0–100) |

## Blueprint (you push)

1. RacePoint → Import the XML (user profile folder / drag onto the Library).
2. Place **GeorgieTech Gigawatt** in the layout.
3. Inspector: this chassis’ current IP, port `5004`. Lab example: `192.168.1.142`.
4. Draw **TOSLINK** from this component to the AVR / matrix **optical** input (media type `optical_digital` must match).
5. Generate Services for that zone. Expect a Listen / Media Player service (`SVC_AV_EXTERNALMEDIASERVER`).
6. Upload the config to your Savant system. This repo never SSHs to a Savant controller.

## Unrealized service / speakers without a stereo sink

Savant Media Audio Query (`AV_LIVEMEDIAQUERY_SAVANTMEDIA_SOURCE`) needs a complete path that **ends** on `AV_STEREOSPEAKERS_SINK`.

A subwoofer-only / powered-speakers component that does not declare that sink will fail Generate Services (path incomplete). Profile **v1.2** dropped Live Media Query so that extra service is not created. Now Playing still uses State Center on the Media Player service. **v1.3** restores Live Media Query for rooms that *do* end on stereo speakers.

If you want a Listen service that actually ends in a room:

- Do not terminate Gigawatt TOSLINK on a subwoofer-only device.
- Wire TOSLINK → AVR / amp (volume + amp) → **Stereo Speakers** (the stock component with `AV_STEREOSPEAKERS_SINK`).
- Or replace the endpoint with **Powered Speakers** that declare `AV_STEREOSPEAKERS_SINK` on an input whose media type matches (`optical_digital` or analog via a DAC). A subwoofer jack is not that sink.

## Tokens the host accepts

`Play` `Pause` `Stop` `SkipNext` `SkipPrevious` `SkipUp` `SkipDown`  
`SetVolume 25` `SendKeys Volume+` `SendKeys Volume-`  
`MuteOn` `MuteOff` `Mute` `GetStatus` `SendKeys Standby`

Replies are lines like `Volume=40` `Play=Play` `Title=…` `Artist=…`.

## Smoke test from a Mac (before Blueprint)

Lab jack:

```sh
printf 'GetStatus\r\n' | nc -w 2 192.168.1.142 5004
printf 'Pause\r\n' | nc -w 2 192.168.1.142 5004
printf 'Play\r\n' | nc -w 2 192.168.1.142 5004
```

On a shipped unit, replace `192.168.1.142` with that chassis’ current IP.

`GetStatus` must start with `OK`. Play with nothing queued starts the first library track.
