# Somfy RTS (Telis) protocol notes

This documents what `blindztimez/somfy.py` implements. It matches the Flipper
Somfy Telis implementation, so frames are interoperable.

## Frame layout (7 bytes, plaintext)

| Byte | Contents |
| --- | --- |
| 0 | `0xA7` — "encryption key" nibble (standard fresh-remote value) |
| 1 | high nibble = button code; low nibble = checksum |
| 2 | rolling counter, high byte |
| 3 | rolling counter, low byte |
| 4 | remote serial, byte 2 (bits 23..16) |
| 5 | remote serial, byte 1 (bits 15..8) |
| 6 | remote serial, byte 0 (bits 7..0) |

Button codes: `MY/Stop = 0x1`, `UP = 0x2`, `DOWN = 0x4`, `PROG = 0x8`.

### Checksum

4-bit XOR over every nibble of the 7 plaintext bytes (with the checksum nibble
itself taken as 0), stored in the low nibble of byte 1:

```
checksum = 0
for b in frame:        # frame[1] low nibble is still 0 here
    checksum ^= b ^ (b >> 4)
frame[1] |= checksum & 0xF
```

### Obfuscation

Each byte (from byte 1) is XORed with the previous **obfuscated** byte:

```
for i in 1..6:
    frame[i] ^= frame[i-1]
```

The 56-bit result, packed MSB-first, is what goes on the air. (De-obfuscation is
`p = o ^ (o >> 8)`.)

## On-air encoding (OOK)

Base symbol time `TE = 640 µs`. One transmission is:

1. **Wake-up:** carrier ON 9415 µs, OFF 89565 µs.
2. **First frame** with **2** hardware-sync pulses.
3. `extra_repeats` **repeat frames**, each with **7** hardware-sync pulses.

Each frame:

- **Hardware sync:** N × (ON `4·TE`, OFF `4·TE`).
- **Software sync:** ON 4550 µs, OFF `TE`.
- **Data:** 56 Manchester bits, MSB first — `1` = (OFF `TE`, ON `TE`), `0` = (ON `TE`, OFF `TE`).
- **Inter-frame gap:** OFF 30415 µs.

Adjacent segments of the same level are merged, so e.g. a data `1` followed by a
`1` becomes a single longer segment — exactly the shape the Flipper emits.

## Rolling counter

The 16-bit counter increments by one on every command. The motor accepts a frame
whose counter is ahead of its last-seen value (within a window) and then stores
it, so counters must be **strictly monotonic** per remote. If a remote gets out of
sync (e.g. you transmitted while the motor was out of range), press UP/DOWN a few
times, or bump it: `blindz remote counter NAME --delta 10`.

## PROG pairing (creating a new remote)

To add a **new** remote, the motor is put into programming mode and then receives
one PROG frame from the new remote's address:

1. Hold PROG on an **already-paired** remote until the blind jogs → the motor
   enters programming mode (~2 minutes).
2. The new (virtual) remote sends **one** PROG burst from its fresh random 24-bit
   serial. The motor learns it and the blind jogs again.

**PROG is a toggle**: a PROG from an address the motor already knows *removes* it.
That's why the new remote must send PROG exactly once (one RF burst = one rolling
code = one toggle), and why you must not press an existing remote's PROG again
while programming mode is open — see the warnings in the README.

`blindz remote unpair NAME` simply sends PROG from a known remote to toggle it out
of the motor's memory (motor must be in programming mode first).
