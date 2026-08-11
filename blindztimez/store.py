"""Persistent state: settings + remotes + daemon runtime.

Everything lives in one JSON file, written atomically. A file lock (flock)
serialises every mutation so the daemon and the CLI can never transmit at the
same time or race the per-remote rolling counter.

Defensive by design: loading a missing, partial or corrupt file falls back to
defaults field-by-field instead of raising, so a bad write can never brick a
setup that must run for months unattended.
"""

from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from blindztimez import config

STATE_VERSION = 1


@dataclass
class TimeSpec:
    """One schedule edge (open or close): fixed clock time, or sunrise/sunset + offset."""

    source: str = "fixed"  # "fixed" | "sunrise" | "sunset"
    time: str = "07:00"  # HH:MM, used when source == "fixed"
    offset_min: int = 0  # minutes added to sun time, used when source != "fixed"


@dataclass
class Settings:
    """User-configurable settings (persisted)."""

    frequency_hz: int = config.DEFAULT_FREQUENCY_HZ
    tx_gpio: int = 24  # BCM pin wired to the CC1101 GDO0 data line
    tx_power: int = 0xC0  # CC1101 PATABLE "on" level for OOK
    frame_repeats: int = 2  # extra copies of each RF frame per command
    stagger_ms: int = 1000  # delay between commands to consecutive blinds
    weekend_separate: bool = False
    open: TimeSpec = field(default_factory=lambda: TimeSpec("fixed", "07:00", 0))
    close: TimeSpec = field(default_factory=lambda: TimeSpec("fixed", "20:00", 0))
    weekend_open_time: str = "09:00"  # used when weekend_separate and open source is fixed
    weekend_close_time: str = "20:00"
    latitude: float = 52.0
    longitude: float = 13.0
    http_port: int = 8080  # LAN HTTP endpoint for Apple Shortcuts (blindz serve)
    http_bind: str = "0.0.0.0"  # interfaces to listen on; LAN-only in practice
    http_token: str = ""  # shared secret required on every HTTP request


@dataclass
class Remote:
    """One virtual Somfy remote with its own rolling counter."""

    serial: int
    counter: int = 1
    daily: bool = True  # opened in the morning / closed in the evening on schedule
    name: str = ""


@dataclass
class Runtime:
    """Daemon runtime state (persisted so restarts don't double-fire)."""

    enabled: bool = False  # whether the schedule is active
    last_open_date: str | None = None  # ISO date the morning open last fired
    last_close_date: str | None = None
    last_action: str = ""
    fail_count: int = 0


@dataclass
class State:
    """The whole persisted document."""

    settings: Settings = field(default_factory=Settings)
    remotes: list[Remote] = field(default_factory=list)
    runtime: Runtime = field(default_factory=Runtime)


def _get(d: Any, key: str, default: Any) -> Any:
    """Fetch d[key] with a type-matched fallback; tolerate non-dicts and bad types."""
    if not isinstance(d, dict):
        return default
    val = d.get(key, default)
    # Guard against a wrong JSON type silently poisoning a field.
    if default is not None and not isinstance(val, type(default)):
        # bool is a subclass of int, so allow int where a number is expected.
        if isinstance(default, (int, float)) and isinstance(val, (int, float)):
            return val
        return default
    return val


def _timespec_from(d: Any, fallback: TimeSpec) -> TimeSpec:
    """Build a TimeSpec defensively from a JSON fragment."""
    src = _get(d, "source", fallback.source)
    if src not in ("fixed", "sunrise", "sunset"):
        src = fallback.source
    return TimeSpec(
        source=src,
        time=_get(d, "time", fallback.time),
        offset_min=int(_get(d, "offset_min", fallback.offset_min)),
    )


def _settings_from(d: Any) -> Settings:
    """Build Settings defensively from a JSON fragment, filling gaps with defaults."""
    s = Settings()
    s.frequency_hz = int(_get(d, "frequency_hz", s.frequency_hz))
    s.tx_gpio = int(_get(d, "tx_gpio", s.tx_gpio))
    s.tx_power = int(_get(d, "tx_power", s.tx_power))
    s.frame_repeats = max(1, min(5, int(_get(d, "frame_repeats", s.frame_repeats))))
    s.stagger_ms = max(0, int(_get(d, "stagger_ms", s.stagger_ms)))
    s.weekend_separate = bool(_get(d, "weekend_separate", s.weekend_separate))
    s.open = _timespec_from(_get(d, "open", {}), s.open)
    s.close = _timespec_from(_get(d, "close", {}), s.close)
    s.weekend_open_time = _get(d, "weekend_open_time", s.weekend_open_time)
    s.weekend_close_time = _get(d, "weekend_close_time", s.weekend_close_time)
    s.latitude = float(_get(d, "latitude", s.latitude))
    s.longitude = float(_get(d, "longitude", s.longitude))
    s.http_port = int(_get(d, "http_port", s.http_port))
    s.http_bind = str(_get(d, "http_bind", s.http_bind))
    s.http_token = str(_get(d, "http_token", s.http_token))
    return s


def _remotes_from(items: Any) -> list[Remote]:
    """Build the remote list defensively, dropping any entry without a valid serial."""
    out: list[Remote] = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict) or "serial" not in it:
            continue
        try:
            serial = int(it["serial"]) & config.SERIAL_MASK
        except (TypeError, ValueError):
            continue
        out.append(
            Remote(
                serial=serial,
                counter=int(_get(it, "counter", 1)) & config.COUNTER_MASK,
                daily=bool(_get(it, "daily", True)),
                name=str(_get(it, "name", "")) or f"remote_{serial:06X}",
            )
        )
        if len(out) >= config.MAX_REMOTES:
            break
    return out


def _runtime_from(d: Any) -> Runtime:
    """Build Runtime defensively from a JSON fragment."""
    r = Runtime()
    r.enabled = bool(_get(d, "enabled", r.enabled))
    r.last_open_date = _get(d, "last_open_date", None) or None
    r.last_close_date = _get(d, "last_close_date", None) or None
    r.last_action = str(_get(d, "last_action", ""))
    r.fail_count = max(0, int(_get(d, "fail_count", 0)))
    return r


def load() -> State:
    """Load state from disk, returning defaults if it is missing or unreadable.

    Safe to call without the lock: atomic writes mean a concurrent read always
    sees either the old or the new complete file, never a half-written one.
    """
    path = config.state_path()
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return State()
    return State(
        settings=_settings_from(_get(raw, "settings", {})),
        remotes=_remotes_from(_get(raw, "remotes", [])),
        runtime=_runtime_from(_get(raw, "runtime", {})),
    )


def save(state: State) -> None:
    """Write state atomically: temp file + fsync + os.replace, so it is never torn."""
    config.ensure_state_dir()
    path = config.state_path()
    doc = {
        "version": STATE_VERSION,
        "settings": dataclasses.asdict(state.settings),
        "remotes": [dataclasses.asdict(r) for r in state.remotes],
        "runtime": dataclasses.asdict(state.runtime),
    }
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)  # atomic on POSIX


@contextlib.contextmanager
def transaction() -> Iterator[State]:
    """Hold the exclusive lock, load fresh state, yield it, then save on exit.

    Radio transmission happens inside this block so the lock also serialises the
    radio. State is saved in `finally` so counter increments already applied are
    persisted even if a later transmit in the same batch raises.
    """
    config.ensure_state_dir()
    with open(config.lock_path(), "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            state = load()
            try:
                yield state
            finally:
                save(state)  # persist even on error so applied counter bumps survive
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def find_remote(state: State, key: str) -> Remote | None:
    """Look up a remote by name (case-insensitive), 1-based index, or hex serial."""
    key = key.strip()
    for r in state.remotes:
        if r.name.lower() == key.lower():
            return r
    if key.isdigit():
        idx = int(key) - 1
        if 0 <= idx < len(state.remotes):
            return state.remotes[idx]
    with contextlib.suppress(ValueError):
        serial = int(key, 16) & config.SERIAL_MASK
        for r in state.remotes:
            if r.serial == serial:
                return r
    return None
