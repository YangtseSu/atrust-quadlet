<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Status

Milestones from the plan, with what has actually been verified.

| # | Milestone | State | Evidence |
|---|---|---|---|
| M0 | Protocol capture (no browser needed?) | **done** | Full login flow captured from the portal SPA: `authConfig` (pubKey/pubKeyExp/antiReplayRand/csrfToken), `auth/psw` body and required headers, `reportEnv`, `authCheck`, `onlineInfo`, `checkCode`; the client's cookie store is plain SQLite |
| M1 | `atrustd` HTTP login | **done** | `code=0 密码认证成功` (ticket 73 chars), `authCheck code=0 isOnline=True user=... clientIp=...`, `tid`/`tid.sig` in the session jar |
| M2 | Write `tid`/`tid.sig` into the client profile | **done** | live run: tray stopped, DB row updated (`last_access_utc` moved), values match the session, client back after 4 s |
| M3 | Watchdog + re-login | implemented | `atrustd/probe.py` (tun/routes/proxy CONNECT), `atrustd/state.py`, supervisor loop in `atrustd/__main__.py` |
| M4 | VNC handover | implemented | `atrustd/vnc.py` writes `NEED_VNC` + `captcha.png` into `ATRUST_STATE_DIR` and waits |
| M5 | Quadlet + GHCR packaging | unit drafted | `quadlet/atrust.container`, `quadlet/atrust.env.example`; image build not yet run |

## How the 400 was solved (M1)

`POST /passport/v1/auth/psw` answered `HTTP 400 {"code":10000001,"message":"非法的请求"}` until the
request looked like the SPA's:

* `x-csrf-token` must carry `authConfig.data.security.csrfToken` (POSTs only),
* `x-sdp-rid` = base64(`host:port`), `x-sdp-traceid` = random hex, `x-sdp-env` = base64 device id,
* `Content-Type: application/json;charset=utf-8` on every call,
* password = RSA PKCS#1 v1.5 over `"<password>_<antiReplayRand>"` (hex), i.e. `--padding pkcs1`.

## How the protocol was captured

Run a throwaway container from the base image (client running, `DISPLAY=:1`), attach a Chromium
with Selenium, install a `fetch`/`XMLHttpRequest` hook through
`Page.addScriptToEvaluateOnNewDocument`, log in through the SPA once and read back
`window.__cap`. That yields request bodies, response bodies and (with the XHR
`setRequestHeader` wrapper) the headers the portal insists on. The same run also shows the
local-client detection calls (`POST https://localhost.sangfor.com.cn:54631/v1/detect`).

## Client login: what does NOT work (all verified in a container)

The client (`aTrustAgent` + `aTrustTray`) is the only thing that can bring the tunnel up, and it
does not accept a session that was obtained elsewhere:

| Attempt | Result |
|---|---|
| Browser login through the portal SPA, then its hand-off call | SPA posts `POST https://localhost.sangfor.com.cn:54631/v1/detect` with `{"addr":"<portal>","type":"web","guid":"<authConfig.guid>","lang":...,"sdpTraceId":"<hex>","token":"","data":{}}` - `token` stays empty, and `ip route show dev utun7` remains empty afterwards. The SPA does not hand a session to the client |
| Writing fresh `tid`/`tid.sig` into the client profile + restarting the client | client still reports `logout` (`/v1/service/status`), no routes appear |
| Driving the client's Electron UI over CDP | the tray does **not start at all** when `vpn_ui()` adds `--remote-debugging-port=9222` (checked twice, real and fresh volumes) |
| Calling the client API directly (`/v1/service/status`, `/v1/aUem/statusV2`, `/v1/service/init`) | `HTTP 503` for bare GET/POST. The tray uses an envelope: `{"type":"cs","lang":"...","guid":"...","addr":"...","token":"...","sdpTraceId":"...","data":...}` posted over HTTPS to the agent (see `aTrustTray*.log`: `Agent request https get, url: /v1/aUem/statusV2 post_data: {...}`) |

Conclusion: the client logs in **inside its own UI**. Headless auto-login therefore has to inject
input into that window (X level, e.g. `xdotool`), with a VNC hand-over whenever the portal asks for
the graphical captcha - which is exactly the behaviour requested (VNC on first login / stale
tokens).

## Verification commands

```bash
# M1: portal login only (no client involved)
podman exec -e PYTHONPATH=/opt -e ATRUST_PORTAL_URL=... -e ATRUST_USERNAME=... -e ATRUST_PASSWORD=... \
  atrust python3 -m atrustd --login-probe -v

# M2 + supervisor: token write, client restart, state transitions
podman exec atrust python3 -m atrustd --once -v
podman exec atrust python3 -m atrustd --status
podman exec atrust ip route show dev utun7     # routes == client is online
```

## Next

1. **`atrustd/uiauto.py` (the way forward).** Drive the client's own login window with X level input
   injection (`xdotool`: find the window, type account/password, tick the agreement, submit), then
   confirm `ip route show dev utun7` shows VPN routes. On captcha, fall back to `vnc.hint()`.
   `xdotool` is not in the base image - add it in the Containerfile (`apt-get install xdotool`).
2. **Authoritative status signal.** The client's own API reports state
   (`/v1/service/status` -> `data.status`), but only answers the tray's envelope (see the table
   above). Either send that envelope (`{"type":"cs","lang":...,"guid":...,"addr":...,"token":...,
   "sdpTraceId":...,"data":...}`) or keep using the data plane (tun + routes), which already works.
3. Verify the Quadlet unit on a host: `systemctl --user start atrust.service` (the generator accepts
   `quadlet/atrust.container`; checked with `QUADLET_UNIT_DIRS=... /usr/lib/podman/quadlet -dryrun -user`).
4. M4 verification: run once with a deliberately wrong password and check that `NEED_VNC`, the hint
   file and `captcha.png` appear in `ATRUST_STATE_DIR`.
5. Long-run observation: how often the portal asks for a captcha, and whether a web login ever kicks
   the client's own session (single-session policies).
