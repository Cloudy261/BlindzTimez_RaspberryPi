# Wiring layout: Raspberry Pi ↔ CC1101

7 connections, all **3.3 V logic**. Works the same whether you use Dupont jumper
wires or solder directly. `GDO2` is left unconnected (this build is transmit-only).

> ⚠️ **3.3 V only.** The CC1101 is **not** 5 V tolerant. Use the Pi's 3.3 V pin
> (physical pin 1), never a 5 V pin.

## Signal map (the source of truth)

| CC1101 pin (silkscreen label) | Pi pin (physical #) | Pi signal (BCM / SPI) |
| --- | --- | --- |
| **VCC** / VDD | **1** | 3V3 |
| **GND** | **6** | GND |
| **SCK** | **23** | GPIO11 · SPI0 SCLK |
| **MOSI** (may be "SI") | **19** | GPIO10 · SPI0 MOSI |
| **MISO** (may be "SO" / "GDO1") | **21** | GPIO9 · SPI0 MISO |
| **CSN** (may be "CS") | **24** | GPIO8 · SPI0 CE0 |
| **GDO0** | **18** | GPIO24 · data line |
| **GDO2** | — | not connected |

MISO must be wired even though we only transmit — the driver reads the chip's
status registers over SPI. `GDO0 → GPIO24` is the default `tx-gpio`; if you use a
different pin, set it with `blindz config set tx-gpio <BCM_number>`.

## Raspberry Pi Zero W — 40-pin header

Board viewed from above, pin **1** is the corner nearest the microSD slot.
`◄─` marks the pins this project uses.

```
   VCC  ─►  3V3     │ 1 ││ 2 │  5V
            GPIO2   │ 3 ││ 4 │  5V
            GPIO3   │ 5 ││ 6 │  GND     ◄─ GND
            GPIO4   │ 7 ││ 8 │  GPIO14
            GND     │ 9 ││10 │  GPIO15
            GPIO17  │11 ││12 │  GPIO18
            GPIO27  │13 ││14 │  GND
            GPIO22  │15 ││16 │  GPIO23
            3V3     │17 ││18 │  GPIO24  ◄─ GDO0  (data)
   MOSI ─►  GPIO10  │19 ││20 │  GND
   MISO ─►  GPIO9   │21 ││22 │  GPIO25
   SCK  ─►  GPIO11  │23 ││24 │  GPIO8   ◄─ CSN   (SPI0 CE0)
            GND     │25 ││26 │  GPIO7
                     ⋮      (pins 27–40 unused)
```

## CC1101 module (E07-M1101D, 8 pins)

Ebyte's E07-M1101D order is below. **The physical order differs between modules —
always match by the printed label, not by position.**

```
   E07-M1101D pin   label     → connect to
   ──────────────   ───────     ───────────────────────────
        1           GND       → Pi pin 6   (GND)
        2           VCC       → Pi pin 1   (3V3)
        3           GDO0      → Pi pin 18  (GPIO24, data)
        4           CSN       → Pi pin 24  (GPIO8 / CE0)
        5           SCK       → Pi pin 23  (GPIO11 / SCLK)
        6           MOSI      → Pi pin 19  (GPIO10 / MOSI)
        7           MISO      → Pi pin 21  (GPIO9  / MISO)
        8           GDO2      → (not connected)
```

## Point-to-point wire list (Dupont or solder)

```
   CC1101 VCC  ───────────── Pi pin 1   (3V3)
   CC1101 GND  ───────────── Pi pin 6   (GND)
   CC1101 GDO0 ───────────── Pi pin 18  (GPIO24)
   CC1101 MOSI ───────────── Pi pin 19  (GPIO10)
   CC1101 MISO ───────────── Pi pin 21  (GPIO9)
   CC1101 SCK  ───────────── Pi pin 23  (GPIO11)
   CC1101 CSN  ───────────── Pi pin 24  (GPIO8 / CE0)
   CC1101 GDO2                (leave open)
```

## Practical notes

- **Antenna first.** Screw on the 433 MHz antenna before transmitting; running the
  radio with no antenna can damage it and gives almost no range.
- **Keep SPI wires short** (a few cm) if you can — long, loose Dupont leads on SCK/
  MOSI/MISO can cause flaky SPI. Soldered or short jumpers are more reliable.
- **Double-check VCC vs GND** before powering on; a reversed supply can kill the
  module.
- After wiring, verify the bus is alive: `ls /dev/spidev0.*` should list
  `/dev/spidev0.0` (see [INSTALL.md](../INSTALL.md) for enabling SPI).
