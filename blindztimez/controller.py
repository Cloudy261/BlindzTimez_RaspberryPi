"""High-level operations shared by the CLI and the daemon.

Each public function opens its own store transaction (which also takes the radio
lock) and never nests another, so the daemon and CLI can call them freely without
deadlocking. A remote's rolling counter is advanced only after a transmit that
actually succeeds -- a blocked radio can therefore never silently desync a blind.
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime

from blindztimez import config, radio, store
from blindztimez.somfy import build_pulses
from blindztimez.store import Remote, State


class ControllerError(RuntimeError):
    """Raised for user-level failures (no such remote, list full, etc.)."""


def _record(state: State, text: str) -> None:
    """Store a short 'what happened when' string for the status view."""
    state.runtime.last_action = f"{text} {datetime.now():%H:%M}"


def _transmit(state: State, remote: Remote, button: int) -> bool:
    """Transmit one command; bump the counter and log only on success."""
    log = config.get_logger()
    pulses = build_pulses(remote.serial, remote.counter, button, state.settings.frame_repeats)
    try:
        radio.send(
            pulses,
            frequency_hz=state.settings.frequency_hz,
            tx_gpio=state.settings.tx_gpio,
            tx_power=state.settings.tx_power,
        )
    except radio.RadioError as exc:
        state.runtime.fail_count += 1
        log.error("TX FAIL %s %s: %s", remote.name, config.BUTTON_NAMES.get(button, "?"), exc)
        return False
    remote.counter = (remote.counter + 1) & config.COUNTER_MASK
    log.info(
        "TX %s %s serial=%06X cnt=%d",
        remote.name,
        config.BUTTON_NAMES.get(button, "?"),
        remote.serial,
        remote.counter,
    )
    return True


def _require(state: State, key: str) -> Remote:
    """Return the remote matching `key` or raise a user-facing error."""
    remote = store.find_remote(state, key)
    if remote is None:
        raise ControllerError(f"no remote matches {key!r}")
    return remote


# --- group commands ---------------------------------------------------------


def _send_group(state: State, button: int, daily_only: bool) -> int:
    """Send `button` to the target remotes (all, or only daily) with the stagger. Returns count."""
    sent = 0
    first = True
    for remote in state.remotes:
        if daily_only and not remote.daily:
            continue
        if not first and state.settings.stagger_ms:
            time.sleep(state.settings.stagger_ms / 1000.0)
        if _transmit(state, remote, button):
            sent += 1
        first = False
    return sent


def open_all(daily_only: bool = True) -> int:
    """Send UP now. daily_only=True (schedule/CLI) hits daily remotes; False hits every remote."""
    with store.transaction() as state:
        n = _send_group(state, config.BTN_UP, daily_only)
        _record(state, f"Open x{n}")
    return n


def close_all(daily_only: bool = True) -> int:
    """Send DOWN now. daily_only=True (schedule/CLI) hits daily remotes; False hits every remote."""
    with store.transaction() as state:
        n = _send_group(state, config.BTN_DOWN, daily_only)
        _record(state, f"Close x{n}")
    return n


# --- per-remote commands ----------------------------------------------------


def send_button(key: str, button: int) -> bool:
    """Send one button to a single remote. Returns True on a successful transmit."""
    with store.transaction() as state:
        remote = _require(state, key)
        ok = _transmit(state, remote, button)
        _record(state, f"{config.BUTTON_NAMES.get(button, '?')} {remote.name}")
    return ok


def unpair(key: str) -> bool:
    """Send PROG to toggle a remote out of the motor's memory (motor must be in prog mode)."""
    return send_button(key, config.BTN_PROG)


def set_daily(key: str, value: bool) -> None:
    """Turn a remote's daily open/close role on or off."""
    with store.transaction() as state:
        _require(state, key).daily = value


def rename(key: str, new_name: str) -> None:
    """Rename a remote."""
    new_name = new_name.strip()
    if not new_name:
        raise ControllerError("name cannot be empty")
    with store.transaction() as state:
        _require(state, key).name = new_name[:24]


def adjust_counter(key: str, delta: int | None = None, absolute: int | None = None) -> int:
    """Bump (delta) or set (absolute) a remote's rolling counter. Returns the new value."""
    with store.transaction() as state:
        remote = _require(state, key)
        if absolute is not None:
            remote.counter = absolute & config.COUNTER_MASK
        elif delta is not None:
            remote.counter = (remote.counter + delta) & config.COUNTER_MASK
        return remote.counter


def remove(key: str) -> str:
    """Remove a remote from the list. Returns its name."""
    with store.transaction() as state:
        remote = _require(state, key)
        name = remote.name
        state.remotes.remove(remote)
        return name


def add_manual(serial: int, counter: int = 1, name: str | None = None) -> Remote:
    """Add a remote with a known serial (advanced / recovery). Refuses duplicates."""
    serial &= config.SERIAL_MASK
    with store.transaction() as state:
        if len(state.remotes) >= config.MAX_REMOTES:
            raise ControllerError("remote list is full")
        if any(r.serial == serial for r in state.remotes):
            raise ControllerError(f"serial {serial:06X} already exists")
        remote = Remote(
            serial=serial,
            counter=counter & config.COUNTER_MASK,
            daily=True,
            name=(name or f"remote_{serial:06X}")[:24],
        )
        state.remotes.append(remote)
        return remote


# --- PROG pairing (create a brand-new virtual remote) -----------------------


def pair_new() -> Remote:
    """Create a fresh random remote and send ONE PROG burst to register it.

    Caller must first put the motor in programming mode (hold PROG on an existing
    remote until the blind jogs), then confirm afterwards whether the blind jogged
    again -- keep the remote on success, or call `remove()` to discard it.
    """
    with store.transaction() as state:
        if len(state.remotes) >= config.MAX_REMOTES:
            raise ControllerError("remote list is full")
        existing = {r.serial for r in state.remotes}
        serial = 0
        while serial == 0 or serial in existing:
            serial = secrets.randbits(24) & config.SERIAL_MASK
        remote = Remote(serial=serial, counter=1, daily=True, name=f"paired_{serial:06X}")
        state.remotes.append(remote)
        # One PROG burst = one rolling code = exactly one "add" toggle at the motor.
        _transmit(state, remote, config.BTN_PROG)
        _record(state, f"PROG {remote.name}")
        return remote


# --- schedule control (used by CLI and daemon) ------------------------------


def set_enabled(value: bool) -> None:
    """Enable or disable the daily schedule."""
    with store.transaction() as state:
        state.runtime.enabled = value


def mark_fired(edge: str, iso_date: str) -> None:
    """Record that today's open/close already fired, so it won't repeat."""
    with store.transaction() as state:
        if edge == "open":
            state.runtime.last_open_date = iso_date
        else:
            state.runtime.last_close_date = iso_date
