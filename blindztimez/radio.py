"""Radio transmit layer: CC1101 (OOK config over SPI) + pigpio (precise waveform).

The CC1101 provides the 433.42 MHz carrier and OOK modulation; pigpio generates
the exact microsecond pulse timing on the GDO0 data line using DMA, which is the
only reliable way to hit Somfy's ~640 us symbols on non-realtime Linux.

Hardware libraries (pigpio, cc1101) are imported lazily inside `send()` so the
rest of the app runs on a machine without a radio attached.
"""

from __future__ import annotations

import time

from blindztimez.somfy import Pulse


class RadioError(RuntimeError):
    """Raised when the radio cannot transmit (pigpiod down, SPI missing, etc.)."""


def send(
    pulses: list[Pulse],
    *,
    frequency_hz: int,
    tx_gpio: int,
    tx_power: int,
) -> None:
    """Transmit one OOK pulse list. Raises RadioError on any radio-level failure.

    Every pigpio wave is deleted before returning so repeated transmits over
    months of runtime never exhaust the limited DMA control-block pool.
    """
    try:
        import cc1101
        import pigpio
    except ImportError as exc:  # pragma: no cover - only hit off-Pi
        raise RadioError(f"radio libraries not installed: {exc}") from exc

    pi = pigpio.pi()
    if not pi.connected:
        raise RadioError("cannot reach pigpiod (try: sudo systemctl start pigpiod)")

    try:
        pi.set_mode(tx_gpio, pigpio.OUTPUT)
        pi.write(tx_gpio, 0)  # carrier off until we send
        pi.wave_clear()

        on_mask = 1 << tx_gpio
        waveform = [
            pigpio.pulse(on_mask, 0, dur) if level else pigpio.pulse(0, on_mask, dur)
            for level, dur in pulses
        ]
        pi.wave_add_generic(waveform)
        wid = pi.wave_create()
        if wid < 0:
            raise RadioError("pigpio failed to create the transmit wave")

        try:
            # cc1101 defaults to ASK/OOK; the (off, on) power tuple sets the OOK levels.
            with cc1101.CC1101(spi_bus=0, spi_chip_select=0, lock_spi_device=True) as radio:
                radio.set_base_frequency_hertz(frequency_hz)
                radio.set_output_power((0, tx_power))
                with radio.asynchronous_transmission():
                    pi.wave_send_once(wid)
                    while pi.wave_tx_busy():
                        time.sleep(0.001)
        except RadioError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any SPI/chip error uniformly
            raise RadioError(f"CC1101 transmit failed: {exc}") from exc
        finally:
            pi.wave_delete(wid)  # free this wave's DMA control blocks
            pi.write(tx_gpio, 0)
    finally:
        pi.wave_clear()
        pi.stop()  # close the pigpio socket; no handles kept between transmits
