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

## Next

1. `podman build` the image and run the Quadlet unit on a host (M5).
2. Verify the full loop end to end: token refresh → client restart → tunnel, with `atrustd --once`.
3. Decide whether the client must be restarted at all after a token refresh (today: yes, so the
   tray loads the new cookies).
4. Long-run observation: how often does the portal ask for a captcha in practice (M4 tuning).
