"""Interactive numbered menu -- a Flipper-like front end over the same controller.

Kept intentionally dependency-free (plain input()/print()) so it works over any
SSH session on a headless Pi. All actions delegate to controller/cli helpers, so
the menu and the scriptable subcommands stay perfectly in sync.
"""

from __future__ import annotations

from blindztimez import cli, config, controller, store

BUTTONS = {"1": config.BTN_UP, "2": config.BTN_DOWN, "3": config.BTN_MY, "4": config.BTN_PROG}


def _prompt(text: str) -> str | None:
    """Read a line; return None on Ctrl-C / EOF so callers can fall back to the menu."""
    try:
        return input(text)
    except (KeyboardInterrupt, EOFError):
        print()
        return None


def _pause() -> None:
    """Wait for Enter so the user can read output before the menu redraws."""
    _prompt("\n(press Enter) ")


def _toggle_schedule() -> None:
    """Enable or disable the daily schedule depending on its current state."""
    state = store.load()
    controller.set_enabled(not state.runtime.enabled)
    print("Schedule " + ("disabled." if state.runtime.enabled else "enabled."))


def _remote_menu(name_key: str) -> None:
    """Per-remote actions (send, rename, counter, roles, unpair, remove)."""
    while True:
        state = store.load()
        remote = store.find_remote(state, name_key)
        if remote is None:
            return  # removed
        name_key = remote.name  # keep tracking it by (possibly new) name
        print(
            f"\n-- {remote.name}  serial={remote.serial:06X}  cnt={remote.counter}  "
            f"daily={'on' if remote.daily else 'off'} --"
        )
        print(
            "  1) Send UP     2) Send DOWN   3) Send MY     4) Send PROG\n"
            "  5) Toggle daily  6) Rename   7) Counter +1  8) Counter +10\n"
            "  9) Counter reset(1)  10) Unpair from motor  11) Remove   0) Back"
        )
        choice = _prompt("> ")
        if choice is None or choice == "0":
            return
        try:
            _remote_action(remote, choice)
        except controller.ControllerError as exc:
            print(f"error: {exc}")
        _pause()


def _remote_action(remote: store.Remote, choice: str) -> None:
    """Execute one per-remote menu choice."""
    if choice in BUTTONS:
        ok = controller.send_button(remote.name, BUTTONS[choice])
        print("Sent." if ok else "Transmit FAILED (see log).")
    elif choice == "5":
        controller.set_daily(remote.name, not remote.daily)
        print("Toggled daily role.")
    elif choice == "6":
        new = _prompt("New name: ")
        if new:
            controller.rename(remote.name, new)
    elif choice == "7":
        print(f"Counter = {controller.adjust_counter(remote.name, delta=1)}.")
    elif choice == "8":
        print(f"Counter = {controller.adjust_counter(remote.name, delta=10)}.")
    elif choice == "9":
        print(f"Counter = {controller.adjust_counter(remote.name, absolute=1)}.")
    elif choice == "10":
        ok = controller.unpair(remote.name)
        print("Sent PROG (unpair toggle). Test the blind." if ok else "Transmit FAILED.")
    elif choice == "11":
        controller.remove(remote.name)
        print("Removed.")


def _remotes_menu() -> None:
    """List remotes and drill into one."""
    while True:
        state = store.load()
        print("\n" + cli.render_remotes(state))
        print("  Pick a number to open it, or 0 to go back.")
        choice = _prompt("> ")
        if choice is None or choice == "0":
            return
        remote = store.find_remote(state, choice)
        if remote is None:
            print("No such remote.")
            _pause()
            continue
        _remote_menu(remote.name)


def _settings_menu() -> None:
    """Show settings and let the user edit one key at a time."""
    while True:
        print("\n" + cli.render_settings(store.load().settings))
        print("\n  Settings keys: " + ", ".join(cli.SETTING_KEYS))
        print("  Type '<key> <value>' to change one (e.g. 'open 07:00'), or blank to go back.")
        line = _prompt("> ")
        if not line:
            return
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            print("Format: <key> <value>")
            _pause()
            continue
        key, value = parts
        try:
            with store.transaction() as state:
                msg = cli.apply_setting(state, key, value)
            print(msg)
        except ValueError as exc:
            print(f"error: {exc}")
        _pause()


HELP = """\
BlindzTimez -- Somfy RTS blinds on a schedule (Raspberry Pi + CC1101).

DAILY ROUTINE
  When the schedule is ENABLED, all 'daily' remotes get UP at the open time each
  morning and DOWN at the close time each evening. The daemon fires them; this
  menu only configures things and sends manual commands.

PAIR A NEW REMOTE (recommended, no rolling-code desync)
  Hold the recessed PROG button on an existing remote until the blind jogs,
  release, then confirm here. A fresh independent virtual remote is created and
  registered with the motor.

NOTES
  Set the open/close times and (optionally) sunrise/sunset in Settings. The Pi's
  own clock/timezone is used, so DST is automatic. Keep the systemd service and
  pigpiod running for the schedule to fire.
"""


def run() -> None:
    """Run the top-level interactive menu until the user quits."""
    while True:
        state = store.load()
        sched = "ENABLED" if state.runtime.enabled else "disabled"
        print(f"\n===== BlindzTimez =====   schedule: {sched}")
        print(
            "  1) Start/Stop schedule\n"
            "  2) Status\n"
            "  3) Open all now\n"
            "  4) Close all now\n"
            "  5) Remotes\n"
            "  6) Pair new remote (PROG)\n"
            "  7) Settings\n"
            "  8) Help\n"
            "  0) Quit"
        )
        choice = _prompt("> ")
        if choice is None or choice == "0":
            print("Bye.")
            return
        try:
            _dispatch(choice)
        except controller.ControllerError as exc:
            print(f"error: {exc}")
            _pause()


def _dispatch(choice: str) -> None:
    """Handle a top-level menu choice."""
    if choice == "1":
        _toggle_schedule()
        _pause()
    elif choice == "2":
        print("\n" + cli.render_status(store.load()))
        _pause()
    elif choice == "3":
        print(f"Sent UP to {controller.open_all()} blind(s).")
        _pause()
    elif choice == "4":
        print(f"Sent DOWN to {controller.close_all()} blind(s).")
        _pause()
    elif choice == "5":
        _remotes_menu()
    elif choice == "6":
        cli.run_pairing()
        _pause()
    elif choice == "7":
        _settings_menu()
    elif choice == "8":
        print("\n" + HELP)
        _pause()
