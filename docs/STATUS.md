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

1. **Client login handoff (the real open item).** The engine can refresh `tid`/`tid.sig` and write
   them into the client profile, but the *client* does not go online from tokens alone: in the
   end-to-end run the client stayed in `logout` after the token refresh and restart. Something has
   to hand the web session to the client, which is what the portal SPA does after a browser login.
   Next step: capture that message (the SPA's POST to `https://localhost.sangfor.com.cn:54631/...`
   right after login) with the same CDP hook, then implement it as `atrustd/handoff.py`.
2. **Authoritative status signal.** The client's own API reports the state:
   `GET /v1/service/status` on `127.0.0.1:54631` answers
   `{"code":0,"data":{"status":"logout","data":{...}}}` when seen from the tray (Electron RPC).
   Direct requests currently get `HTTP 503 ServiceUnavailable`, so the required headers must be
   captured from the tray's request as well. Once that works, `probe.py` should prefer it over the
   data-plane heuristics (tun/routes stay as confirmation).
3. Verify the Quadlet unit on a host: `systemctl --user start atrust.service` (the generator accepts
   `quadlet/atrust.container`; checked with `QUADLET_UNIT_DIRS=... /usr/lib/podman/quadlet -dryrun -user`).
4. Long-run observation: how often the portal asks for a captcha in practice (M4 tuning), and
   whether a web login ever kicks the client's own session (single-session policies).
