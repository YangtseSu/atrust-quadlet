<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Status

Milestones from the plan, with what has actually been verified.

| # | Milestone | State | Evidence |
|---|---|---|---|
| M0 | Protocol capture (no browser needed?) | **done** | Full login flow captured from the portal SPA: `authConfig` (pubKey/pubKeyExp/antiReplayRand/csrfToken), `auth/psw` body and required headers, `authCheck`, `onlineInfo`, `checkCode`; the client's cookie store is plain SQLite |
| M1 | `atrustd` HTTP login | **in progress** | `authConfig` works; `auth/psw` still answers `HTTP 400 code=10000001 非法的请求` |
| M2 | Write `tid`/`tid.sig` into the client profile | implemented | `atrustd/tokens.py` (plain SQLite upsert + client stop/start); not yet exercised against a live portal |
| M3 | Watchdog + re-login | implemented | `atrustd/probe.py` (tun/routes/proxy CONNECT), `atrustd/state.py`, supervisor loop in `atrustd/__main__.py` |
| M4 | VNC handover | implemented | `atrustd/vnc.py` writes `NEED_VNC` + `captcha.png` into `ATRUST_STATE_DIR` and waits |
| M5 | Quadlet + GHCR packaging | unit drafted | `quadlet/atrust.container`, `quadlet/atrust.env.example`; image build not yet run |

## Current blocker (M1)

`POST /passport/v1/auth/psw` returns `HTTP 400 {"code":10000001,"message":"非法的请求"}`.

What is already aligned with the SPA (captured from the browser):

* body `{"username":"<user>@local","password":"<512 hex chars>","rememberPwd":"0"}`
* password plaintext `"<password>_<antiReplayRand>"`, RSA-encrypted with `data.pubKey` (hex, 2048 bit)
  and `data.pubKeyExp`; PKCS#1 v1.5 assumed, OAEP implemented as `--padding oaep`
* headers `x-sdp-rid` (base64 `host:port`), `x-csrf-token` (from `data.security.csrfToken`),
  `x-sdp-traceid`, `Content-Type: application/json;charset=utf-8`

Open suspects, in the order they will be tested:

1. `x-sdp-env` (base64 `{"deviceId":"<id>"}`) - present on the SPA's login POST, currently omitted
   unless `ATRUST_DEVICE_ID` is set.
2. RSA padding (PKCS#1 v1.5 vs OAEP).
3. Cookies the SPA already holds when it posts (`tid`/`tid.sig` are injected from the client
   profile; other base cookies come from the portal page warm-up).

Reproduce:

```bash
podman exec -e PYTHONPATH=/opt \
  -e ATRUST_PORTAL_URL=https://vpn.example.com/ \
  -e ATRUST_USERNAME=... -e ATRUST_PASSWORD=... \
  atrust python3 -m atrustd --login-probe -v
```
