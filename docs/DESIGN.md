<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# How it works

The user-facing side (install, configure, operate) is in `README.md`. This file is the engineering
side: what `atrustd` does, why the login is split in two, and how the client's own window is driven.
The plan is `docs/plans/` (one file per step), the direction `docs/ROADMAP.md`, and the retired
records - the milestone log to 2026-10-10 with all its measurements - `docs/archive/`. The client's
own loopback HTTPS service - the interface its web workbench and the vendor's CSSDK use - is
catalogued in `docs/CLIENT-LOCAL-API.md`; the supervisor uses it from `atrustd/clientapi.py`: it
reads the client's own view beside every transition, watches the client's own event channel, and
hands the client the ticket that logs it back in.

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
POST /passport/v1/public/ticketExchange?<same query>   (no body; the session cookies are the request)
       -> data.sidTicket (73 characters): the ticket the client's own login hands the agent
GET  /passport/v1/public/checkCode?<...>&rnd=<ms> -> the graphical captcha image
```

`atrustd` implements this with the Python standard library only (urllib + sqlite3 + a small RSA
PKCS#1 v1.5 implementation): the base image has no python3 and we deliberately avoid pip,
`requests` and `cryptography`.

The portal's certificate is never *verified* - `insecure` exists because these portals sit behind
internal CAs - but the portal publishes the certificates it serves for its own clients to compare the
TLS peer against: `authConfig`'s `data.antiMITMAttackData.rsaCert`/`sm2encCert`, both present on this
deployment's portal beside `enable: 0` (read live 2026-10-13), and their identifier is the SDK's own,
`SHA-256(base64(DER) + "@~*&!()-")` (`zju-connect`'s `sangforEncodedCertificateDigest`, the digest
taken over the base64 text and not over the DER). The official clients log a mismatch and carry on,
never refuse; `atrustd` does the same, one extra `ssl` handshake with verification off beside every
login: the peer's digest at debug - the live line here was `portal TLS peer certificate sha256=…
matches authConfig (rsaCert, sm2encCert)`, i.e. this portal serves the certificate it publishes - and
a warning when the portal published something and neither digest matches, which is what a replacing
proxy in front of the portal would look like. The line is evidence for a client bump and for a proxy
investigation; it decides nothing, and the login proceeds either way.

## How the client logs in (its own calls first, the window as the fallback)

The web login above never brings the tunnel up by itself; it exists to refresh `tid`/`tid.sig`,
which is what keeps the *client's* login captcha free, and it is where the ticket below comes from.
Since 2026-10-11 the supervisor logs the client back in through the client's own calls first - the
sequence the client's own web workbench makes on a portal login (`docs/CLIENT-LOCAL-API.md`, "The
login path, verified"):

1. the engine's live portal session mints the ticket (`POST /passport/v1/public/ticketExchange`,
   `portal.py::sid_ticket`; its session is refreshed first when it has gone cold),
2. the agent's `POST /v1/service/start` takes it (`clientapi.py::start`; the envelope needs the
   client's own `sdpcguid`, which the status read publishes),
3. the tunnel is waited for on a 60 s bound.

Measured live 2026-10-11 on the dev container, driven by the supervisor: `LOGGED_OUT` 23:51:50.8 →
mint 23:51:50.9 → `start` 23:51:51.1 → `ONLINE` 23:51:56.2 - five seconds, no window opened, the
event channel showing `leaveInitial`, `login`, `enterOnline` on the way.

The client's own window is the fallback, and it takes the cycle whenever the ticket path cannot run
or the tunnel does not come up on it. `atrustd.uiauto` then does what a human in the VNC session
would do:

```
portal address (every client start) -> account -> password -> agreement -> submit
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

The measured limits of the ticket path are what the window is still for. A fresh container's client
publishes no `sdpcguid` for its first ~40 s (measured - an empty guid makes `start` answer
`Invalid schema: #/properties/guid`, so the attempt is not made at all), which is also why the
attempt's way in waits ten seconds for a guid only where this daemon has seen one before: a guid
that has been published once comes back within ~5 s of a tray restart, while a client that has never
published one is a container that has just been recreated - 35 s+ - and the window path's login runs
there anyway, so a cold start pays no bound for nothing. A portal that wants the
graphical captcha stops the ticket mint as well as the login; a client whose own view already says
it is in a session has nothing for a ticket to fix; and a ticket the agent refuses comes back as a
code (`75500304 当前票据已失效` for a stale one, measured 2026-10-11). Each of those leaves its
reason in the journal and in the state detail of the recovery that follows (`the ticket login: ...`,
the field the notifier shows), so the human sees which path was already tried. `uiauto` is unchanged,
one pass per cycle.

The restart branch runs before the ticket path, and it is not always able to help: when the client's
own view says `logout` with `tunnelUnavailable`, the portal has ended that session and a restart
cannot repair it. Measured on 2.5.16.41, that detour cost 2.4 minutes (stop, restart, a 120 s tunnel
wait that could not succeed) before the ticket path recovered the same session in 5.4 s. So the
branch reads the view the `DEGRADED` transition just recorded and stands aside for exactly that
shape; everything else - any other state the client answers, a read that failed (its service is
unreachable for ~2-4 s around a restart), or no view at all with `ATRUST_CLIENT_API` off - restarts
as before. The journal and the `LOGGED_OUT` detail say it (`client logout/tunnelUnavailable; not
restarting it`), and the cycle goes straight to the login path. The branch is still what repairs a
session the client's own view does not call ended, and when the engine's portal session is already
cold it is not reached at all - the ticket path is then the first thing to run.

One login per cycle: when the engine's portal session has gone cold, `_api_login` runs the fresh
login itself (the window path's ground work either way) and the window path reuses that session
instead of asking the portal again - the repeat was measured refused (`75500006 当前账号已在线，无需
重复上线`, 0.3 s after the first had landed) and made the journal read like a failed login although
the first one stood.

The portal address is written to the client's own config (`ATRUST_CLIENT_ADDR_CONF`) before the
client starts, and the client's own start-up path picks it up: the address lands in its saved-address
store, the window is created with the address already in its URL, and the client's router guard runs
its connection detect and moves to the login page by itself, so `uiauto` only fills the credentials.
Typing the address into the window stays as the fallback for a client that has no address anywhere.
The account is the one field the client remembers on its own: the login page initialises it from its
own last-username state, so `uiauto` types over a filled account field and into an empty address
field (measured live 2026-10-11, client 2.5.16.30).

The geometry behind these probes is pinned offline rather than remembered:
`tests/test_uiauto_geometry.py` replays `classify()`, `find_box()`, `find_button()` and
`_agreement_checked()` over saved window dumps (`tests/data/screens/` - the connection page and the
password form as client 2.5.16.41 renders them, the error row and the captcha dialog as 2.5.16.30
did) and fails when a constant drifts or a probe stops matching the saved pixels; the two
fresh-profile dumps are re-captured on a client bump (the recipe is in the test's docstring), and
the 2.5.16.41 re-capture reproduced them: the login page byte for byte, the connection page down to
five pixels of box-corner antialiasing, at the same window origin and size.

The vendor's own SDK (`resources/bin/libaTrustSDK.so`, the "CSSDK" its docs describe) was measured
as an alternative login path (2026-10-12, client 2.5.16.30, a throwaway container with the account)
and is deliberately not one: `atrust_sync_login_by_pwd` comes back `10403` in 0.3 s without ever
reaching the portal - the client's local auth setup refuses the call
(`init server config failed.; Reason: fail code: 10403`, `libaTrustAuth.so`) - and even a call that
got through would meet the graphical captcha this deployment demands of a password login
(`graphCheckCodeEnable: 1`). The SDK's status query works and is a thin client of the same
`/v1/service/status` this engine already calls, so nothing about the login changes; the ticket path
and the window stay what they were.

## What the portal lists the terminal as

The client registers the terminal under the container's UTS hostname, and the portal's terminal list
shows that string - a login from the host itself appears there under the host's own name. Podman's
default hostname is the container ID, so every recreated container entered that list as a new 12 hex
name of its own, and the names of containers long removed stay behind as history. The unit therefore
sets `HostName=%H`, i.e. the name of the machine the container runs on: Quadlet turns the key into
`--hostname %H` (the generator emits the specifier untouched) and systemd resolves `%H` when the
unit loads. Measured 2026-10-10 on podman 6.1.3: a container created without `--hostname` reports
its own ID from `hostname` and in `/etc/hostname`; `--hostname <name>` sets both plus the `/etc/hosts`
line; a user unit's `ExecStart` resolves `%H` at start. A deployment that wants a name of its own
overrides the key in `atrust.container.d/`.

The name is all this changes. The device id the supervisor's own session reports (`x-sdp-env`,
`portal.py::_device_id`) belongs to the deployment: `ATRUST_DEVICE_ID` if set, otherwise one
generated on first use and kept in `$ATRUST_STATE_DIR/device-id`. It must not come from
`/etc/machine-id`, which is what it used to do: the image ships one machine id, so every container
built from it - any deployment, any host - reported the same id, and every rebuild replaced that id
(measured 2026-10-10: the published image's `/etc/machine-id` is that single file, and no
md5/sha1/sha256 of it appears anywhere in the client's own profile, so the client's terminal record
does not use it either). The machine id stays the last resort for a state directory that cannot be
written. The *client's* own device identity is a different story: measured 2026-10-11, two containers
of the same image on the same host - different accounts, different state directories, different
engine `x-sdp-env` values - report the **same** `sdpcguid` to the portal, and a container with nothing
running has no guid anywhere in its filesystem, so the client derives it at runtime. What it derives
it from is not pinned; the containers share the image's machine id and the host's hardware address,
and the note above found no plain hash of the machine id in the client's own profile, so it is not
that alone. Either way the consequence is measured on this host: every container of the image on it
is the same device to the portal.

## Auth methods this project does not drive

The window-driven login above covers the password form and nothing else. Every other page the client
can put there ends in the VNC hand-over: the engine never types into a page it cannot read, and
`atrustd` keeps watching the data plane while it waits. The decision is a policy, not a gap - a
second factor is the account holder's business, and a wrong guess at one costs a portal attempt.

| The portal asks for | What this project does |
|---|---|
| the graphical captcha | `NEED_VNC`; the hint carries the reason, the portal's captcha image is written beside it, and the notifier shows that image as the notification icon (verified live 2026-10-10). Re-verified from a cold login with a second account in a throwaway container 2026-10-11: it stops *both* logins - the engine's portal login answers `图形验证码已超时，请重试` and the client's own window login answers `75500000 The characters has expired` with `graphCheckCodeEnable: 1` - and it is a click-in-order image (the characters to click and their order are baked into the picture), not a typed code. Once a human answered it in the client's window the login completed and the tunnel came up (30 routes, probe `HTTP/1.1 200`) |
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
3. a witness answers through the container's HTTP proxy - a real HTTP request for a plain HTTP
   target (`CONNECT` for `:443`, which cannot be sent a plain request), retried three times,
   because the client's netstack drops an occasional connection of its own accord.

The witnesses of step 3 are the `ATRUST_PROBE_TARGET` a human named (first) and, with
`ATRUST_PROBE_DISCOVER` on (the default), the addresses the tunnel itself routes one by one: the bare
host routes of `ip route show dev utun7`, capped at four, each asked once per round on a 3 s leash (the
table is the client's own and a search must not grow with it). The route table is the only source that
exists without a portal session: a deployment whose portal demands the graphical captcha never lets the
engine log in (`publish_apps` never runs, so `apps.json` stays empty), while the routes exist as soon
as the client's own login does. An
address is a witness for the tunnel, not the tunnel, so a target that cannot answer does not decide
the check while another witness answers: the cycle is `ONLINE`, nothing is restarted, and the state
detail says which witness answered (`no answer from <configured>; probe <host>:80 ok (HTTP/1.1 200,
route)`). With nothing answering and the datapath up, the cycle is `DEGRADED` as before; with
`ATRUST_PROBE_DISCOVER=0` and no target configured, the interface and its routes are the proof and no
request is sent at all. The two leashes are measured: on the live container (2026-10-13) the resource
address that deployment routes answered through the proxy in 0.03 s, while a bare address of the
client's own virtual range (`198.18.255.1`, one of the two bare routes in that table) never answers -
it times out at the full 8 s, which is why a route-derived candidate gets 3 s and an address a human
named keeps the 8 s the probe always had.

Step 3 is also the keepalive. The portal expires a session whose tunnel only carried `CONNECT`s -
about ten minutes of quiet was enough, with the probe itself running - while the same cadence with
real requests held the session for hours (measured 2026-10-09: 10.3 minutes with `CONNECT`s only,
over an hour with real requests at the same 90 s cadence). So the
supervisor's own probe keeps the session alive and nothing else has to touch the tunnel. A
discovered witness is a real request too, so a deployment that never configured a target now keeps
its session alive as well - the app list cannot stand in for it there, because the portal that
demands the captcha never lets the engine log in and `apps.json` stays empty, while the tunnel's
routes exist either way.

That maps to the state file (`ATRUST_STATE_DIR/state.json`, what `--status` prints) and to the
journal: `STARTING`, `ONLINE`, `DEGRADED` (tunnel not usable yet), `LOGGED_OUT` (the session is
gone, re-login running) and `NEED_VNC` (a human is needed). `quadlet/atrust.container` mounts that
directory on the host as well (`~/.atrust-data/run`), so the state - and the `NEED_VNC` hint and the
captcha beside it - survives the container being recreated and is readable without entering the
container; every file the engine writes there is 0600 (`state.write_private`: `state.json` through
its atomic temp file, `NEED_VNC`, the captcha image, `apps.json`, `device-id` and the bundles), because
the mount makes a file left 0644 readable by every local user of the host - measured 2026-10-13
before the change: `ls -l ~/.atrust-data/run` showed `state.json` (the account name and the client's
own view) and `apps.json` at 0644, beside `device-id` at 0600.

Recovery walks the same path a human would: restart the client when the web session is
still alive and the client's own view does not say it is logged out (a `logout`/`tunnelUnavailable`
client skips the restart and its wait - the login path recovers in seconds, the restart cost minutes
and could not have helped); otherwise log in to the portal for fresh tokens and hand the client the
ticket that login mints (`sid_ticket` → `/v1/service/start`, the calls the client's own workbench
makes) - the client's own window is the fallback when the ticket path cannot run or the tunnel does
not come up on it, and the VNC hand-over is what happens
when the portal asks for a captcha. Which path ran is in the transition (`tunnel up after the
ticket login` / `after the client login` / `after client restart`) and, when the hand-over comes
next, in the state detail (`the ticket login: ...`) beside the hint. Every wait is bounded
(`ATRUST_VNC_WAIT`) and every failure backs off
exponentially.

The portal's refusals are read as classes before they are read as prose. `portal.classify` turns a
non-zero answer into `session-invalid` (`75500002`, `75500001`, and the sibling
reimplementation's `10000004`), `already-online` (`75500006` - the portal still holds the account
online after a client-side logout, measured 2026-10-11), `captcha`, `wrong-password` or
`rate-limited`. The graphical-captcha demand is decided by `data.graphCheckCodeEnable` first - a
field of the answer, so the decision does not depend on the language the caller asked for - with
the message hints and `75500000` behind it; the two classes whose code is not pinned yet are read
from the row's own words (`The username or password is incorrect. You still have 9 attempts left`,
measured 2026-10-10). The class travels beside the code, in the login's journal line
(`password auth failed: code=75500006 class=already-online message=...`) and in the hand-over's
state detail (`...; code=... class=...`). The client's own service answers by code as well, and
its codes are their own space with their own classes (`clientapi.classify`: `already-logged-in`,
`stale-ticket`, `invalid-parameter`, `invalid-request`, `query-failed`, `proxy-failed`;
`docs/CLIENT-LOCAL-API.md` lists where each was measured).

One class decides anything beyond the hand-over: a `wrong-password` or `rate-limited` answer stops
the engine's logins - no fresh login, no window submit - until the tunnel is up or the daemon
restarts. The password comes from `ATRUST_PASSWORD`, so nothing inside the process can correct it,
and the portal counts the checks it makes (one per password it checked: 10 → 9 on the 2026-10-10
drill). The cycle goes to `NEED_VNC` with the portal's own row in the hint, its counter parsed out
of the row when it prints one, and the `--login-probe` command named beside it - the human's own
explicit attempt, which spends one of the account's attempts only when they choose to. The tunnel
coming up clears the record (the human may have fixed the credential and logged in over VNC
themselves), and so does a restart, which is also how a corrected env file is re-read.

Beside the data plane the supervisor records the client's own view. `POST /v1/service/status` on the
client's loopback service (`atrustd.clientapi`; the port is read from the client's own run file,
with the `+11` backups behind it) is one request - no window, no X11 - and answers with the client's
user state (`online`, `logout`, ...), its tunnel state (`tunnelAvailable`, ...), the logged-in user
name and the login time. Every transition reads it and writes it beside the state it belongs to:
`state.json` gains a `client` object (the four fields, or the reason they are missing) and the
transition line in the journal carries the same phrase (`...; client logout/tunnelUnavailable`).
That is what a human - and `quadlet/atrust-notify.sh` - reads beyond the probe's detail: *who* is
logged in and since when, not only what the packets did.

The decision stays the data plane for the tunnel itself, and the one branch the view does decide is
the restart: when the client itself reports `logout` while its tunnel reads `tunnelUnavailable`, the
cycle skips the restart and its 120 s wait and goes straight to the login path (measured on
2.5.16.41: 5.4 s from `DEGRADED` to `ONLINE`, against 2.4 minutes through the branch). Nothing else
reads the record: the client can report `tunnelAvailable` while its netstack drops traffic, so the
two are not compared, in a controlled logout (measured 2026-10-11) its `tunnelStatus` and the probe
flipped within the same two-second sample, i.e. the view adds no earlier warning, and the one
vocabulary the data plane cannot express at all - `otherSdpCLogin`/`otherSdpCOffline`, this client
online to another portal - did not occur on a deployment that talks to a single portal, so it keeps
the branch as before.

The client's own event channel is what can cut the interval short. `/v1/service/events` on the same
loopback service is a long poll - it holds the request for up to its own `timeout` field and answers
with whatever the client published, and its event ids restart with the agent - and `atrustd`
subscribes to it from a background thread (`atrustd.clientapi.EventPoller`) whose only output is a
`threading.Event` the daemon's waits watch beside the stop event. A transition the client publishes -
entering or leaving the session or its online run, a status or tunnel change - therefore starts the
next cycle in seconds instead of at the next `ATRUST_WATCH_INTERVAL`, and the cycle that runs is the
same one every other wake runs: `probe.check()` still decides. The event is only ever a hint to look
now, which is the vendor's own guidance for the channel as well (after a logout or tunnel event,
re-query the state instead of trusting it). The cycle logs the event(s) that woke it and its first
transition's detail carries them, so the journal and `state.json` say why a cycle ran early.

The filter is the throttle. Waking costs a probe cycle - two `ip` forks and a request through the
proxy - so only the session and tunnel vocabulary wakes (`logout`, `login`, `online`, `offline`,
`enterOnlineRun`/`leaveOnlineRun` and the rest of the client's own enum, plus the core plugin's
`statusEvent|*` forms); the chatter the channel also carries (`ready`, `resourceReady`, the consult
events, `uemStatus*`) is read and dropped. A poll that fails resets `fromId` to 0 - the agent's ids
restart with it - and retries on a 2 s, doubling backoff capped at 30 s, so a client that is down
for minutes costs a loopback connect every 30 s and nothing else; the journal carries the whole
path (`client events unreachable: ...; retrying in Ns`, then `client event channel is up (id N)`).

Measured on the dev image 2026-10-11 with two controlled downs: the supervisor's own family sweep
(`tokens.stop_client_family`) killed the in-flight long poll 0.05 s after the stop, the poller read
`the client service is not listening` at +2.1 s, reconnected at +6.6 s (the agent's own restart by
the vendor's loop) and the burst that followed - `tunnelStatus`, then the full `status` - woke a
cycle at **+7.1 s**, where the blind cadence would have looked 65.9 s after the down; a killed
tunnel was respawned by the client itself and announced as restored at +5.1 s, waking a cycle at
+5.3 s. Neither down outlived the client's own repair, so neither left a `DEGRADED` in the state
file: the channel shortens what the supervisor reacts to, it does not decide what it sees. When the
client itself goes down, nothing can publish anything - the channel's death is all the poller sees,
and the returning agent's burst is what wakes the next cycle.

The whole interface is optional, and `ATRUST_CLIENT_API=0` says so: the daemon then builds no
`ClientAPI`, starts no poller, reads no view and hands out no ticket - the data-plane-only supervisor
with one journal line to say it. Every shape above was measured out of the running client rather
than documented, so a client bump can move it with nothing to announce it; the code's answer is that
each use falls back (the probe decides, the window logs in, a refusal is a warning in the journal and
a `the ticket login: ...` in the recovery's own detail) and the deployment's answer is this switch,
instead of a downgrade of the image.

## Stopping the container

The Quadlet unit's stop comes down to `ExecStop=podman rm -f atrust` (systemd's own unit, generated
by Quadlet), which signals PID 1 - `atrustd` - and waits `[Container] StopTimeout=5`. The SIGTERM
handler only sets a `threading.Event`; the daemon's waits (`ATRUST_WATCH_INTERVAL`, the tunnel wait,
`ATRUST_VNC_WAIT`) wait on that event instead of sleeping, because CPython re-enters `time.sleep`
after a signal and the flag used to be read only after the whole cycle returned. A stop in the
steady `ONLINE` state is answered in about a second and a half - a second of it is the client's own
SIGTERM grace, see below; a stop inside a cycle waits for the step it is in (a UI step, a probe
retry) - seconds, not minutes. The event poller is not joined either: its worst case is one bounded
long poll, the stop event ends its loop and the process exit takes the daemon thread - measured with
the poller running, `client stop took 1.60s` and the container died 1.67 s after the signal.

On the way out the daemon sweeps the client: `aTrustXtunnel-64` (which detaches and reparents to
PID 1, so no parent-based cleanup reaches it), its watchdog child, the agents and the trays. SIGTERM
first, then SIGKILL for what is still there - the tunnel, the trays and the client's own restarts
leave on SIGTERM, the Electron children and the plugin daemon do not. Matching is by the binary's
path (a `pkill -f` pattern): `pkill -x` compares the command *name*, which the kernel truncates to
15 characters, so the name of the tunnel binary is `aTrustXtunnel-6` there. The tray-only
`tokens.stop_client()` on the token-refresh path is deliberately not this sweep: a refresh must keep
the agent and the tunnel up while the tray reloads the new cookies.

What the sweep kills leaves corpses under PID 1 - `atrustd` itself: a dying process hands its
children to PID 1 (a dead tray's Electron helpers, a dead agent's plugins, a dead tunnel's
watchdog), and the detached tunnel is PID 1's own child already. Nothing calls `waitpid` for them,
so they stay in the task list as zombies. Each only holds a task slot, but that slot counts against
podman's pids limit (2048 by default), and a container left running long enough could fill the
limit with dead entries until the client family cannot come back. `reap_orphans()`
(`os.waitpid(-1, WNOHANG)` in a loop) runs at the top of every cycle and once more right after the
final sweep. It is an explicit call rather than a `SIGCHLD` handler: the engine's own
`subprocess.run` calls (`ip`, `xdotool`, `xwd`) wait for their exit statuses themselves and a
handler would steal them.

Measured 2026-10-11 in throwaway containers with the real client family (fresh profile, the forced
sweep being SIGTERM then SIGKILL over the three `CLIENT_FAMILY` patterns): without the reaper the
sweep left 18 zombies under PID 1 after 3 s and 20 after 33 s, and they never left - the live
container on that image showed 2 after 18 minutes of running; with it, the same sweep was clean
within a cycle (`reaped 13 orphan(s)` in the journal, 0 defunct at the next cycle's top) and the
stop path collected the 10 its own final sweep left (`client stop took 1.28s` then
`reaped 10 orphan(s)`).

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
| `libmmkv.so: cannot enable executable stack as shared object requires: Invalid argument`, wrapped in `UnhandledPromiseRejectionWarning` | ~18x, once per login | the client's history-address store: `resources/bin/libmmkv.so` declares `PT_GNU_STACK` **RWE**, and glibc 2.41 (Debian 13; the host's 2.44 behaves the same) no longer makes the stack executable for `dlopen`. The kernel still allows an exec stack - `mprotect(PROT_READ\|PROT_WRITE\|PROT_EXEC)` on `[stack]` returns 0 on 7.2.9-cachyos - so this is the loader's policy, not the container. What degraded on this base was the client's own address memory: with no store, every window opened on "Connection Options" and the address had to be typed in. The image now clears that bit in the client-image build; in the container it is the only fix needed - on a normal host, clearing it exposes the second defect right behind it (the first use of the client's sqlite store segfaults inside the bundled SQLCipher: `resources/bin/libsqlite3.so`'s `sqlcipher_activate` -> `sqlcipher_malloc` calls a NULL provider function under `SdpDatabase::initDatabase` in `libSpaProvider.so`, because Electron brings in the system SQLite) - but no client process in the container ever maps the system `libsqlite3.so.0`, so that path does not arise here; "The client's own store" below has the measurements |
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
the fixes (a unit drop-in, a launcher preload and a one-byte `prepare()` patch); the container hits
only the third, which the image now applies (see below):

| symptom | cause | fix |
|---|---|---|
| `aTrustDaemon` SIGSEGVs every ~35 s (`X509_VERIFY_PARAM_set_depth` through `libNetwork.so`) | the system `libQt5Network` -> `libproxy` -> `libcurl.so.4` (OpenSSL 3) enters the daemon *before* the bundled `libcurl.so`, and the client's curl references carry no symbol versions (`objdump -T libNetwork.so`), so they bind to the system one - whose OpenSSL 3 object then reaches the client's OpenSSL 1.1 SSL callback | preload the bundled curl into the unit: `Environment=LD_PRELOAD=.../resources/bin/libcurl.so`; libproxy's `CURL_OPENSSL_4` reference still resolves to the system curl |
| pressing next after entering the address SIGSEGVs the tray in `sqlcipher_activate` | Electron brings the system `libsqlite3.so.0` into the tray, beside the bundled SQLCipher (`resources/bin/libsqlite3.so`), and the two SQLites' `sqlite3_*`/provider state collide | preload the bundled one in the tray's launcher: `LD_PRELOAD=$APP/resources/bin/libsqlite3.so` (SQLite 3.31.0, enough for Electron 9) |
| the address list never persists | `resources/bin/libmmkv.so` declares `PT_GNU_STACK` **RWE**; glibc 2.41+ refuses that `dlopen` | `patchelf --clear-execstack` in the package build (1 byte) |

With all three: `SdpMmkv` creates `.../database/SdpcHistory`, entering an address no longer crashes
the tray, and the history survives a restart (verified on the host 2026-10-10).

In the container only the third one applies, and it is the one that matters. Measured on the
published image in a throwaway container (2026-10-10): the base has no system `libcurl.so.4` and no
`libproxy`, and `aTrustAgent` already maps the bundled `resources/bin/libcurl.so` through the
`LD_LIBRARY_PATH` `vpn-config.sh` sets, so that daemon defect cannot occur here; the system
`libsqlite3.so.0` is mapped by nothing but `atrustd`'s own Python, never by a client process, so the
tray's SQLCipher collision cannot occur either. Clearing the one flag (the ELF edit above, done at
runtime inside the probe) took the store from dead to working: `[addHistory] end`,
`database/SdpcHistory` written, `getHistoryAddr` returns the address seeded into `addr.conf`, and the
connection page's address box renders it instead of the placeholder - so a fresh container would seed
its own remembered address at every start and a human in VNC would find the field filled. Two things
the change brings: the store sits at `/usr/share/sangfor/.aTrust/database/SdpcHistory`, in the
container layer outside the mounted profile, so a recreated container starts empty again (the seed in
`run_daemon` restores it, which is also why a changed `ATRUST_PORTAL_URL` cannot leave a stale address
behind - nothing outlives the container); and the submit path's portal half was not exercised
offline, so a live cycle after the change is the acceptance.

The image now clears the flag in the client-image build (`base/Containerfile`: `patchelf
--clear-execstack` on the client's `resources/bin/libmmkv.so`, patchelf purged again, and an
assertion that the object no longer requests an executable stack - `base/README.md`). The live
acceptance of 2026-10-11 (container recreated on the changed image) shows the whole chain, and it ends
on the login page without `uiauto` touching the address: `loading [SdpcHistory] with 1 key-values`,
`getHistoryAddr` returning the portal, `WebDirManager defaultSdpcAddr: <portal>`, the router guard's
`auto connect on enter router guard` and `final route:login`, then the supervisor's
`client window: submitted: credentials submitted [page=login]` with no `the client asks for the portal
address` line at all, and `LOGGED_OUT -> ONLINE (tunnel up after the client login)` five seconds
later.

The store is also what has to go when the client's memory must be dropped. Force the address page by
stopping the client family first, then removing `database/SdpcHistory`, `database/SdpcHistory.crc`
and `var/conf/addr.conf`: a running client flushes the store back, and deleting only the store is not
enough either, because the next start re-imports `addr.conf`. Measured 2026-10-11 in a throwaway
container of the changed image: with both files gone the store loads with 0 key-values,
`getHistoryAddr` returns empty and `defaultSdpcAddr` is `undefined` again, i.e. the client asks for
the address.

A changed `ATRUST_PORTAL_URL` is the case that needs none of it, measured on the live deployment
2026-10-13. The store lives in the container's own layer - `/usr/share/sangfor/.aTrust` is a real
directory of the container's filesystem (device 71, inode 31427510) while the mounted profile is the
host's (device 51, inode 27717281) - so the container the unit's stop removes takes the store with
it: a container created after its predecessor had written the portal address loaded `[SdpcHistory]
with 0 key-values`, and the address it got was the one `run_daemon` had just seeded into `addr.conf`.
With the URL changed, that container's `queryHistory` was again `[]`, its `addHistoryAddr` and the
window's own `defaultSdpcAddr` both carried the *new* address, and the tunnel stayed down while the
engine failed against it (`GET /passport/v1/public/authConfig failed`); restoring the URL and
restarting carried the real address back the same way, `LOGGED_OUT -> ONLINE` in 13 s. Nothing can
leave the client on the old address while the engine talks to the new one: the engine's URL is fixed
at container creation, and a start that keeps the container (`podman restart atrust` by hand) keeps
the layer *and* the creation-time environment - measured: a marker file in the layer survived the
restart and `printenv ATRUST_PORTAL_URL` was still the value the container was created with - so a
changed URL is always a container recreation, and a recreation always starts without a store. The
manual reset above is for dropping the client's memory inside a container that keeps running.
