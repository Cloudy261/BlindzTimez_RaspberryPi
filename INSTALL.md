# Installation Guide

Target: **Raspberry Pi Zero W** running a **headless Raspberry Pi OS** (Lite,
Bookworm or Bullseye). Everything below is done over SSH.

---

## 1. Hardware — what to buy

| Part | Recommendation | Approx. price |
| --- | --- | --- |
| Radio | **Ebyte E07-M1101D-SMA** CC1101 module (SPI, with an SMA connector) | €4–8 |
| Antenna | 433 MHz SMA "rubber duck" antenna | €2–4 |
| Wires | 7× female–female Dupont jumper wires | €1 |

**Why the CC1101 (and not a €1 FS1000A transmitter):** Somfy RTS uses the unusual
**433.42 MHz** frequency. The CC1101 is a *programmable* transceiver — this app
tunes it to 433.42 MHz **in software**, no soldering. The cheap FS1000A/XY-MK-5V
modules are locked to 433.92 MHz and will not reliably drive Somfy motors.

> Any generic "CC1101 433 MHz SPI module" works too (the plain 8-pin green boards).
> The E07-M1101D-SMA just has a proper antenna connector for better range. Get the
> **433 MHz** variant, **not** the 868/915 MHz one.

> ⚠️ The CC1101 is **3.3 V only** — it is **not** 5 V tolerant. Power it from the
> Pi's 3.3 V pin, never 5 V.

If your Pi Zero W has no soldered GPIO header, you'll need to solder one (or use a
hammer-header / a header-less "WH" variant).

---

## 2. Wiring (CC1101 → Raspberry Pi 40-pin header)

All connections are 3.3 V logic. `GDO2` is left unconnected (transmit-only).

| CC1101 pin | Raspberry Pi pin (physical) | Pi signal (BCM) |
| --- | --- | --- |
| VCC / VDD | Pin **1** | 3.3 V |
| GND | Pin **6** | GND |
| SCK  | Pin **23** | SCLK (GPIO11) |
| MOSI (SI) | Pin **19** | MOSI (GPIO10) |
| MISO (SO) | Pin **21** | MISO (GPIO9) |
| CSN | Pin **24** | CE0 (GPIO8) |
| GDO0 | Pin **18** | GPIO24 ← the data line |
| GDO2 | — | not connected |

`GDO0 → GPIO24` is the default `tx-gpio`. If you wire GDO0 to a different pin,
set it with `blindz config set tx-gpio <BCM_number>`.

MISO must be connected even though we only transmit — the driver reads the chip's
status registers over SPI.

> 📌 For a full pin-map diagram of both boards (usable for Dupont wires or
> soldering), see **[docs/wiring.md](docs/wiring.md)**.

---

## 3. Enable SPI and install system packages

```bash
sudo raspi-config nonint do_spi 0          # enable the SPI bus
sudo apt update
sudo apt install -y pigpio python3-pigpio python3-spidev python3-venv git
sudo systemctl enable --now pigpiod        # precise-timing daemon, start at boot
sudo usermod -aG spi,gpio "$USER"          # SPI + GPIO access without root
sudo reboot                                # SPI + group changes need a reboot
```

After the reboot, confirm the SPI device and pigpio are present:

```bash
ls /dev/spidev0.*          # expect /dev/spidev0.0
systemctl is-active pigpiod # expect: active
```

---

## 4. Install BlindzTimez

Copy this project to the Pi (e.g. `git clone …` or `scp -r`) so it lives at, say,
`/home/pi/BlindzTimez_RasPi`. Then install it into a virtualenv:

```bash
python3 -m venv --system-site-packages ~/blindz-venv
~/blindz-venv/bin/pip install /home/pi/BlindzTimez_RasPi
```

`--system-site-packages` lets the venv reuse the apt-installed `python3-spidev`
and `python3-pigpio`, so nothing has to be compiled. Test it:

```bash
~/blindz-venv/bin/blindz version
~/blindz-venv/bin/blindz status
```

> Tip: add `export PATH="$HOME/blindz-venv/bin:$PATH"` to `~/.bashrc` so you can
> just type `blindz`.

---

## 5. Pair your blinds and set the schedule

Do this once per blind. **Stand near the blind** with its existing remote:

```bash
blindz remote pair
```

Follow the prompts (hold PROG on the existing remote until the blind jogs → Enter
→ confirm the jog → name it). Then configure and arm:

```bash
blindz config set open 07:00
blindz config set close 20:00
# optional: blindz config set close sunset-20   (needs lat/lon)
# optional: blindz config set weekend-separate on ; blindz config set weekend-open 09:30
blindz enable
blindz status
```

---

## 6. Run the schedule as a background service

The schedule only fires while the daemon runs. Install the systemd unit:

```bash
sudo cp /home/pi/BlindzTimez_RasPi/systemd/blindztimez.service /etc/systemd/system/
sudoedit /etc/systemd/system/blindztimez.service   # check User=, BLINDZ_STATE_DIR, ExecStart path
sudo systemctl daemon-reload
sudo systemctl enable --now blindztimez.service
systemctl status blindztimez.service
```

Edit the unit so that:
- `User=` is your login user (default `pi`),
- `BLINDZ_STATE_DIR=` points at that user's `~/.config/blindztimez`,
- `ExecStart=` is the full path to `blindz` inside your venv (default
  `/home/pi/blindz-venv/bin/blindz daemon`).

`BLINDZ_STATE_DIR` **must match** for the daemon and your CLI, otherwise they use
different state files. The default (`~/.config/blindztimez`) already matches when
you run the CLI as the same user.

---

## 7. Verify and watch logs

```bash
blindz open                 # blinds should move now
journalctl -u blindztimez -f
tail -f ~/.config/blindztimez/blindz.log
```

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `cannot reach pigpiod` | `sudo systemctl enable --now pigpiod` |
| `radio libraries not installed` | Reinstall in the venv: `~/blindz-venv/bin/pip install /home/pi/BlindzTimez_RasPi` |
| `PermissionError` on `/dev/spidev0.0` | Ensure you're in the `spi` group (`groups`), then re-login/reboot |
| Blinds don't respond, no errors | Check the antenna, move closer, try `blindz config set tx-power 0xC0`; confirm the remote is actually paired (`blindz remote send NAME up`) |
| Blinds still don't respond | If your setup keys OOK inverted, that's the usual culprit — see `docs/ARCHITECTURE.md` ("inverting the carrier") |
| Wrong times fire | Check the Pi's timezone: `timedatectl` (set with `sudo timedatectl set-timezone …`) |
| A physical remote stopped working after pairing | You likely pressed its PROG twice inside prog-mode (a toggle) — re-add it via another working remote |
