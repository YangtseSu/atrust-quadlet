<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step B07 — Lessons from the aTrust reimplementations (backlog)

Status: ⏸ backlog
Depends on: — (a read of two upstream projects on 2026-10-13, pinned to the revisions below; nothing
in this file is measured on this project's own deployment)
Touches: — (per item)
(each `- ⬜` item below is one commit)

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
  `ATRUST_STATE_DIR` (0600) collecting those, plus the container's client version from the image label
  and the base ref from `base/ref.sh`. Effort low, risk low. Verify: run it on the live container, read
  the bundle back, assert no credential, token or portal hostname beyond the deployment's own is in it
  (the repository is public — the same scrub the design's log quotes use).

- ⬜ **Say who the portal is talking to.** `portal.py` runs the whole session with
  `check_hostname = False, verify_mode = CERT_NONE` when `insecure` is set (it is, by default,
  `portal.py:174-178`) — the portal's certificate is never looked at by this engine at all.
  `zju-connect` refuses PKI for the same reason (internal CAs) but pins what the *portal itself*
  publishes: `verifySangforCertificateIdentity` compares each peer certificate's digest against the
  `rsaCert`/`sm2EncCert` digests from `authConfig`, the digest being
  `SHA-256(base64(DER) + "@~*&!()-")`
  ([`auth/anti_mitm.go#L233-L258`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/anti_mitm.go#L233-L258),
  constant at [`#L23`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/anti_mitm.go#L23))
  — and, like the official clients, logs-and-ignores a failure
  ([`auth/request.go#L130-L135`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/request.go#L130-L135)).
  Proposal: log the peer cert fingerprint beside every login at debug level, and compare it against the
  cert `authConfig` publishes when that field is present, reporting a mismatch as a warning rather than
  a refusal. Effort low, risk low (a hard refusal would break internal-CA deployments; a warning does
  not). Verify offline against a recorded `authConfig` pair (matching and mismatching), one live login
  for the log line.

- ⬜ **Pin and document the device identity the way the ports of this family do.** `zju-connect`
  persists `deviceId = lower(randHex(32))`, `signKey`, cookies and `server_version_info` in
  `client_data.json`, mode 0600, and reuses them to skip login entirely
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
  that a portal's "trust this terminal" grant binds to the client's guid (so it survives a recreation
  but is shared by every container built from the image), and check that the state dir and the client's
  cookie store are 0600 on a fresh install. Effort low, risk low. Verify:
  `podman exec atrust ls -l ~/.atrust-data/run ~/.aTrust/AppCache`.

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
  its best node every 300 s
  ([`client/atrust/session.go#L40-L43`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/session.go#L40-L43))
  — the protocol has its own refresh cadence beside its 5 s/3-miss heartbeat
  ([`client/atrust/l3tunnelconn.go#L36-L46`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/l3tunnelconn.go#L36-L46)).
  Nothing to build: our probe is the keepalive here (measured), and the client's own heartbeat runs
  inside the client. Recorded so the numbers are not re-derived.

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
  medium (an automated second factor is a policy decision, not a code one).

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
