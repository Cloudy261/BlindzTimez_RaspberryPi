"""Paths, constants and shared logger. No hardware imports live here."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# --- Somfy button codes (match the Flipper's somfy.h). ---
BTN_MY = 0x1
BTN_UP = 0x2
BTN_DOWN = 0x4
BTN_PROG = 0x8

# Human names for the button codes, used in status/log output.
BUTTON_NAMES = {BTN_MY: "MY", BTN_UP: "UP", BTN_DOWN: "DOWN", BTN_PROG: "PROG"}

# Parse a button name (from CLI/menu) back to its code.
BUTTON_CODES = {v.lower(): k for k, v in BUTTON_NAMES.items()}

# Somfy 433-band frequencies (Hz). 433.42 is the usual RTS frequency.
FREQUENCIES_HZ = [433_220_000, 433_420_000, 433_920_000, 434_420_000]
DEFAULT_FREQUENCY_HZ = 433_420_000

# Somfy uses a 24-bit remote address and a 16-bit rolling counter.
SERIAL_MASK = 0xFFFFFF
COUNTER_MASK = 0xFFFF

MAX_REMOTES = 32


def state_dir() -> Path:
    """Return the directory holding state, lock and log (override via BLINDZ_STATE_DIR)."""
    env = os.environ.get("BLINDZ_STATE_DIR")
    base = Path(env) if env else Path.home() / ".config" / "blindztimez"
    return base


def state_path() -> Path:
    """Path to the single JSON state file (settings + remotes + runtime)."""
    return state_dir() / "state.json"


def lock_path() -> Path:
    """Path to the flock file that serialises radio access and counter writes."""
    return state_dir() / "blindz.lock"


def log_path() -> Path:
    """Path to the rotating log file."""
    return state_dir() / "blindz.log"


def ensure_state_dir() -> None:
    """Create the state directory if it does not exist yet."""
    state_dir().mkdir(parents=True, exist_ok=True)


_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    """Return the shared logger, configured once with a size-capped rotating file."""
    global _logger
    if _logger is not None:
        return _logger
    ensure_state_dir()
    logger = logging.getLogger("blindztimez")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # RotatingFileHandler caps total log size so it never grows without bound.
    handler = RotatingFileHandler(log_path(), maxBytes=256 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    _logger = logger
    return logger
