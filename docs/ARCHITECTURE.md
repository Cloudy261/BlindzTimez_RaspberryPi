# Architecture

## Overview

```
                 ┌────────────────────────────────────────────┐
   blindz CLI ───▶                                            │
   (subcommands) │            controller.py                   │
   blindz menu ──▶  (open/close, per-remote, pairing, enable) │
                 │       │                    │               │
   systemd ──────▶ daemon.py                  │               │
   blindz daemon │  (once-per-day fire)       ▼               │
                 │                      store.transaction()   │
                 │                   flock + atomic JSON I/O   │
                 │                            │               │
                 │                            ▼               │
                 │  somfy.build_pulses ─▶ radio.send ─────────┼─▶ CC1101 (SPI) + pigpio (GDO0)
                 └────────────────────────────────────────────┘
```

Both front ends (CLI subcommands and the interactive menu) and the daemon call
the **same** `controller` functions, so behaviour is identical everywhere.

## Modules

- **`somfy.py`** — pure function `build_pulses(serial, counter, button, extra_repeats)` returning a list of `(carrier_on, duration_us)` tuples. A direct port of the Flipper's `somfy.c`; no I/O, no state. Verified to reproduce a real Flipper capture bit-for-bit.
- **`radio.py`** — `send(pulses, …)`. Configures the CC1101 for 433.42 MHz OOK over SPI (via the `cc1101` library, which defaults to ASK/OOK) and clocks the pulse train out on the GDO0 pin using **pigpio** DMA waveforms. Hardware libraries are imported lazily so everything else runs on a dev machine.
- **`store.py`** — the single JSON state file (settings + remotes + runtime), with dataclasses, atomic writes, defensive loading, and the `transaction()` lock context.
- **`schedule.py`** — pure time math: fixed/weekend/sunrise-sunset → minute-of-day. Uses the system timezone (DST-correct).
- **`controller.py`** — the shared operations. Each opens exactly one `store.transaction()` (never nested).
- **`daemon.py`** — the forever loop; one `tick()` per ~20 s.
- **`cli.py` / `menu.py`** — the two front ends.

## Concurrency and the rolling counter

The rolling counter **must** increase by exactly one per transmitted command, or
the motor rejects the frame. Two things could break that: the daemon and a manual
CLI command transmitting at the same time, or two writers clobbering the state
file.

Both are prevented by `store.transaction()`, which takes an exclusive **`flock`**
on `blindz.lock`. The lock is held across *load → transmit → increment → save*, so:

- only one process drives the radio at a time, and
- the counter read is always the latest on disk, and the write is atomic
  (`temp file → fsync → os.replace`).

The counter is advanced **only after a transmit that actually succeeded** — a
blocked radio increments a failure counter instead, so it can never silently
desync a blind.

To avoid a self-deadlock, controller functions never nest transactions; the
daemon composes them sequentially (e.g. `mark_fired("open")` then `open_all()`),
each taking and releasing the lock in turn.

## Built to run for months

- **No pigpio resource leak:** every transmit creates one DMA wave and
  **deletes it** (`wave_delete` + `wave_clear`) before returning, and opens/closes
  its pigpio connection per call. The limited DMA control-block pool never fills.
- **Bounded logs:** a `RotatingFileHandler` caps the log at ~0.75 MB total.
- **Atomic, defensive state:** a torn or corrupt file can never brick the setup —
  `store.load()` falls back to defaults field-by-field and never raises.
- **The loop allocates nothing that grows:** each `tick()` re-reads a small file
  and returns.

## Scheduling model

`daemon.tick()` is *edge-triggered with per-day dedupe*: it records the ISO date
each edge last fired and fires an edge only when `now ≥ edge_time` **and** it
hasn't fired today. This means:

- a brief outage across the exact minute still fires the event shortly after boot;
- an event never fires twice in a day;
- manual `blindz open`/`close` do **not** set the "fired today" marker, so they
  don't suppress the scheduled event.

## Inverting the carrier

In async OOK, a HIGH on GDO0 keys the carrier **on**. `somfy.build_pulses` emits
`carrier_on=True` for the "mark" half-symbols, matching the Flipper. If a
particular module/library revision keys the carrier inverted (blinds never
respond, yet SPI/pigpio report success), invert the mask in `radio.send` (swap the
two `pigpio.pulse(...)` branches). This is the first thing to try if transmits are
clean but the motor ignores them.
