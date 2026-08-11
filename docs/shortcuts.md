# Controlling the blinds from an Apple Shortcut / widget

The `blindz serve` command runs a small **token-protected, LAN-only** HTTP
endpoint. An Apple Shortcut hits it with one "Get Contents of URL" action; put
that Shortcut in a Home-Screen or Control-Center widget for one-tap open/close.

> Your phone must be on the **home WiFi** to reach the Pi. That's by design — the
> Pi has no internet access, so it isn't reachable (or attackable) from outside.
> For control while away, see *Remote access* at the bottom.

## Endpoint reference

All routes accept **GET or POST** and require the token on every request
(`Authorization: Bearer <token>` or `X-Blindz-Token: <token>`).

| Route | Does |
| --- | --- |
| `GET /status` | JSON: enabled, remotes, last action, failures |
| `/open` | UP to **all** remotes (ignores the daily flag) |
| `/close` | DOWN to **all** remotes (ignores the daily flag) |
| `/remote/<name>/<up\|down\|my\|prog>` | one button to **one** remote (selective) |

Responses are JSON, e.g. `{"action":"open","sent":3}`. No token → `401`.

`/open` and `/close` act on **every** remote — the `daily` flag only controls the
automatic morning/evening schedule, not these endpoints. To move a single blind,
use the per-remote route, e.g. `GET /remote/living_room/down`. The `<name>` is the
remote's name from `blindz remote list` (URL-encode spaces as `%20`).

## 1. On the Pi: set a token and start the service

```bash
blindz token --generate          # prints a secret; copy it for the Shortcut
sudo cp ~/BlindzTimez_RasPi/systemd/blindztimez-http.service /etc/systemd/system/
sudoedit /etc/systemd/system/blindztimez-http.service   # check User=, paths (as in INSTALL.md)
sudo systemctl daemon-reload
sudo systemctl enable --now blindztimez-http.service
systemctl status blindztimez-http.service               # active (running)
```

Find the Pi's address for the URL. A **static DHCP lease** on the FritzBox (set
earlier) keeps the IP stable — note it down (written below as `<PI-IP>`). Or use
the mDNS name `raspberrypi.local` (your Pi's hostname + `.local`), which iOS
resolves natively.

Test it from any computer on the LAN first:

```bash
curl -H "Authorization: Bearer <TOKEN>" http://<PI-IP>:8080/status
```

## 2. On the iPhone: build the Shortcut

1. Open **Shortcuts** → **+** (new shortcut) → **Add Action** → search **"Get Contents of URL"**.
2. **URL:** `http://<PI-IP>:8080/open` (or `http://raspberrypi.local:8080/open`).
3. Tap **Show More** on the action:
   - **Method:** `GET` (POST works too).
   - **Headers:** add one — key `Authorization`, value `Bearer <TOKEN>`.
4. (Optional) add a **Show Notification** action after it so a tap gives feedback.
5. Name it **"Blinds Open"** and pick an icon/colour.
6. Duplicate it, change the URL to `.../close`, name it **"Blinds Close"**.

*(Per-remote example: URL `http://<PI-IP>:8080/remote/living_room/up`.)*

## 3. Put it in a widget

- **Home Screen:** long-press the wallpaper → **+** → search **Shortcuts** → add the
  widget → tap it to choose which shortcut(s) it shows. Tapping a tile runs it.
- **Control Center (iOS 18):** Edit Control Center → **Add a Control** → **Shortcut**
  → pick "Blinds Open" / "Blinds Close".
- **Back Tap / Siri:** you can also trigger the same Shortcut by voice or a
  double/triple tap on the back of the phone (Settings → Accessibility → Touch).

## Security notes

- The token is a 128-bit secret; requests are checked in constant time and the
  server **won't start without one**. Keep the token off shared channels.
- The endpoint exposes only open/close and the four remote buttons — no pairing,
  no config, no shell.
- It listens on the LAN; the FritzBox blocks the Pi from the internet, so the
  endpoint is not reachable from outside your home.
- To rotate the token: `blindz token --generate` (prints a new one),
  `sudo systemctl restart blindztimez-http.service`, then update the Shortcut.

## Remote access (optional)

If you want to open the blinds while away, **do not** port-forward the endpoint.
Instead enable **WireGuard VPN on the FritzBox** and turn it on with a companion
Shortcut before the request — your phone joins the home LAN over the VPN and the
same `192.168.178.x` URL works, with nothing exposed to the internet.
