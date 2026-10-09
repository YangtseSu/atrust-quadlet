<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# How it works

The user-facing side (install, configure, operate) is in `README.md`. This file is the engineering
side: what `atrustd` does, why the login is split in two, and how the client's own window is driven.
Measurements, milestones and closed decisions live in `docs/STATUS.md`; open work in
`docs/ROADMAP.md`.

The pieces: the base image brings the aTrust client (its tray, agent and userspace netstack), Xvfb,
VNC, danted and tinyproxy. This project adds `atrustd` (a Python supervisor, stdlib only) and the
Quadlet unit. `atrustd` never talks to the client's internals - it talks to the portal, writes the
client's own profile, drives the client's own window with X level input, and decides everything with
the data plane.

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

## The supervisor

One cycle every `ATRUST_WATCH_INTERVAL` seconds (90 by default), and the sleep lives in the caller -
`cycle()` returns the delay - so a healthy tunnel cannot turn the loop into a busy loop (it once
did, see `docs/STATUS.md`). A cycle decides with the data plane, cheapest check first:

1. the tunnel interface exists and carries an address (`ip -brief addr show utun7`),
2. the client installed routes pointing at it (`ip route show dev utun7`),
3. with `ATRUST_PROBE_TARGET` set, traffic really reaches an intranet target through the container's
   HTTP proxy - a raw `CONNECT`, retried three times, because the client's netstack drops an
   occasional connection of its own accord.

That maps to the state file (`ATRUST_STATE_DIR/state.json`, what `--status` prints) and to the
journal: `STARTING`, `ONLINE`, `DEGRADED` (tunnel not usable yet), `LOGGED_OUT` (the session is
gone, re-login running) and `NEED_VNC` (a human is needed). Recovery walks the same path a human
would: restart the client when the web session is still alive, otherwise log in to the portal for
fresh tokens, submit the client's own window, and fall back to the VNC hand-over when the portal
asks for a captcha. Every wait is bounded (`ATRUST_VNC_WAIT`) and every failure backs off
exponentially.
