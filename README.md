# BlindzTimez for Raspberry Pi

A headless, command-line **Somfy RTS (433.42 MHz)** blind controller for a
**Raspberry Pi Zero W** with a cheap **CC1101** radio.

It opens all your blinds each morning and closes them each evening, at fixed
times (or at sunrise/sunset). Each blind is driven by a **virtual Somfy remote**
you create by **PROG-pairing** — so nothing desyncs and no physical remote is
cloned. A background service runs the schedule; a `blindz` command lets you
configure everything and send commands by hand.

This is a re-implementation of the [BlindzTimez Flipper Zero app](https://github.com/Cloudy261/BlindzTimez)
in Python. The Somfy protocol encoder is a direct port and produces byte-for-byte
identical RF frames (verified against a real Flipper `.sub` capture).

> **What's different from the Flipper app (by design):** there is **no** daytime
> UP/DOWN cycle / presence-simulation feature, and **no receiver** — this build
> is transmit-only. You create fresh virtual remotes via PROG pairing rather than
> cloning existing ones over the air.

## Features

- **Somfy RTS (Telis)** rolling-code protocol at **433.42 MHz** (OOK), interoperable with Flipper Somfy captures.
- **Multiple virtual remotes**, each with its own rolling counter, **saved to disk after every transmit** so it survives reboots and power loss.
- **PROG pairing**: create a brand-new independent remote and register it with the motor (no rolling-code desync). Guided "did the blind jog?" confirmation, then name it.
- **Daily schedule**: fixed morning-open / evening-close, with optional **separate weekend times** and **sunrise/sunset** timing (± offset). Uses the Pi's real clock and timezone, so **DST is automatic**.
- **Manual control**: open-all / close-all now, and per-remote **UP / DOWN / STOP (My) / PROG**, rename, counter adjust (resync), unpair.
- **Two front ends over one core**: scriptable **subcommands** (`blindz open`, `blindz config set …`) and an **interactive menu** (`blindz menu`).
- **Built to run forever**: pigpio DMA waves are freed after every transmit, state writes are atomic, logs rotate, and a file lock keeps the daemon and CLI from ever racing the rolling counter.

## Hardware

See **[INSTALL.md](INSTALL.md)** for the full parts list, wiring table and setup.
In short: a Pi Zero W + an **SPI CC1101 module** (recommended: *Ebyte E07-M1101D-SMA*
with a 433 MHz antenna, ~€4–8). The CC1101 is tuned to 433.42 MHz **in software** —
no crystal swap, unlike the fixed 433.92 MHz transmitter modules.

## Quick start

```bash
blindz remote pair          # create + register a virtual remote (repeat per blind)
blindz config set open 07:00
blindz config set close 20:00
blindz enable               # arm the daily schedule (the service does the rest)
blindz status               # see schedule, remotes and today's times
blindz open                 # open everything right now
blindz close                # close everything right now
blindz menu                 # interactive menu for everything above
```

## How the daily routine works

When the schedule is **enabled**, the background service fires two events a day:

| Time          | Event | Command                          |
| ------------- | ----- | -------------------------------- |
| **open time** (e.g. 07:00) | Morning open | **UP** to every *daily* remote |
| **close time** (e.g. 20:00) | Evening close | **DOWN** to every *daily* remote |

Each edge fires **at most once per day**. If the Pi was briefly off at the exact
minute, it still fires shortly after boot; it never double-fires.

## Command reference

| Command | What it does |
| --- | --- |
| `blindz status` | Schedule state, remote count, today's open/close times |
| `blindz open` / `blindz close` | Open / close all daily blinds now |
| `blindz enable` / `blindz disable` | Arm / disarm the daily schedule |
| `blindz menu` | Interactive numbered menu |
| `blindz remote list` | List remotes (name, role, serial, counter) |
| `blindz remote pair` | PROG-pair a brand-new virtual remote |
| `blindz remote send NAME up\|down\|my\|prog` | Send one button to a remote |
| `blindz remote daily NAME on\|off` | Include/exclude a remote from the daily open/close |
| `blindz remote rename NAME NEWNAME` | Rename |
| `blindz remote counter NAME --delta N \| --set N` | Resync the rolling counter |
| `blindz remote unpair NAME` | Send PROG to toggle a remote out of the motor |
| `blindz remote rm NAME` | Remove a remote from the list |
| `blindz remote add HEXSERIAL [--counter N] [--name X]` | Add a known serial (advanced/recovery) |
| `blindz config show` | Show all settings |
| `blindz config set KEY VALUE` | Change a setting (see below) |
| `blindz token [--generate]` | Show / create the HTTP API token |
| `blindz serve` | Run the LAN HTTP endpoint for Apple Shortcuts (see [docs/shortcuts.md](docs/shortcuts.md)) |

### Settings (`blindz config set KEY VALUE`)

| Key | Example values |
| --- | --- |
| `open` / `close` | `07:00`, `sunrise`, `sunrise+30`, `sunset-20` |
| `weekend-separate` | `on` / `off` |
| `weekend-open` / `weekend-close` | `09:30` |
| `frequency` | `433.42` (MHz) |
| `stagger` | `1000` (ms between consecutive blinds) |
| `repeats` | `2` (extra RF frame copies, 1–5) |
| `tx-gpio` | `24` (BCM pin wired to CC1101 GDO0) |
| `tx-power` | `0xC0` |
| `lat` / `lon` | `52.5`, `13.4` (for sunrise/sunset) |

## PROG pairing — important

`blindz remote pair` creates a fresh remote and registers it with the motor:

1. Hold the recessed **PROG** button on an **existing** remote until the blind **jogs**, then release.
2. Press **Enter** — the tool sends one PROG burst from the new virtual remote; the blind should jog again.
3. Confirm the jog to keep and name it; decline to discard it.

> ⚠️ **PROG is a toggle and programming mode stays open ~2 minutes.** A PROG from a
> remote the motor already knows **removes** it. So press your existing remote's
> PROG **exactly once** per attempt, and if a try fails, **wait ~2 minutes** before
> retrying — otherwise you may delete your working remote. This is the same caveat
> as on the Flipper.

## Project layout

| Path | Purpose |
| --- | --- |
| `blindztimez/somfy.py` | Somfy RTS encoder (port of the Flipper's `somfy.c`) |
| `blindztimez/cc1101` via `radio.py` | CC1101 OOK config + pigpio DMA waveform TX |
| `blindztimez/store.py` | Atomic, locked JSON state (settings + remotes + runtime) |
| `blindztimez/schedule.py` | Open/close time computation (fixed / weekend / sun) |
| `blindztimez/controller.py` | Shared operations (open/close, per-remote, pairing) |
| `blindztimez/daemon.py` | The forever-running scheduler |
| `blindztimez/cli.py` / `menu.py` | Subcommands and the interactive menu |
| `systemd/blindztimez.service` | The background service unit |
| `docs/` | Architecture and protocol notes |

See **[docs/wiring.md](docs/wiring.md)** for the full pin-map diagram,
**[docs/shortcuts.md](docs/shortcuts.md)** for the Apple Shortcut / widget setup,
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** and
**[docs/somfy-protocol.md](docs/somfy-protocol.md)** for internals, and
**[LOG.md](LOG.md)** for the development log.

## Disclaimer

For controlling your own Somfy blinds. Transmitting on 433 MHz may be regulated
in your region — use responsibly.
