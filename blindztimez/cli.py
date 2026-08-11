"""Command-line interface: scriptable subcommands plus an interactive menu.

Shared render/config helpers live here and are reused by menu.py so both front
ends behave identically.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from blindztimez import __version__, config, controller, schedule, store
from blindztimez.store import Settings, State

# --- shared render helpers --------------------------------------------------


def render_status(state: State) -> str:
    """Return a human-readable status block (schedule, remotes, today's times)."""
    daily = sum(1 for r in state.remotes if r.daily)
    lines = [
        "BlindzTimez",
        f"  Schedule : {'ENABLED' if state.runtime.enabled else 'disabled'}",
        f"  Remotes  : {len(state.remotes)} (daily: {daily})",
    ]
    try:
        open_m, close_m = schedule.effective_times(state.settings, date.today())
        we = " [weekend times]" if _is_weekend_active(state.settings) else ""
        lines.append(
            f"  Today    : open {schedule.format_hhmm(open_m)}  "
            f"close {schedule.format_hhmm(close_m)}{we}"
        )
    except ValueError as exc:
        lines.append(f"  Today    : (bad schedule: {exc})")
    lines.append(f"  Frequency: {state.settings.frequency_hz / 1e6:.2f} MHz")
    if state.runtime.last_action:
        lines.append(f"  Last     : {state.runtime.last_action}")
    if state.runtime.fail_count:
        lines.append(f"  Failures : {state.runtime.fail_count}")
    return "\n".join(lines)


def _is_weekend_active(s: Settings) -> bool:
    """True if separate weekend times apply today."""
    return s.weekend_separate and date.today().weekday() >= 5


def render_remotes(state: State) -> str:
    """Return a numbered list of remotes with role, serial and counter."""
    if not state.remotes:
        return "  (no remotes yet -- add one with 'blindz remote pair')"
    rows = []
    for i, r in enumerate(state.remotes, 1):
        role = "D" if r.daily else "-"
        rows.append(f"  {i}. {r.name:<20} [{role}] serial={r.serial:06X} cnt={r.counter}")
    return "\n".join(rows)


# --- settings application (shared by CLI and menu) --------------------------

SETTING_KEYS = (
    "open",
    "close",
    "weekend-separate",
    "weekend-open",
    "weekend-close",
    "frequency",
    "stagger",
    "repeats",
    "tx-gpio",
    "tx-power",
    "lat",
    "lon",
    "http-port",
    "http-bind",
    "http-token",
)


def _parse_bool(value: str) -> bool:
    """Parse on/off/true/false/yes/no/1/0."""
    v = value.strip().lower()
    if v in ("on", "true", "yes", "1"):
        return True
    if v in ("off", "false", "no", "0"):
        return False
    raise ValueError(f"expected on/off, got {value!r}")


def _apply_edge(spec_time: str, value: str) -> tuple[str, str, int]:
    """Parse an edge value into (source, fixed_time, offset). Keeps old time for sun fallback."""
    v = value.strip().lower()
    for base in ("sunrise", "sunset"):
        if v.startswith(base):
            rest = v[len(base) :]
            offset = int(rest) if rest else 0  # e.g. "sunrise+30", "sunset-15"
            return base, spec_time, offset
    schedule.parse_hhmm(value)  # validate HH:MM
    return "fixed", value, 0


def apply_setting(state: State, key: str, value: str) -> str:
    """Apply one setting change to `state`; return a confirmation string. Raises ValueError."""
    s = state.settings
    key = key.strip().lower()
    if key == "open":
        s.open.source, s.open.time, s.open.offset_min = _apply_edge(s.open.time, value)
        return f"open = {s.open.source} {s.open.time} {s.open.offset_min:+d}m"
    if key == "close":
        s.close.source, s.close.time, s.close.offset_min = _apply_edge(s.close.time, value)
        return f"close = {s.close.source} {s.close.time} {s.close.offset_min:+d}m"
    if key == "weekend-separate":
        s.weekend_separate = _parse_bool(value)
        return f"weekend-separate = {s.weekend_separate}"
    if key == "weekend-open":
        schedule.parse_hhmm(value)
        s.weekend_open_time = value
        return f"weekend-open = {value}"
    if key == "weekend-close":
        schedule.parse_hhmm(value)
        s.weekend_close_time = value
        return f"weekend-close = {value}"
    if key == "frequency":
        s.frequency_hz = int(round(float(value) * 1e6)) if "." in value else int(value)
        return f"frequency = {s.frequency_hz / 1e6:.2f} MHz"
    if key == "stagger":
        s.stagger_ms = max(0, int(value))
        return f"stagger = {s.stagger_ms} ms"
    if key == "repeats":
        s.frame_repeats = max(1, min(5, int(value)))
        return f"repeats = {s.frame_repeats}"
    if key == "tx-gpio":
        s.tx_gpio = int(value)
        return f"tx-gpio = BCM {s.tx_gpio}"
    if key == "tx-power":
        s.tx_power = int(value, 0) & 0xFF  # accepts 0xC0 or decimal
        return f"tx-power = 0x{s.tx_power:02X}"
    if key == "lat":
        s.latitude = float(value)
        return f"lat = {s.latitude}"
    if key == "lon":
        s.longitude = float(value)
        return f"lon = {s.longitude}"
    if key == "http-port":
        s.http_port = int(value)
        return f"http-port = {s.http_port}"
    if key == "http-bind":
        s.http_bind = value.strip()
        return f"http-bind = {s.http_bind}"
    if key == "http-token":
        s.http_token = value.strip()
        return "http-token = (set)"
    raise ValueError(f"unknown setting {key!r} (known: {', '.join(SETTING_KEYS)})")


def _edge_text(name: str, sp: store.TimeSpec) -> str:
    """One-line description of an open/close edge."""
    if sp.source == "fixed":
        return f"{name} = {sp.time}"
    return f"{name} = {sp.source} {sp.offset_min:+d}m"


def render_settings(s: Settings) -> str:
    """Return a readable dump of all settings."""
    return "\n".join(
        [
            "  " + _edge_text("open ", s.open),
            "  " + _edge_text("close", s.close),
            f"  weekend-separate = {s.weekend_separate}"
            f"  (open {s.weekend_open_time} / close {s.weekend_close_time})",
            f"  frequency = {s.frequency_hz / 1e6:.2f} MHz",
            f"  stagger = {s.stagger_ms} ms   repeats = {s.frame_repeats}",
            f"  tx-gpio = BCM {s.tx_gpio}   tx-power = 0x{s.tx_power:02X}",
            f"  lat = {s.latitude}   lon = {s.longitude}",
            f"  http = {s.http_bind}:{s.http_port}   token = {'set' if s.http_token else 'unset'}",
        ]
    )


# --- interactive pairing flow (shared by CLI and menu) ----------------------


def run_pairing() -> None:
    """Guide the user through PROG-pairing a brand-new virtual remote."""
    print(
        "\nPair a new remote:\n"
        "  1. Hold the recessed PROG button on an EXISTING remote until the blind jogs.\n"
        "  2. Release it, then press Enter here right away.\n"
        "  (PROG is a toggle and prog-mode stays open ~2 min -- do NOT press your\n"
        "   existing remote's PROG again during that window.)\n"
    )
    try:
        input("Press Enter when the blind has jogged (Ctrl-C to cancel)... ")
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return

    try:
        remote = controller.pair_new()
    except controller.ControllerError as exc:
        print(f"Pairing failed: {exc}")
        return
    print(f"Sent PROG from new remote {remote.serial:06X}.")

    answer = input("Did the blind jog again to confirm? [y/N] ").strip().lower()
    if answer != "y":
        controller.remove(f"{remote.serial:06X}")  # discard the remote that didn't take
        print("Discarded the unpaired remote. Wait ~2 min before a clean retry.")
        return

    name = input(f"Name this remote [{remote.name}]: ").strip()
    if name:
        controller.rename(remote.name, name)
    print(f"Paired and saved as '{name or remote.name}'.")


# --- subcommand handlers ----------------------------------------------------


def _cmd_status(_args: argparse.Namespace) -> int:
    print(render_status(store.load()))
    return 0


def _cmd_open(_args: argparse.Namespace) -> int:
    n = controller.open_all()
    print(f"Sent UP to {n} blind(s).")
    return 0


def _cmd_close(_args: argparse.Namespace) -> int:
    n = controller.close_all()
    print(f"Sent DOWN to {n} blind(s).")
    return 0


def _cmd_enable(_args: argparse.Namespace) -> int:
    controller.set_enabled(True)
    print("Schedule enabled.")
    return 0


def _cmd_disable(_args: argparse.Namespace) -> int:
    controller.set_enabled(False)
    print("Schedule disabled.")
    return 0


def _cmd_menu(_args: argparse.Namespace) -> int:
    from blindztimez import menu  # lazy import avoids a cli<->menu cycle at load

    menu.run()
    return 0


def _cmd_daemon(_args: argparse.Namespace) -> int:
    from blindztimez import daemon

    daemon.run()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from blindztimez import server

    s = store.load().settings
    port = args.port if args.port is not None else s.http_port
    bind = args.bind if args.bind is not None else s.http_bind
    token = args.token if args.token is not None else s.http_token
    try:
        server.serve(bind, port, token)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_token(args: argparse.Namespace) -> int:
    """Show the HTTP API token, or generate and store a fresh one."""
    if args.generate:
        import secrets

        token = secrets.token_hex(16)
        with store.transaction() as state:
            state.settings.http_token = token
        print(token)
        return 0
    token = store.load().settings.http_token
    print(token if token else "(no token set — run: blindz token --generate)")
    return 0


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"blindztimez {__version__}")
    return 0


def _cmd_remote(args: argparse.Namespace) -> int:
    """Dispatch the 'remote' subcommands."""
    action = args.remote_action
    if action == "list":
        print(render_remotes(store.load()))
        return 0
    if action == "pair":
        run_pairing()
        return 0
    if action == "add":
        serial = int(args.serial, 16)
        r = controller.add_manual(serial, args.counter, args.name)
        print(f"Added {r.name} (serial {r.serial:06X}).")
        return 0
    if action == "rm":
        print(f"Removed {controller.remove(args.remote)}.")
        return 0
    if action == "rename":
        controller.rename(args.remote, args.name)
        print(f"Renamed to {args.name}.")
        return 0
    if action == "daily":
        controller.set_daily(args.remote, _parse_bool(args.value))
        print(f"{args.remote}: daily = {args.value}")
        return 0
    if action == "send":
        code = config.BUTTON_CODES[args.button.lower()]
        ok = controller.send_button(args.remote, code)
        print("Sent." if ok else "Transmit FAILED (see log).")
        return 0 if ok else 1
    if action == "unpair":
        ok = controller.unpair(args.remote)
        print("Sent PROG (unpair toggle)." if ok else "Transmit FAILED.")
        return 0 if ok else 1
    if action == "counter":
        if args.set is not None:
            new = controller.adjust_counter(args.remote, absolute=args.set)
        else:
            new = controller.adjust_counter(args.remote, delta=args.delta)
        print(f"Counter = {new}.")
        return 0
    return 2


def _cmd_config(args: argparse.Namespace) -> int:
    """Dispatch the 'config' subcommands."""
    if args.config_action == "show":
        print(render_settings(store.load().settings))
        return 0
    # set
    with store.transaction() as state:
        msg = apply_setting(state, args.key, args.value)
    print(msg)
    return 0


# --- argument parser --------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct the full argparse tree."""
    p = argparse.ArgumentParser(
        prog="blindz", description="Somfy RTS blind controller (Pi + CC1101)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show schedule, remotes and today's times").set_defaults(
        func=_cmd_status
    )
    sub.add_parser("open", help="open (UP) all daily blinds now").set_defaults(func=_cmd_open)
    sub.add_parser("close", help="close (DOWN) all daily blinds now").set_defaults(func=_cmd_close)
    sub.add_parser("enable", help="enable the daily schedule").set_defaults(func=_cmd_enable)
    sub.add_parser("disable", help="disable the daily schedule").set_defaults(func=_cmd_disable)
    sub.add_parser("menu", help="launch the interactive menu").set_defaults(func=_cmd_menu)
    sub.add_parser("daemon", help="run the scheduler loop (used by systemd)").set_defaults(
        func=_cmd_daemon
    )
    srv = sub.add_parser("serve", help="run the LAN HTTP endpoint (Apple Shortcuts)")
    srv.add_argument("--port", type=int, default=None)
    srv.add_argument("--bind", default=None)
    srv.add_argument("--token", default=None)
    srv.set_defaults(func=_cmd_serve)
    tok = sub.add_parser("token", help="show or generate the HTTP API token")
    tok.add_argument("--generate", action="store_true", help="create and store a fresh token")
    tok.set_defaults(func=_cmd_token)
    sub.add_parser("version", help="print version").set_defaults(func=_cmd_version)

    # remote ...
    rp = sub.add_parser("remote", help="manage remotes")
    rsub = rp.add_subparsers(dest="remote_action", required=True)
    rsub.add_parser("list", help="list remotes")
    rsub.add_parser("pair", help="PROG-pair a brand-new virtual remote")
    add = rsub.add_parser("add", help="add a remote by known serial (advanced)")
    add.add_argument("serial", help="24-bit serial in hex, e.g. 1A2B3C")
    add.add_argument("--counter", type=int, default=1)
    add.add_argument("--name", default=None)
    rm = rsub.add_parser("rm", help="remove a remote")
    rm.add_argument("remote", help="name, index or hex serial")
    ren = rsub.add_parser("rename", help="rename a remote")
    ren.add_argument("remote")
    ren.add_argument("name")
    dly = rsub.add_parser("daily", help="set a remote's daily role on/off")
    dly.add_argument("remote")
    dly.add_argument("value", help="on|off")
    snd = rsub.add_parser("send", help="send one button to a remote")
    snd.add_argument("remote")
    snd.add_argument("button", choices=["up", "down", "my", "prog"])
    unp = rsub.add_parser("unpair", help="send PROG to toggle a remote out of the motor")
    unp.add_argument("remote")
    cnt = rsub.add_parser("counter", help="adjust a remote's rolling counter")
    cnt.add_argument("remote")
    grp = cnt.add_mutually_exclusive_group(required=True)
    grp.add_argument("--delta", type=int, help="add to the counter (e.g. 1, 10)")
    grp.add_argument("--set", type=int, help="set the counter to an absolute value")
    rp.set_defaults(func=_cmd_remote)

    # config ...
    cp = sub.add_parser("config", help="view or change settings")
    csub = cp.add_subparsers(dest="config_action", required=True)
    csub.add_parser("show", help="show all settings")
    cset = csub.add_parser("set", help="change one setting")
    cset.add_argument("key", help=f"one of: {', '.join(SETTING_KEYS)}")
    cset.add_argument("value")
    cp.set_defaults(func=_cmd_config)

    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (controller.ControllerError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
