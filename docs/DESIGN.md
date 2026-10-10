<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# How it works

The user-facing side (install, configure, operate) is in `README.md`. This file is the engineering
side: what `atrustd` does, why the login is split in two, and how the client's own window is driven.
The plan is `docs/plans/` (one file per step), the direction `docs/ROADMAP.md`, and the retired
records - the milestone log to 2026-10-10 with all its measurements - `docs/archive/`.

The pieces: `base/` builds the client image - the aTrust client (its tray, agent and userspace
netstack) from Sangfor's package, the tigervnc X server, microsocks (SOCKS5) and tinyproxy (HTTP),
plus the iptables/sysctl/getlogin shims the client expects in a container. This project adds
`atrustd` (a Python supervisor, stdlib only) and the Quadlet unit. `atrustd` never talks to the
client's internals - it talks to the portal, writes the client's own profile, drives the client's
own window with X level input, and decides everything with the data plane.

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
elsewhere); it exists to refresh `tid`/`tid.sig`, which is what keeps the
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

The geometry behind these probes is pinned offline rather than remembered:
`tests/test_uiauto_geometry.py` replays `classify()`, `find_box()`, `find_button()` and
`_agreement_checked()` over two saved window dumps (`tests/data/screens/`, client 2.5.16.30 - the
connection page and the password form) and fails when a constant drifts or a probe stops matching
the saved pixels; the dumps are re-captured on a client bump (the recipe is in the test's
docstring).

## The supervisor

One cycle every `ATRUST_WATCH_INTERVAL` seconds (90 by default), and the sleep lives in the caller -
`cycle()` returns the delay - so a healthy tunnel cannot turn the loop into a busy loop (it once did). A cycle decides with the data plane, cheapest check first:

1. the tunnel interface exists and carries an address (`ip -brief addr show utun7`),
2. the client installed routes pointing at it (`ip route show dev utun7`),
3. with `ATRUST_PROBE_TARGET` set, traffic really reaches an intranet target through the container's
   HTTP proxy - a real HTTP request for a plain HTTP target (`CONNECT` for `:443`, which cannot be
   sent a plain request), retried three times, because the client's netstack drops an occasional
   connection of its own accord.

Step 3 is also the keepalive. The portal expires a session whose tunnel only carried `CONNECT`s -
about ten minutes of quiet was enough, with the probe itself running - while the same cadence with
real requests held the session for hours (measured 2026-10-09: 10.3 minutes with `CONNECT`s only,
over an hour with real requests at the same 90 s cadence). So the
supervisor's own probe keeps the session alive and nothing else has to touch the tunnel.

That maps to the state file (`ATRUST_STATE_DIR/state.json`, what `--status` prints) and to the
journal: `STARTING`, `ONLINE`, `DEGRADED` (tunnel not usable yet), `LOGGED_OUT` (the session is
gone, re-login running) and `NEED_VNC` (a human is needed). `quadlet/atrust.container` mounts that
directory on the host as well (`~/.atrust-data/run`), so the state - and the `NEED_VNC` hint and the
captcha beside it - survives the container being recreated and is readable without entering the
container. Recovery walks the same path a human
would: restart the client when the web session is still alive, otherwise log in to the portal for
fresh tokens, submit the client's own window, and fall back to the VNC hand-over when the portal
asks for a captcha. Every wait is bounded (`ATRUST_VNC_WAIT`) and every failure backs off
exponentially.

## Stopping the container

The Quadlet unit's stop comes down to `ExecStop=podman rm -f atrust` (systemd's own unit, generated
by Quadlet), which signals PID 1 - `atrustd` - and waits `[Container] StopTimeout=5`. The SIGTERM
handler only sets a `threading.Event`; the daemon's waits (`ATRUST_WATCH_INTERVAL`, the tunnel wait,
`ATRUST_VNC_WAIT`) wait on that event instead of sleeping, because CPython re-enters `time.sleep`
after a signal and the flag used to be read only after the whole cycle returned. A stop in the
steady `ONLINE` state is answered in about a second and a half - a second of it is the client's own
SIGTERM grace, see below; a stop inside a cycle waits for the step it is in (a UI step, a probe
retry) - seconds, not minutes.

On the way out the daemon sweeps the client: `aTrustXtunnel-64` (which detaches and reparents to
PID 1, so no parent-based cleanup reaches it), its watchdog child, the agents and the trays. SIGTERM
first, then SIGKILL for what is still there - the tunnel, the trays and the client's own restarts
leave on SIGTERM, the Electron children and the plugin daemon do not. Matching is by the binary's
path (a `pkill -f` pattern): `pkill -x` compares the command *name*, which the kernel truncates to
15 characters, so the name of the tunnel binary is `aTrustXtunnel-6` there. The tray-only
`tokens.stop_client()` on the token-refresh path is deliberately not this sweep: a refresh must keep
the agent and the tunnel up while the tray reloads the new cookies.

Measured 2026-10-10 (podman 6.1.3, rootless, the published image, client family up, 13 processes):

| | before | after |
|---|---|---|
| `podman stop` | 10.2 s (podman's `--stop-timeout`), the client left by SIGKILL from the cgroup | 1.5 s, `client stop took 1.27s` in the journal |
| `podman rm -f` (what systemd runs) | 8.4 s | 1.9 s, same 1.27 s of sweep |
| the daemon itself, `ONLINE`, after SIGTERM | - | 1.58 s (6 of 12 processes needed the SIGKILL) |

The same day, on the live container with the tunnel `ONLINE` (`systemctl --user stop atrust`, the new
images built locally): 1.77 s against 10.37 s for the image it replaced, the journal showing
`signal 15 received`, `4 of 12 client process(es) ignored SIGTERM, SIGKILLing [...]` and
`client stop took 1.26s`, no client process left on the host, and `start` back to `ONLINE` in about
30 s.

Before the sweep existed, the only thing that ever killed the client was the cgroup teardown: the
container stopped, the client never heard a signal, and every `systemctl --user stop atrust` cost
the full ten seconds.
