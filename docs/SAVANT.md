# Savant RacePoint — Gigawatt TOSLINK

Gigawatt stays the player on **192.168.1.142**. Savant OS stays **off** this chassis (`savant-startup-manager` masked). RacePoint talks telnet to this host on **port 5004**.

Profile file: [`savant/georgietech_gigawatt.xml`](savant/georgietech_gigawatt.xml)

A copy for Blueprint import also lives at:

`/Users/georgecarrillo/Documents/AI Apps/Savant/georgietech_gigawatt.xml`

Do **not** import `savant_sms-102a.xml` for this host. That profile is obsolete on OS 11, needs `SavantMediaQuery`, HDMI/VGA, and radio services this box does not run.

Do **not** point Inspector at 192.168.1.40. Do not unmask Savant on 142.

## What you import

| Field | Value |
|---|---|
| Manufacturer | GeorgieTech |
| Model | Gigawatt |
| Class | Media_server |
| Jack | **TOSLINK** (`optical_digital`) |
| Resource | `AV_EXTERNALMEDIASERVER_SOURCE` + volume |
| Control | IP telnet **5004**, CR/LF |
| Volume | 0–50 (host maps to 0–100) |

## Blueprint (you push)

1. RacePoint → Import the XML (user profile folder / drag onto the Library).
2. Place **GeorgieTech Gigawatt** in the layout.
3. Inspector: IP `192.168.1.142`, port `5004`.
4. Draw **TOSLINK** from this component to the AVR / matrix optical input (media type `optical_digital` must match).
5. Generate Services for that zone. Expect a Listen / Media Player service (`SVC_AV_EXTERNALMEDIASERVER`).
6. Upload the config to Carrillos Resident yourself. This repo never SSHs to `.40`.

## Tokens the host accepts

`Play` `Pause` `Stop` `SkipNext` `SkipPrevious` `SkipUp` `SkipDown`  
`SetVolume 25` `SendKeys Volume+` `SendKeys Volume-`  
`MuteOn` `MuteOff` `Mute` `GetStatus` `SendKeys Standby`

Replies are lines like `Volume=40` `Play=Play` `Title=…` `Artist=…`.

## Smoke test from a Mac (before Blueprint)

```sh
printf 'GetStatus\r\n' | nc -w 2 192.168.1.142 5004
printf 'Pause\r\n' | nc -w 2 192.168.1.142 5004
printf 'Play\r\n' | nc -w 2 192.168.1.142 5004
```

`GetStatus` must start with `OK`. Play with nothing queued starts the first library track.
