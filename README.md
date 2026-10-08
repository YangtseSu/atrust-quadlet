<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# atrust-quadlet

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
| Captcha / first login needs a human | the supervisor writes a `NEED_VNC` hint (plus the captcha image) and waits; open VNC, finish the login in the desktop, and supervision continues automatically |
| Login state is watched, re-login is automatic | data-plane probes (`utun7` + routes + an intranet target through the HTTP proxy) drive a small state machine (`ONLINE`/`DEGRADED`/`LOGGED_OUT`/`NEED_VNC`) with exponential backoff |
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

## Quick start

```bash
podman build -t ghcr.io/<you>/atrust-quadlet:latest .
install -d ~/.config/containers/systemd
cp quadlet/atrust.container ~/.config/containers/systemd/
install -m600 quadlet/atrust.env.example ~/.config/atrust.env   # edit it first
systemctl --user daemon-reload
systemctl --user start atrust.service
journalctl --user -u atrust.service -f
```

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
| `ATRUST_STATE_DIR` | `/run/atrustd` | where `state.json`, `NEED_VNC` and `captcha.png` are written |
| `ATRUST_CLIENT_COOKIE_DB` | `/root/.aTrust/AppCache/Cookies` | the client's own cookie store |
| `ATRUST_PROXY` | `127.0.0.1:8888` | HTTP proxy used by the data-plane probe |
| `ATRUST_TUN` | `utun7` | tunnel interface created by the client |
| `ATRUST_DEVICE_ID` | empty | optional device id sent as `x-sdp-env`, keep it stable per container |
| `PASSWORD` | – | VNC password used by the base image |

## Operating it

```bash
podman exec atrust python3 -m atrustd --status      # JSON: last state, attempts, detail
podman exec atrust python3 -m atrustd --once        # one supervision cycle
podman exec atrust python3 -m atrustd --login-probe # only test the portal login
```

## Status

* M0 protocol capture: done (login flow, CSRF/rid/env headers, token handling).
* M1 `atrustd` engine: done - verified against a live portal (`code=0 密码认证成功`,
  `authCheck isOnline=True`, `tid`/`tid.sig` in the session).
* M2 token persistence into the client profile: verified on a live container (tray stopped,
  database updated, client restarted and reloaded the tokens).
* M3 watchdog/backoff, M4 VNC handover, M5 Quadlet: implemented, end-to-end run pending.
* Details, including how the portal's request validation was solved: `docs/STATUS.md`.

## License

GPL-3.0-or-later, see `LICENSES/GPL-3.0-or-later.txt`. This project is [REUSE](https://reuse.software/)
compliant: every file carries `SPDX-FileCopyrightText` / `SPDX-License-Identifier` tags
(`reuse lint`).
