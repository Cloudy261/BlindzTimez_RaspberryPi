"""Somfy RTS (Telis) encoder.

Direct port of the Flipper app's `somfy_build_upload` (somfy.c). Produces the OOK
pulse train for one transmission as a list of (carrier_on, duration_us) tuples,
already merged so adjacent same-level segments are combined -- exactly the shape
the Flipper emits, so transmissions are interoperable with genuine Somfy captures.
"""

from __future__ import annotations

TE_SHORT = 640  # base symbol time in microseconds
Pulse = tuple[bool, int]  # (carrier_on, duration_us)


def _build_frame(serial: int, counter: int, button: int) -> int:
    """Build the 56-bit obfuscated Somfy frame from serial/counter/button."""
    frame = bytearray(7)
    frame[0] = 0xA7  # "encryption key" nibble; standard fresh-remote value
    frame[1] = (button & 0xF) << 4
    frame[2] = (counter >> 8) & 0xFF
    frame[3] = counter & 0xFF
    frame[4] = (serial >> 16) & 0xFF
    frame[5] = (serial >> 8) & 0xFF
    frame[6] = serial & 0xFF

    # 4-bit checksum over all nibbles, stored in the low nibble of frame[1].
    checksum = 0
    for b in frame:
        checksum ^= b ^ (b >> 4)
    frame[1] |= checksum & 0xF

    # Obfuscate in place: O[i] = P[i] ^ O[i-1].
    for i in range(1, 7):
        frame[i] ^= frame[i - 1]

    # Pack MSB-first into a 56-bit integer.
    data = 0
    for b in frame:
        data = (data << 8) | b
    return data


def build_pulses(serial: int, counter: int, button: int, extra_repeats: int) -> list[Pulse]:
    """Return the full OOK pulse list for one command (wake-up + 1 + extra_repeats frames)."""
    data = _build_frame(serial, counter, button)
    pulses: list[Pulse] = []

    def emit(level: bool, dur: int) -> None:
        """Append a pulse, merging with the previous one if it has the same level."""
        if pulses and pulses[-1][0] == level:
            pulses[-1] = (level, pulses[-1][1] + dur)
        else:
            pulses.append((level, dur))

    # Wake-up pulse.
    emit(True, 9415)
    emit(False, 89565)

    frames = 1 + max(0, extra_repeats)
    for f in range(frames):
        # Hardware sync: 2 pulses on the first frame, 7 on the repeats.
        hw_sync = 2 if f == 0 else 7
        for _ in range(hw_sync):
            emit(True, TE_SHORT * 4)
            emit(False, TE_SHORT * 4)
        # Software sync.
        emit(True, 4550)
        emit(False, TE_SHORT)
        # Manchester data, MSB first: bit=1 -> low,high ; bit=0 -> high,low.
        for pos in range(55, -1, -1):
            if (data >> pos) & 1:
                emit(False, TE_SHORT)
                emit(True, TE_SHORT)
            else:
                emit(True, TE_SHORT)
                emit(False, TE_SHORT)
        # Inter-frame gap (merges with the trailing low above).
        emit(False, 30415)

    return pulses
