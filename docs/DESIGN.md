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

## Auth methods this project does not drive

The window-driven login above covers the password form and nothing else. Every other page the client
can put there ends in the VNC hand-over: the engine never types into a page it cannot read, and
`atrustd` keeps watching the data plane while it waits. The decision is a policy, not a gap - a
second factor is the account holder's business, and a wrong guess at one costs a portal attempt.

| The portal asks for | What this project does |
|---|---|
| the graphical captcha | `NEED_VNC`; the hint carries the reason, the portal's captcha image is written beside it, and the notifier shows that image as the notification icon (verified live 2026-10-10) |
| a TOTP code (`二次认证`) | the same hand-over; the code is derived locally for the human - `atrustd/totp.py` (RFC 6238) behind `podman exec -e ATRUST_TOTP_KEY=<base32 secret> atrust python3 -m atrustd --totp`, printed by the hint itself |
| an SMS code | the same hand-over; the code goes to the account holder's phone, the engine has nothing to contribute |
| a QR code to enrol an authenticator | the same hand-over; the enrolment happens in the portal UI, and the secret it shows is what feeds `ATRUST_TOTP_KEY` |
| a trust-terminal approval | the same hand-over; the approval happens in the account holder's portal or app |
| a forced password change | the same hand-over; the window is not the password form, so `uiauto` reports it as such and that reason reaches the desktop |

The page names of the sibling project [`kenvix/aTrustLogin`](https://github.com/kenvix/aTrustLogin)
(`totpAuth`, `smsAuth`, `page_auth_trust_terminal`, in its `src/main.py`) show these are separate
pages of the portal SPA rather than one form: which of them a deployment has is that deployment's
setting, and none has been captured here yet. That project drives them in a browser (Selenium, with
`pyotp` for the TOTP page) - the one part of its approach this project shares is the code derivation,
and nothing about the requests the SPA makes, which it never observes.

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

## The client's own log noise

`journalctl --user -u atrust.service` carries lines from the closed client that read like failures.
Measured on the Debian 13 base with client 2.5.16.30, none of them keeps the tunnel from coming up:

| line(s) | frequency | what it is |
|---|---|---|
| `Error: ipv4: FIB table does not exist.` + `Flush terminated` | once per start | the prelude's `detect-route.sh` (upstream) runs `ip route flush table 2` before policy table 2 exists; reproduced in a throwaway container. The detector then fills the table, and the live rule set is the six `iif lo sport <port> lookup 2` rules |
| `Error: Missing goto target for action goto.` | once per start | a kernel netlink **extack**: `fib_rules.c` rejects a fib rule whose action is `goto` and whose target is missing, and iproute2 renders it as `Error: ...`. The sentence exists in the running kernel and in nothing inside the image - so it is a rule update the kernel declined, not a tool failing to start; which process issues it was not pinned, and nothing in this repository uses `goto` |
| `WARNING: logging deactivated (can't log to stdout when daemonized)` | once per start | `tinyproxy`, which forks into the background at start |
| `Failed to connect to user scope bus via local transport: No such file or directory` | 5x per start | the client's own shell probe: it writes `/tmp/aTrustShell.conf` holding `SHELL_CMD=systemctl --user show-environment > /tmp/env` and then runs it; the container has no systemd user bus |
| `sh: 1: cannot create /tmp/aTrustShell.conf: Permission denied` | 4x per start | the same probe: the client's root half owns that file (mode 0644 in a sticky `/tmp`) while the shell executor runs as the unprivileged `sangfor` (uid 1234) |
| `libmmkv.so: cannot enable executable stack as shared object requires: Invalid argument`, wrapped in `UnhandledPromiseRejectionWarning` | ~18x, once per login | the client's history-address store: `resources/bin/libmmkv.so` declares `PT_GNU_STACK` **RWE**, and glibc 2.41 (Debian 13; the host's 2.44 behaves the same) no longer makes the stack executable for `dlopen`. The kernel still allows an exec stack - `mprotect(PROT_READ\|PROT_WRITE\|PROT_EXEC)` on `[stack]` returns 0 on 7.2.9-cachyos - so this is the loader's policy, not the container. What degrades on this base is the client's own history list (this repository's supervisor does not use it). Clearing that bit alone is not enough: MMKV then loads and creates its `SdpcHistory` store, but the first use of the client's sqlite store segfaults inside the bundled SQLCipher (`resources/bin/libsqlite3.so`: `sqlcipher_activate` -> `sqlcipher_malloc` calls a NULL provider function, under `SdpDatabase::initDatabase` in `libSpaProvider.so`) - the cause is the system SQLite Electron brings in, not MMKV, see the section below |
| `(process:<pid>): GLib-GObject-WARNING/CRITICAL: invalid (NULL) pointer instance` / `g_signal_connect_data: assertion 'G_TYPE_CHECK_INSTANCE (instance)' failed` | a few, at start | the client's core plugin (the pid is the one in its `sapp-aTrustAgent_plugins_aTrustCore...` line) with no D-Bus session |

The rest of its output is the client's own diagnostic format - `log isn't inited.[aTrustAgent]
[getUserHomePath:375]...`, `check file size fialed`, `ReferenceError: err is not defined`
(`resources/app/src/service/bsod_checker.js`), `[EAIOSDKWrapper:onComponentLinkageStatusChanged:198]:
argument index out of range`, `Dynamic exception type: apache::thrift::transport::
TTransportException` with `Could not bind: Address already in use` - and none of it changes the
supervisor's state machine: the journal shows `LOGGED_OUT -> ONLINE` right after those bursts.

### The client's own store, and what it takes to fix it

Three independent defects keep the client's address history dead, and all three have to go. Measured
on the host with client 2.5.16.30 and glibc 2.44, where the AUR package `sangfor-atrust-bin` carries
the fixes (a unit drop-in, a launcher preload and a one-byte `prepare()` patch); none of this is
applied to this repository's image, whose supervisor never needs the client's store:

| symptom | cause | fix |
|---|---|---|
| `aTrustDaemon` SIGSEGVs every ~35 s (`X509_VERIFY_PARAM_set_depth` through `libNetwork.so`) | the system `libQt5Network` -> `libproxy` -> `libcurl.so.4` (OpenSSL 3) enters the daemon *before* the bundled `libcurl.so`, and the client's curl references carry no symbol versions (`objdump -T libNetwork.so`), so they bind to the system one - whose OpenSSL 3 object then reaches the client's OpenSSL 1.1 SSL callback | preload the bundled curl into the unit: `Environment=LD_PRELOAD=.../resources/bin/libcurl.so`; libproxy's `CURL_OPENSSL_4` reference still resolves to the system curl |
| pressing next after entering the address SIGSEGVs the tray in `sqlcipher_activate` | Electron brings the system `libsqlite3.so.0` into the tray, beside the bundled SQLCipher (`resources/bin/libsqlite3.so`), and the two SQLites' `sqlite3_*`/provider state collide | preload the bundled one in the tray's launcher: `LD_PRELOAD=$APP/resources/bin/libsqlite3.so` (SQLite 3.31.0, enough for Electron 9) |
| the address list never persists | `resources/bin/libmmkv.so` declares `PT_GNU_STACK` **RWE**; glibc 2.41+ refuses that `dlopen` | `patchelf --clear-execstack` in the package build (1 byte) |

With all three: `SdpMmkv` creates `.../database/SdpcHistory`, entering an address no longer crashes
the tray, and the history survives a restart (verified on the host 2026-10-10).
