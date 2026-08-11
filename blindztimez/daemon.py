"""The forever-running scheduler.

Every tick it re-reads state, computes today's open/close minute-of-day, and
fires each edge at most once per day (tracked by date). If the daemon was down
at the exact minute, it still fires shortly after start -- but never re-fires an
edge already done today. It transmits only when the schedule is enabled.

Design notes for unattended runtime: the loop allocates nothing that grows, reads
state lock-free each tick, and delegates all radio work (and locking) to the
controller, which frees its pigpio waves after every transmit.
"""

from __future__ import annotations

import time
from datetime import date, datetime

from blindztimez import config, controller, schedule, store

TICK_SECONDS = 20  # how often to check the schedule


def _due(last_iso: str | None, today: date, now_minute: int, edge_minute: int) -> bool:
    """True if this edge is enabled for today and hasn't fired yet."""
    return last_iso != today.isoformat() and now_minute >= edge_minute


def tick(now: datetime | None = None) -> None:
    """Run one schedule check. Separated from the loop so it is easy to test."""
    now = now or datetime.now()
    state = store.load()  # lock-free read; a transaction is taken only if we transmit
    if not state.runtime.enabled or not state.remotes:
        return

    today = now.date()
    now_minute = now.hour * 60 + now.minute
    try:
        open_m, close_m = schedule.effective_times(state.settings, today)
    except ValueError as exc:
        config.get_logger().error("bad schedule config: %s", exc)
        return

    # Mark the edge fired first, then transmit: a transient radio failure must not
    # cause the same edge to retry on every tick for the rest of the day.
    if _due(state.runtime.last_open_date, today, now_minute, open_m):
        controller.mark_fired("open", today.isoformat())
        n = controller.open_all()
        config.get_logger().info("scheduled OPEN fired: %d blind(s)", n)
    elif _due(state.runtime.last_close_date, today, now_minute, close_m):
        controller.mark_fired("close", today.isoformat())
        n = controller.close_all()
        config.get_logger().info("scheduled CLOSE fired: %d blind(s)", n)


def run() -> None:
    """Run the scheduler loop forever (invoked by the systemd service)."""
    log = config.get_logger()
    log.info("daemon started (tick=%ds)", TICK_SECONDS)
    while True:
        try:
            tick()
        except Exception as exc:  # noqa: BLE001 - never let one bad tick kill the daemon
            log.exception("tick error: %s", exc)
        time.sleep(TICK_SECONDS)
