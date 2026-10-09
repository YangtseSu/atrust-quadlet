<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# atrust-quadlet

[![publish](https://github.com/YangtseSu/atrust-quadlet/actions/workflows/publish.yml/badge.svg)](https://github.com/YangtseSu/atrust-quadlet/actions/workflows/publish.yml)

Run the Sangfor aTrust client in a podman container with supervised auto-login, for headless
hosts (routers, workstations, CI boxes): you get the VPN tunnel plus the SOCKS5/HTTP proxies the
base image provides, and you do **not** have to pass portal cookies around as parameters.

*Not affiliated with, or endorsed by, Sangfor. The aTrust client itself is not part of this
project: it comes from the base image [`hagb/docker-atrust`](https://github.com/Hagb/docker-easyconnect).*

## What it does

| Requirement | How it is implemented |
|---|---|
| Login without leaving cookies to the user | `atrustd` performs the portal login itself and writes `tid`/`tid.sig` into the **client's own** profile (`/root/.aTrust/AppCache/Cookies`, plain SQLite), so the tokens persist on the mounted volume and the client side stops asking for the captcha |
| No cookie parameters | There is no `--cookie_*` option. The tokens are read from the client profile (`ATRUST_CLIENT_COOKIE_DB`) and refreshed by the engine |
| The client's own window logs in | `atrustd.uiauto` fills in the client's login window (portal address, account, password, agreement) with X level input (`xdotool`) and submits it - the client accepts no session that was obtained elsewhere |
| Captcha / first login needs a human | the supervisor writes a `NEED_VNC` hint (plus the captcha image) and waits; open VNC, finish the login in the desktop, and supervision continues automatically |
| Login state is watched, re-login is automatic | data-plane probes (`utun7` + routes + an intranet target through the HTTP proxy) drive a small state machine (`ONLINE`/`DEGRADED`/`LOGGED_OUT`/`NEED_VNC`) with exponential backoff |
| The apps behind the tunnel are visible | every login publishes what the portal grants this account (name, launch URL, launch method, server address) to the log and to `apps.json` in `ATRUST_STATE_DIR`; `atrustd --apps` prints it |
| podman, not docker | everything is podman; the client, Xvfb, VNC and the proxies come from the base image, which already carries the rootless-podman plumbing |
| Quadlet | `quadlet/atrust.container` + `quadlet/atrust.env.example`; portal URL, user and password live in the env file referenced by the unit |

## How the login works (protocol, no browser)

The aTrust web portal is a plain HTTPS API; the bundled SPA does the crypto in JavaScript. Verified
against a live portal:

```
GET  /passport/v1/public/authConfig?clientType=SDPBrowserClient&platform=Linux&lang=<lang>&needTicket=1
       -> data.pubKey (hex RSA modulus), data.pubKeyExp, data.antiReplayRand,
          data.defaultDomain, data.security.csrfToken
POST /passport/v1/auth/psw?<same query>
       body {"username":"<user>@<domain>","password":"<hex>","rememberPwd":"0"}
       password = RSA(pubKey, pubKeyExp) over "<password>_<antiReplayRand>"
       required headers: x-sdp-rid = base64(host:port), x-csrf-token = data.security.csrfToken
       -> data.ticket, data.nextService = auth/authCheck
GET  /passport/v1/auth/authCheck?<same query>    -> data.onlineInfo.isOnline, session cookies
GET  /passport/v1/user/onlineInfo?<same query>   -> code 75500002 "会话无效" once the session is gone
GET  /passport/v1/public/checkCode?<...>&rnd=<ms> -> the graphical captcha image
```

`atrustd` implements this with the Python standard library only (urllib + sqlite3 + a small RSA
PKCS#1 v1.5 implementation): the base image has no python3 and we deliberately avoid pip,
`requests` and `cryptography`.

## How the client logs in (its own window, no OCR)

The web login above never brings the tunnel up by itself (the client refuses sessions obtained
elsewhere, see `docs/STATUS.md`); it exists to refresh `tid`/`tid.sig`, which is what keeps the
*client's* login captcha free. The tunnel comes up when the client's own window logs in, so
`atrustd.uiauto` does what a human in the VNC session would do:

```
portal address (first run) -> account -> password -> agreement -> submit
```

* the window is found by name and pinned to the size the layout was measured at (the client's UI
  re-lays out on resize, so a user changed VNC geometry is harmless),
* the page is recognised from its *input fields* (outlined box, white inside) - no labels are read,
  and it works while the form is still empty and the submit button is greyed out,
* the agreement box is ticked only when its pixels are not already filled,
* the submit button is located by its fill colour, which also survives the error and captcha rows
  the client inserts between the password field and the button,
* the result is never guessed from the screen: the supervisor decides with the data plane (routes
  on `utun7`),
* a window that is not showing the password form (captcha, QR code, another auth method) is reported
  as such and the session is handed over to VNC.

The portal address is written to the client's own config (`ATRUST_CLIENT_ADDR_CONF`) before the
client starts, so a freshly created container opens on the login page instead of "Connection
Options"; typing it into the window remains as the fallback.

## Quick start

```bash
podman pull ghcr.io/yangtsesu/atrust-quadlet:latest
install -d ~/.config/containers/systemd
install -d ~/.atrust-data          # must exist; mounted into the container at /root
cp quadlet/atrust.container ~/.config/containers/systemd/
install -m600 quadlet/atrust.env.example ~/.config/atrust.env   # edit it first
systemctl --user daemon-reload
systemctl --user start atrust.service
journalctl --user -u atrust.service -f
```

The image is public and built from this repository by GitHub Actions for `linux/amd64` and
`linux/arm64` (`:main` and `:<git sha>` are published too; a `v*` tag publishes the version tags,
e.g. `:1.0.0` and `:1.0`, and moves `:latest` to the release). To build it yourself instead:
`podman build -t ghcr.io/yangtsesu/atrust-quadlet:latest .`

Container state lives in `~/.atrust-data` (mounted at `/root`), i.e. the client's own profile and
the `atrustd` state file, so a restart normally needs no login at all: the client resumes its
session.

## Configuration

All configuration is environment-only (Quadlet `Environment=` / `EnvironmentFile=`):

| Variable | Default | Meaning |
|---|---|---|
| `ATRUST_PORTAL_URL` | – (required) | portal, e.g. `https://vpn.example.com/` |
| `ATRUST_USERNAME` | – (required) | account name (the `@<domain>` suffix is added automatically) |
| `ATRUST_PASSWORD` / `ATRUST_PASSWORD_FILE` | – (required) | password, or a file containing it |
| `ATRUST_PROBE_TARGET` | empty | comma separated `host:port` inside the VPN used to prove the tunnel carries traffic |
| `ATRUST_WATCH_INTERVAL` | `90` | seconds between supervision cycles |
| `ATRUST_VNC_WAIT` | `900` | how long to wait for a human in VNC before retrying |
| `ATRUST_STATE_DIR` | `/run/atrustd` | where `state.json`, `NEED_VNC` and the captcha image are written |
| `ATRUST_CLIENT_COOKIE_DB` | `/root/.aTrust/AppCache/Cookies` | the client's own cookie store |
| `ATRUST_CLIENT_ADDR_CONF` | `/usr/share/sangfor/.aTrust/var/conf/addr.conf` | the client's own portal address (seeded before it starts) |
| `ATRUST_CLIENT_LOG_DIR` | `/root/.aTrust/logs` | the client's log, read to tell a captcha request from a failed login |
| `ATRUST_DISPLAY` | `:1` | X display of the client's window (the base image uses `:1`) |
| `ATRUST_PROXY` | `127.0.0.1:8888` | HTTP proxy used by the data-plane probe |
| `ATRUST_TUN` | `utun7` | tunnel interface created by the client |
| `ATRUST_DEVICE_ID` | empty | optional device id sent as `x-sdp-env`, keep it stable per container |
| `PASSWORD` | – | VNC password used by the base image |

## Operating it

```bash
podman exec atrust python3 -m atrustd --status      # JSON: last state, attempts, detail
podman exec atrust python3 -m atrustd --once        # one supervision cycle
podman exec atrust python3 -m atrustd --login-probe # only test the portal login
podman exec atrust python3 -m atrustd --apps        # the apps this account may launch
podman exec atrust ls /run/atrustd                  # NEED_VNC hint + captcha image, if any
```

`--apps` prints what the client's own "App Details" panel shows - the launch method and the URL of
every app the portal grants this account (e.g. a "Default Browser" app is reachable from the host
through the container's proxies). It reads the copy the last login published; `--apps --refresh`
logs in again to update it (that creates a new session, so the supervisor logs the client back in
right after).

When the state is `NEED_VNC`, `ATRUST_STATE_DIR` holds the hint (`NEED_VNC`) and the captcha image
the portal is serving (`captcha.png`, or `captcha.jpg` - the portal picks the format), and the same
instructions are in the journal. Finish the login in the VNC desktop; the supervisor notices the
tunnel coming up and goes back to `ONLINE` on its own.

## Status

* M0 protocol capture: done (login flow, CSRF/rid/env headers, token handling).
* M1 `atrustd` engine: done - verified against a live portal (`code=0 密码认证成功`,
  `authCheck isOnline=True`, `tid`/`tid.sig` in the session).
* M2 token persistence into the client profile: verified on a live container (tray stopped,
  database updated, client restarted and reloaded the tokens).
* M3 watchdog/backoff: done - the state machine walks `STARTING -> DEGRADED -> LOGGED_OUT ->
  ONLINE` on its own, and a tunnel that is up but carries no routes is given a grace period.
* M4 VNC handover: done - a login the engine cannot finish (captcha) writes `NEED_VNC` + the
  captcha image, logs the VNC instructions and goes back to `ONLINE` by itself once a human
  finished the login in the desktop.
* M5 Quadlet: done - `systemctl --user start atrust.service` brings the container up, the tunnel
  follows, and the SOCKS5/HTTP proxies answer on the published ports.
* M6 client-window login: done - `atrustd.uiauto` fills and submits the client's own login window
  (portal address, account, password, agreement) with X level input, so a re-login needs no human;
  a captcha it cannot answer goes to the VNC hand-over.
* M7 app list: done - every login publishes the apps the portal grants this account (name, launch
  URL, launch method, server address) to the log and to `apps.json`; `atrustd --apps` prints it.
* Published image: `ghcr.io/yangtsesu/atrust-quadlet:latest` (public), built from `main` by GitHub
  Actions for `linux/amd64` and `linux/arm64`.
* Details, including how the portal's request validation was solved and how the client's window is
  driven: `docs/STATUS.md`.

## License

GPL-3.0-or-later, see `LICENSES/GPL-3.0-or-later.txt`. This project is [REUSE](https://reuse.software/)
compliant: every file carries `SPDX-FileCopyrightText` / `SPDX-License-Identifier` tags
(`reuse lint`).
