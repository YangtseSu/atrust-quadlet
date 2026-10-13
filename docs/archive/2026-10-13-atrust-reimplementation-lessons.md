<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B07 — Lessons from the aTrust reimplementations

> **Retired 2026-10-13.** The accepted candidates were promoted to numbered steps - **21** (the
> answer classes and the retry gate), **22** (a bump's evidence: the bundle and the peer
> certificate), **23** (the state directory and a changed portal), **24** (the page name in the hint
> and the README paragraphs), **25** (the engine's own session, kept warm) - and the declined ones
> stay declined here. Kept as the survey behind them: its citations, its two live readings and the
> order of the work. The live plan is [`../plans/`](../plans/).

Status: ⏹ retired 2026-10-13 — its candidates were promoted to steps 21-25; the record is below
Depends on: — (a read of two upstream projects on 2026-10-13, pinned to the revisions below; the
review entry in the `## Progress log` adds this deployment's first readings, two of them live)
Touches: — (per item)
(the `- ⬜` markers below are the record of the survey: the work itself is in steps 21-25, see the map
at the end)

The two sources, cited by permalink because a path and its line numbers drift with every upstream
commit:

* [`Mythologyli/zju-connect`](https://github.com/Mythologyli/zju-connect) @
  [`c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63`](https://github.com/Mythologyli/zju-connect/tree/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63)
  (Go, AGPL-3.0) — a full reimplementation of the client side of both Sangfor protocols.
* [`chenx-dust/EZ4Connect`](https://github.com/chenx-dust/EZ4Connect) @
  [`c56e1673efa1c3c41f18c51092a05d9e7d8298a0`](https://github.com/chenx-dust/EZ4Connect/tree/c56e1673efa1c3c41f18c51092a05d9e7d8298a0)
  (Qt6/C++, GPL-3.0) — a GUI shell *around* the same Go core: it spawns the bundled
  `zju-connect`/`zju-connect.exe` binary next to the app
  ([`infrastructure/coreprocess/coreexecutable.cpp#L13`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/coreexecutable.cpp#L13)),
  so it is not a second opinion on the protocol; its value here is the layer it built around it
  (auth discovery, prompt classification, device-data lifecycle, reconnect policy).

## Scope (recorded 2026-10-13)

**aTrust only, no legacy EasyConnect.** The project owner's direction for this step: everything below
concerns the aTrust client and its JSON portal. `zju-connect` keeps two protocol backends behind one
`client.Client` interface ([`client/client.go`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/client.go));
its **EasyConnect** backend — the xml `/por/*.csp` portal, the `update_session.csp` idle keepalive, the
RC4/TLS 1.1 `HelloCustom` tunnel that smuggles the tunnel type into the TLS SessionId, the svpnservice
command decode, the click-coordinate captcha
([`client/easyconnect/request.go`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/easyconnect/request.go),
[`client/easyconnect/protocol.go`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/easyconnect/protocol.go))
— describes a protocol this project does not speak and will never speak. Only `client/atrust/**`
(`/passport/v1/**` + `/controller/v1/**`) is comparable to `atrustd/portal.py`, and that is the half
every lesson below comes from.

## The candidates

- ⬜ **A typed code table for the portal and the agent.** `portal.py` classifies by message text
  (`CAPTCHA_HINTS`) and two codes (`LOGGED_OUT_CODES = {75500002, 75500001}`); the agent's refusals are
  read as strings in the journal (`75500304 当前票据已失效`, `11119054 已经登录成功`). `zju-connect`
  treats the same family as typed sentinels — session-death codes `10000004`/`75500002`
  ([`auth/request.go#L114-L117`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/request.go#L114-L117)),
  stale `antiReplayRand` → `75500000`
  ([`auth/psw.go#L122-L124`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/psw.go#L122-L124))
  — and *decides* differently per class;
  `EZ4Connect` pins the same idea as one tested table
  ([`coreoutputparser.cpp#L5-L81`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/coreoutputparser.cpp#L5-L81)
  + [`tests/coreoutputparser_test.cpp#L24-L38`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/tests/coreoutputparser_test.cpp#L24-L38)).
  Proposal: one `CODE_CLASS` table (`session-invalid`, `already-online`, `stale-ticket`, `captcha`,
  `wrong-password`, `rate-limited`) with the unit tests `tests/test_portal.py` already has the shape
  for, and the supervisor reading the class instead of re-deriving meaning from a message string.
  Effort low, risk low — the strings are Chinese and the portal can reword them; the codes have not
  moved since 2026-10-11. Verify: recorded codes through the table offline; one live cycle per class
  where a class can be provoked safely (a stale ticket is already provoked on purpose).

- ⬜ **Govern the re-login storm by class.** The portal counts password attempts and says so in the
  login failure row (`The username or password is incorrect. You still have N attempts left`,
  recorded in `docs/archive/2026-10-10-ROADMAP.md`), and `EZ4Connect` surfaces the family's
  brute-force answer (`You are trying brute-force login on this IP address.`
  [`coreoutputparser.cpp#L59-L61`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/coreoutputparser.cpp#L59-L61))
  as a state that stops auto-reconnect entirely
  ([`core/connectionsessionstate.cpp#L111-L114`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/core/connectionsessionstate.cpp#L111-L114):
  only `AUTH_EXPIRED` and `OTHER` are reconnectable, every other exit class ends the session).
  Today a wrong password in the env file burns attempts until `logins_before_vnc` (2) hands the
  session to VNC, and every cycle after that re-tries on the exponential backoff. Proposal: a
  wrong-password or rate-limited class ends the retry loop in `NEED_VNC` with the portal's own counter
  in the hint, and the backoff gains jitter. Effort low, risk low. Verify offline with scripted
  refusals; live with a deliberately wrong password in a throwaway container — the journal must name
  the remaining-attempts row, and the portal must see no more than the attempts the human spent.

- ⬜ **A support bundle.** Both projects ship one: `zju-connect` has `-debug-pcap-file` (a
  reconstructed underlay capture) and `-debug-tls-log-file` (NSS keylog), both documented
  secret-bearing and written 0600 (its `README.md`,
  [`internal/keylog`](https://github.com/Mythologyli/zju-connect/tree/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/internal/keylog),
  [`underlay/pcap.go`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/underlay/pcap.go));
  `EZ4Connect` exposes the same pair through the profile
  ([`corecommandbuilder.cpp#L230-L231`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/corecommandbuilder.cpp#L230-L231),
  [`applicationpaths.cpp#L78-L95`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/storage/applicationpaths.cpp#L78-L95)).
  We cannot pcap the client's userspace netstack, but everything a bump regression needs is already on
  disk: `state.json`, the `NEED_VNC` hint and captcha, the client's own log dir
  (`ATRUST_CLIENT_LOG_DIR`), `addr.conf`, `/v1/service/status` with the client's version, and the
  probe's route table. Proposal: `atrustd --bundle` writes one timestamped tarball into
  `ATRUST_STATE_DIR` (0600) collecting those, plus the container's client version
  (`/etc/atrust-version`, written by `base/Containerfile`) and the base reference the app image was
  built from - today only the build argument `BASE_IMAGE` carries it and no image label or file
  inside the image does, so the bundle records that fact rather than inventing one. Effort low, risk
  low. Verify: run it on the live container, read the bundle back, assert no credential, token or
  portal hostname beyond the deployment's own is in it (the repository is public — the same scrub
  the design's log quotes use).

- ⬜ **Say who the portal is talking to.** `portal.py` runs the whole session with
  `check_hostname = False, verify_mode = CERT_NONE` when `insecure` is set (it is, by default,
  `portal.py:176-178`) — the portal's certificate is never looked at by this engine at all.
  `zju-connect` refuses PKI for the same reason (internal CAs) but pins what the *portal itself*
  publishes: `verifySangforCertificateIdentity` compares each peer certificate's digest against the
  `rsaCert`/`sm2encCert` digests from `authConfig`, the digest being
  `SHA-256(base64(DER) + "@~*&!()-")`
  ([`auth/anti_mitm.go#L233-L258`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/anti_mitm.go#L233-L258),
  constant at [`#L23`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/anti_mitm.go#L23))
  — and, like the official clients, logs-and-ignores a failure
  ([`auth/request.go#L130-L135`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/request.go#L130-L135)).
  Proposal: log the peer cert fingerprint beside every login at debug level, and compare it against the
  cert `authConfig` publishes when that field is present, reporting a mismatch as a warning rather
  than a refusal — on this deployment the data *is* present (`antiMITMAttackData` with `enable: 0`
  beside both certificates, read live 2026-10-13), so the comparison has something to compare and the
  fingerprint line is the half that always logs. Effort low, risk low (a hard refusal would break
  internal-CA deployments; a warning does not). Verify offline against a recorded `authConfig` pair
  (matching and mismatching), one live login for the log line.

- ⬜ **Pin and document the device identity the way the ports of this family do.** `zju-connect`
  persists `deviceId = lower(randHex(32))`, cookies and `server_version_info` in
  `client_data.json`, mode 0600 (`signKey` is generated per setup and never persisted), and reuses
  them to skip login entirely
  ([`client/atrust/client.go#L269-L271`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/client.go#L269-L271)
  for the id, [`#L109-L112`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/client.go#L109-L112)
  for the resume check, [`main.go#L181-L184`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/main.go#L181-L184)
  for the 0600 write);
  it reports the pair to the portal as `POST /controller/v1/public/reportEnv(ticket, deviceId)`.
  `EZ4Connect` goes further and *invalidates* the stored device data whenever server, port, protocol,
  auth type, login domain or login URL changes
  ([`presentation/main/mainwindow.cpp#L826-L838`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/presentation/main/mainwindow.cpp#L826-L838)),
  with `-trust-device`/`-untrust-device` as the explicit path
  ([`devicetrust.cpp#L30-L57`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/devicetrust.cpp#L30-L57)).
  Ours: the engine's id is ours to pin (`ATRUST_DEVICE_ID`, persisted in
  `$ATRUST_STATE_DIR/device-id`), while the *client's* `sdpcguid` is derived at runtime and — measured
  2026-10-11 — is the same in every container of the image on a host. Proposal: document in `README.md`
  what is measured (the guid is one per image and host, so a portal that binds a terminal grant to it
  sees every container there as the same terminal) and keep the grant's own binding marked as the
  inference it still is - no portal on this deployment grants one, so nothing here measured it.
  Effort low, risk none. Verify: the README paragraph against the guid measurement it quotes; the
  file modes the original text wanted checked are measured (2026-10-13, `ls -l` on the host mount:
  `device-id` 0600, `state.json`/`apps.json` 0644) and became the candidate added below.

- ⬜ **Two documentation notes the two sources documented.**
  (a) A host-side TUN proxy (Clash and friends) that captures the portal's own traffic loops back into
  the container: `EZ4Connect` documents the bypass rules
  ([`docs/ADVANCED_USAGE.md`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/docs/ADVANCED_USAGE.md):
  the campus domains in `fake-ip-filter`, the campus CIDR never in `route-exclude-address`,
  `-bind-interface`/`-auto-detect-interface`), `zju-connect` says the same for its own host
  ([`docs/service.md`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/docs/service.md):
  the portal host must be direct, `10.0.0.0/8` out of the LAN/direct list). Our README's Zero Omega
  paragraph covers the browser half only — add the mirror case (the portal host and the intranet ranges
  on the host proxy's direct list). Effort low, risk none.
  (b) `ATRUST_PROBE_DISCOVER=0` sends no traffic at all (`README.md`), and the portal expires a quiet
  tunnel — measured on this project 2026-10-09: 10.3 minutes with `CONNECT`s only, over an hour with
  real requests (`docs/DESIGN.md`). That combination is a session that expires by configuration; the
  row should say so beside the switch.
  (c) `zju-connect` re-checks its aTrust session every `SessionRefreshInterval` = 1800 s and re-probes
  its best node every 300 s — the defaults are in
  [`configs/config.go#L86-L87`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/configs/config.go#L86-L87)
  (not in `session.go`, which holds the loop that uses the first,
  [`client/atrust/session.go#L25-L64`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/session.go#L25-L64))
  — the protocol has its own refresh cadence beside its 5 s/3-miss heartbeat
  ([`client/atrust/l3tunnelconn.go#L36-L46`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/l3tunnelconn.go#L36-L46)).
  Nothing to build for the tunnel: our probe is the keepalive there (measured), and the client's own
  heartbeat runs inside the client. The review of 2026-10-13 splits the record: this covers the
  *tunnel's* session and nothing else - the engine's own *web* session (the cookies `ticketExchange`
  needs) has no keepalive, which is the separate candidate added below. Recorded so the numbers are
  not re-derived.

- ⬜ **Consider an in-band TOTP step, with the captcha caveat.** `zju-connect`'s aTrust auth chain has
  discrete steps for the second factor — `auth/sms`, `auth/customSms`, `auth/totp`, `auth/radius`,
  `auth/challenge` → `auth/token`, then `preEnhancedAuth`/`enhancedConfirm`/`enhancedDone`
  ([`client/atrust/auth/`](https://github.com/Mythologyli/zju-connect/tree/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth))
  — i.e. the portal can carry the factor inside the JSON login this project already implements, and
  `atrustd/totp.py` can already produce the code. The deployment this project is measured against
  rejects the password login without the graphical captcha (`graphCheckCodeEnable: 1`,
  `docs/DESIGN.md`), so the in-band path would stop at the captcha there and change nothing; on a
  portal without it, the factor could run without a human. Proposal: keep the VNC hand-over as the
  policy (unchanged) and record this as the shape a future opt-in would take. Effort unknown, risk
  medium (an automated second factor is a policy decision, not a code one). The review of 2026-10-13
  turns this bullet into a pointer rather than work of its own: the chain's shape is measured now -
  `nextService` drives it, up to eight steps, each step's endpoint named in
  [`auth/auth.go#L245-L281`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/auth.go#L245-L281)
  (`auth/sms`, `auth/totp`, `auth/radius`, `auth/challenge` → `auth/token`,
  `preEnhancedAuth`/`enhancedConfirm`/`enhancedDone`, `auth/bindAuthDevice`), which is exactly the
  vocabulary step 05's capture recipe should expect from the portal's own answer.

### Added by the review of 2026-10-13

- ⬜ **Keep the engine's own portal session warm.** The engine's cookies live in one process's memory,
  and the steady `ONLINE` cycle touches the portal not at all, so its session goes cold while the
  tunnel is healthy; the next recovery then pays the fresh login, the `tid`/`tid.sig` write and the
  tray's own stop - measured once at 31 s end to end against 5.3 s with the session still alive
  (`docs/plans/14-api-login-path.md`). `zju-connect` keeps the same kind of session alive by
  refreshing it every `SessionRefreshInterval` = 1800 s - a
  `GET /passport/v1/public/authConfig?needTicket=0` whose `data.isLogin` is the validity check, the
  refreshed cookies written back to its own state file
  ([`configs/config.go#L86-L87`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/configs/config.go#L86-L87),
  [`auth/refresh.go#L39-L43`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/refresh.go#L39-L43),
  [`client/atrust/session.go#L25-L64`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/session.go#L25-L64))
  - while `ErrSessionInvalid` is fatal there. Proposal: measure how long the engine's session
  survives an idle `ONLINE` run and whether one cheap read extends it, then add that read on a slow
  cadence if it does; the data plane keeps deciding everything else. Effort low, risk low. Verify: a
  recovery after hours of `ONLINE` walks the ticket path with no `password auth ok` line, and the
  journal shows the refresh calls in between.

- ⬜ **Let the client's own log name the page.** The tray log already carries the SPA's own console -
  `getHistoryAddr`, `final route:login`, the `checkCode` request `uiauto` reads for its captcha
  marker (`docs/DESIGN.md`) - and the second-factor pages have names of their own (`totpAuth`,
  `smsAuth`, `page_auth_trust_terminal`). `EZ4Connect` classifies the analogous line stream into
  typed events and shows the human which prompt it is
  ([`coreoutputparser.cpp#L5-L81`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/coreoutputparser.cpp#L5-L81)).
  Proposal: the `NEED_VNC` reason and the state detail carry the last page/route token the tail
  published, best-effort beside the captcha marker; a tail that does not end on a newline is re-read
  with a small overlap, so a marker split by the writer is not lost. Effort low, risk low (a format
  drift degrades to today's text). Verify: the classifier over recorded log tails offline, one live
  hand-over whose hint names the page.

- ⬜ **The state directory's own files are 0600.** `device-id` is written 0600
  (`portal.py::_keep_device_id`) while `state.json`, `apps.json` and the `NEED_VNC` hint are 0644 -
  and `state.json` carries the account name - on the host mount, so every local user of the host
  reads them (measured 2026-10-13, `ls -l ~/.atrust-data/run`). Proposal: `state.py` writes its
  files (the atomic temp file included) 0600. Effort trivial, risk none. Verify: the state-file
  tests plus `ls -l` on the live mount after a cycle.

- ⬜ **A changed `ATRUST_PORTAL_URL` invalidates the client's address memory.** `EZ4Connect` clears
  its stored client data whenever server, port, protocol, auth type or login URL changes
  ([`mainwindow.cpp#L826-L838`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/presentation/main/mainwindow.cpp#L826-L838)).
  Ours: a recreated container starts clean, but a plain `restart` with a changed URL keeps the
  client's `SdpcHistory` store on the old address (it lives in the container's layer, outside the
  mounted profile) while the engine talks to the new portal - which side the window uses is
  unmeasured. Proposal: measure that case first (change the URL on the live container,
  `systemctl --user restart atrust`, read what the client's window opens on), then, if the store
  wins, record the portal in `ATRUST_STATE_DIR` and run the documented reset on a mismatch before
  the client's own start loop brings it back (`docs/DESIGN.md`, "The client's own store, and what it
  takes to fix it"). Effort low, risk low (the branch runs only on a changed URL). Verify: the case
  above, then the same case showing the new address and `LOGGED_OUT -> ONLINE`.

## Order of the work (review of 2026-10-13)

Every upstream citation was re-read against the pinned checkouts in this review: they hold, with the
four corrections applied above (the two cadences live in `configs/config.go`, `signKey` is not
persisted, the anti-MITM JSON field is `sm2encCert`, and the client version is a file in the image,
not a label). Three things were read off this deployment: the portal's `authConfig` carries
`antiMITMAttackData` (`enable: 0`, with `rsaCert` and `sm2encCert` present, so the D item has
something to compare against), the state mount's file modes (the 0600 item above), and - through
`zju-connect`'s login code - that `graphCheckCodeEnable` is a *field* of the `auth/psw` response
data ([`auth/psw.go#L99-L111`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/psw.go#L99-L111)),
which is the language-independent captcha signal item A should read ahead of `CAPTCHA_HINTS`: the
same demand reached the client's own log in English (`The characters has expired. Please try
again`, `docs/plans/04-need-vnc-reverification.md`), and no entry of `CAPTCHA_HINTS` matches that
string. The same drill is the caveat on B's live half: its one decrement of the portal's counter
(10 → 9) came *after* the human answered the captcha, so on a captcha portal a wrong password is not
counted - and not observable - until a human is in the loop, which is why that verification needs a
portal without the graphical captcha.

| Item | Verdict | In one line |
|---|---|---|
| A, the typed code table | do first | it is what the login decisions below read, and two of its signals are already measured (`graphCheckCodeEnable`, and the codes `75500000`, `75500002`, `75500006`, `11119054`, `75500304`) |
| B, the re-login storm | do | the only candidate with a safety argument - the account's own attempts; on a captcha portal its live half cannot run (the password is not checked until a human answers the captcha) |
| F(b), the `ATRUST_PROBE_DISCOVER=0` row | do | one README row plus a startup warning; the switch's combination is a session that expires by configuration |
| F(a), the host-proxy bypass | do | docs only, and it is the missing half of an existing README paragraph |
| C, the support bundle | do | keep a log *tail*, not the log directory (B02: ~0.2 GB/day), and leave `device-id` out |
| E, the device identity | do, rewritten | the measurement it needed exists (the shared guid); the grant's own binding stays an inference |
| the 0600 files | do | measured, one file in `state.py` |
| the page name in the hint | do | small, and it improves every hand-over |
| the portal-change invalidation | measure, then do | the fix is cheap; which side of the address memory wins is not known |
| the keep-warm refresh | measure first | the prize is 31 s → 5.3 s on a recovery, but only if a read extends the session |
| D, the peer certificate | do last | while TLS is off by default the comparison is a log-only tripwire; the fingerprint line is the useful half |
| F(c), the cadence record | keep as a note | no code |
| G, in-band TOTP | merge into step 05 | the chain's shape is known (`nextService`), the policy is unchanged |

## Where the work went (2026-10-13)

| Candidate | Step |
|---|---|
| A, the typed code table | [21](../plans/21-typed-login-answers.md) |
| B, the re-login storm | [21](../plans/21-typed-login-answers.md) |
| C, the support bundle | [22](../plans/22-bump-evidence.md) |
| D, the peer certificate | [22](../plans/22-bump-evidence.md) |
| E, the device identity | [24](../plans/24-what-the-human-is-told.md) |
| F(a), the host-proxy bypass | [24](../plans/24-what-the-human-is-told.md) |
| F(b), the `ATRUST_PROBE_DISCOVER=0` row | [24](../plans/24-what-the-human-is-told.md) |
| F(c), the cadence record | stays a note (no step; the numbers are in `docs/DESIGN.md`) |
| G, in-band TOTP | [05](../plans/05-second-factor-otp.md)'s capture recipe |
| the keep-warm refresh | [25](../plans/25-session-keepalive.md) |
| the page name in the hint | [24](../plans/24-what-the-human-is-told.md) |
| the 0600 files | [23](../plans/23-state-directory-and-a-changed-portal.md) |
| the portal-change invalidation | [23](../plans/23-state-directory-and-a-changed-portal.md) |

## Declined, with the reason

- **Fail fast and let systemd recover** (`zju-connect` has no in-process supervisor: an unrecoverable
  session is a fatal error → process exit, recovery is `Restart=on-failure`/`RestartSec=5s`,
  [`docs/service.md`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/docs/service.md)).
  A client restart here costs ~30 s to `ONLINE` and loses the X desktop, while the ticket path recovers
  the same session in 5.4 s (`docs/plans/17-skip-restart-on-a-client-side-logout.md`). The
  exit-and-restart loop is the cheaper design only where the process is cheap to start; it is not here.
- **Reimplement the protocol** (TCP-tunnel mode, fake-IP split DNS, gVisor stack). Both projects are
  full protocol clients; this project's charter is the opposite (`docs/ROADMAP.md`, "Not doing"). The
  items above are the ones that survive the charter.
- **The EasyConnect legacy half of both projects** (xml portal, `update_session.csp`, the RC4 tunnel,
  the click-coordinate captcha, the svpnservice command decode). Out of scope: aTrust only.
- **Hard-fail on a certificate mismatch.** The official clients log-and-ignore (mirrored in
  [`anti_mitm.go`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/anti_mitm.go));
  a hard rule here would break internal-CA portals the `insecure` switch exists for.

## Progress log

* 2026-10-13 — opened from the read of `Mythologyli/zju-connect` (aTrust backend via `client/atrust/**`,
  Go, AGPL-3.0, read at `c19eb4e`) and `chenx-dust/EZ4Connect` (Qt6 shell over the same core,
  GPL-3.0, read at `c56e167`). Scoped to aTrust on the owner's direction; the EasyConnect legacy half
  is recorded here once, as out of scope, so a later reader does not re-derive it. Citations are
  permalinks to those two revisions: the owner's rule is that a local checkout is not the project, and
  a path plus its line numbers drift with the next upstream commit. The candidates above are findings
  only — nothing is measured on this project's own deployment, each carries its verification, and the
  two documentation notes are already actionable without a live session.
* 2026-10-13 — reviewed against both checkouts (still at the pinned revisions) and against this
  deployment's own container. Every citation holds; four were corrected in place (the two cadences
  are `configs/config.go#L86-L87`, not `session.go`; `signKey` is generated per setup and never
  persisted; the anti-MITM JSON field is `sm2encCert`; the support bundle's client version is
  `/etc/atrust-version` - no image label carries it, and the base reference exists only as a build
  argument). Two live readings, both above: the portal's `authConfig` carries `antiMITMAttackData`
  with `enable: 0` beside `rsaCert` and `sm2encCert`, so item D has something to compare against when
  it lands; and the host mount holds `state.json`/`apps.json` at 0644 beside a 0600 `device-id`,
  which became the 0600 candidate. A third finding came out of the login code: `graphCheckCodeEnable`
  is a field of the `auth/psw` data (`auth/psw.go#L99-L111`, where `zju-connect` returns it instead
  of an error), and the same captcha demand reached the client's own log in English - no
  `CAPTCHA_HINTS` entry matches that string - so item A should read the field first and the messages
  second. Four candidates were added (keep-warm, page name, file modes, portal-change invalidation),
  the order table was written, and G is now a pointer into step 05's capture recipe. Nothing was
  implemented in this review; the `- ⬜` list otherwise stands as it was.
* 2026-10-13 — retired to the archive when the accepted candidates were split into steps: the map
  above says which candidate went where, the declined rulings stay here as they are, and nothing is
  left to do in this file. The survey's own exit line moves with the work - 21 closes it for the
  wrong-password code, 22 for the bundle and the fingerprint, 23 for the changed-URL answer, 24 for
  the hand-over's page name, 25 for the session's lifetime. The file was `B07` while it lived in
  `docs/plans/`; the items' markers and the review's numbers are kept verbatim.
