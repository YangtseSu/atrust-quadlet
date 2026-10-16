<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 16 — The agent's API reachable from the host

Status: ⛔ blocked
Depends on: — (the measurements are in `docs/CLIENT-LOCAL-API.md`, "Reaching it from the host"); the
remaining item is the strict hand-over drill (tunnel down -> a human's web login -> tunnel up), which
needs a person for the captcha and a supervisor that is not recovering the session first
Touches: `base/overlay/start.sh`, `quadlet/atrust.container`, `README.md`, `docs/CLIENT-LOCAL-API.md`,
`docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

The client's loopback service is the interface its own web workbench speaks, and the workbench is
served by the *portal* - so a browser on the host that can reach the service can drive the client the
way the vendor intended: log in on the portal page, the page hands the session to the client, the
tunnel comes up. That path needs no VNC for a captcha, no X11 driving, and no engine: it is the
human's own browser doing what this project's `NEED_VNC` hand-over asks them to do through a remote
screen.

Measured 2026-10-11 (recorded in the reference doc) and the reason this is a step rather than a
`PublishPort` line:

* a published port does **not** reach a loopback-bound service under `pasta`: the same server bound
  to `127.0.0.1` is unreachable from the host while the `0.0.0.0` bind is reachable, and a plain
  `socat` relay bound to `0.0.0.0` makes it work again;
* the image already runs such a relay for 54631 (`force_open_ports()`: `socat` on `0.0.0.0:20000` to
  `127.0.0.1:54631`) - but its companion iptables `REDIRECT 54631 -> 20000` is dead under `pasta`
  (instrumented: 0 packets), so publishing `54631` itself still fails while publishing `20000`
  reaches the agent (verified against a fresh container of the base image: `POST /v1/detect` →
  `detect successfully`).

## Deliverables

- ✅ Decide and write down the exposure: **`PublishPort=127.0.0.1:54642:20000`**, on by default in
  the unit, one drop-in to remove - the client's API has no authentication (`logout`, `offline`, the
  status and the event channel), so it stays on `127.0.0.1`; the *spare* host port is the decision's
  own evidence: the vendor's workbench races six addresses
  (`https://localhost.sangfor.com.cn:{54631,54642,54653}`, `https://127.0.0.1:{54630,54641,54652}`;
  in the image's `web/old/jssdk/common/config.js` and again in `web/assets/`), so any of them
  reaches the client, and the spares are the two families' only free ports when a native aTrust
  client on the host owns `54630`/`54631`. The container side stays the image's relay (`20000`),
  which no client port ever claims. Recorded in the unit's comment.
- ✅ `base/overlay/start.sh`: the relay is stated as what it is - the thing a published port has to
  target, because the client binds loopback only and pasta never delivers there - and the
  docker-era `REDIRECT` stays with the runtime that needs it named (docker's documented
  `-p $port:$port`; under pasta it is dead: the forwarded connection is generated inside the
  container's namespace and never traverses `PREROUTING`). The IP-form port (`54630`) gets no relay
  of its own, and that is recorded in the unit's comment: the workbench races all six addresses
  anyway, and a spare is what stays free beside a native client.
- ✅ The Quadlet unit publishes the mapping (previous commit) and `README.md` carries the host side
  in "The login in your browser": the `/etc/hosts` entry for `localhost.sangfor.com.cn`, the
  one-time certificate exception, why the port is a spare of the vendor's own probe list, what the
  exposure means (an unauthenticated API that can end the session), the drop-in that removes it, and
  the container side of the mapping (the relay).
- ✅ Verification, the machine half:
  - from the host, `POST https://127.0.0.1:54642/v1/detect` with the workbench's envelope answers
    `{"code":0,"message":"detect successfully","data":{"pubkey":""}}` on the live container (and the
    same through the domain form, `--resolve localhost.sangfor.com.cn:54642:127.0.0.1`);
  - `127.0.0.1:54642` is the only address the host-side bind carries, the gated
    `/v1/service/status` answers with the portal's own `Referer`, the certificate chain is the
    client's own (3 certs, DigiCert's names, nothing verifies it), and the cross-origin shape is
    known (allow-origin echoed; no preflight, because the SDK sends the agent calls header-less).
- ⛔ Verification, the human half - the portal's login page detecting the client is **seen** (a real
  browser on the host, 2026-10-16: the page's own six probes, one answer - ours on `54642` - then
  `/v1/service/init`, `/v1/service/status`, `/v1/aUem/*`, `/v1/update/status`, `/v1/base/printLog` all
  answering through that port, the portal's `sessionIdExchange` and `clientResource` completing the
  hand-over, and the workbench rendering this account's own app list - no password, no captcha, no
  VNC). What is still not seen is the strict form: the tunnel *down*, a human logging in on the
  portal page, the tunnel coming up - it needs a person for the captcha and a supervisor that is not
  racing them, so the step stays open for it.
- ✅ `docs/CLIENT-LOCAL-API.md`'s "Reaching it from the host" flips from "what fails and why" to what
  the deployment now does (the publish, the spare, the drop-in, the browser half), with the
  measurements kept as the reason and three of its own claims corrected by today's reading: the
  service's certificate is not self-signed (its own chain for the name, with DigiCert's names in it
  and no verification by any trust store), `pasta` cannot even forward to a namespace's loopback
  with an explicit target, and the cross-origin path needs no preflight (the SDK sends the agent
  calls with `noHeader`, and the service answers `Access-Control-Allow-Origin`).

## Exit criteria

- ✅ `reuse lint` stays green and the unit still starts the container from scratch: the deployed unit
  was synced to this repository's copy, the container was created from scratch with the publish
  (`--replace` + `--rm`, no container existing before), and it reached `ONLINE` in 14.1 s
  (`LOGGED_OUT` at 2.1 s). A start cannot depend on the relay's ordering either: `pasta` binds the
  published host port at container start - the collision measurement above shows the bind precedes
  every client process - and the relay itself is started by `start.sh` before the client is.
- ✅ The host-side `POST /v1/detect` is answered (through the published port, over the relay), and the
  browser half is seen: the portal's own page finds the client on `54642` and drives it to a
  workbench. The step still stays open because the strict form above is not seen, and the reason is
  recorded.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-16 — the browser half is **seen**, in a real Chromium on the host driven over CDP (a
  dedicated profile with certificate errors ignored, because a fresh profile refuses the *portal's*
  own certificate too - the operator's browser instead carries the two exceptions the README names).
  Loading `https://<portal>/portal/` fired the workbench's own probe list - six `POST /v1/detect`
  calls, the domain form and the IP form - and exactly one answered:
  `https://localhost.sangfor.com.cn:54642` (200), while `54631`, `54653`, `54630`, `54641` and `54652`
  got nothing (as they must: only `54642` is published). From there the page drove the client through
  that port to a full workbench - `/v1/service/init`, `/v1/service/status`, `/v1/aUem/status`,
  `/v1/update/status`, `/v1/aUem/queryVirtualNetInfo`, `/v1/base/printLog`, every one 200 - then
  exchanged the session on the portal (`/passport/v1/public/sessionIdExchange` 200), pulled the
  account's resources (`/controller/v1/user/clientResource` 200) and rendered the workbench with this
  account's own app in it. No password and no captcha were typed: the client was already `ONLINE`, so
  the hand-over took the session that existed. The portal's own bundle was read too
  (`.../portal/assets/iconfont.*.js`): the same six addresses the client's assets carry, which is why
  the spare answers a probe the page really makes.
* 2026-10-16 — what that leaves open is the drill's strict form, and it is left open on purpose: the
  tunnel *down*, a human typing the portal's login (with its captcha) in a browser, the tunnel coming
  up. Neither side of it can be produced from here - the captcha needs a person, and the supervisor
  recovers a logged-out session on its own (step 17 measured ~5 s with a warm engine session), so the
  human would be racing it. The staging, if the drill is wanted: the engine's password login is what
  the portal's captcha refuses on this deployment, so a logout sends the supervisor into `NEED_VNC`
  with its 900 s wait - which is the window a human can use.
* 2026-10-16 — the machine half is verified on the live container. The deployed unit (a pre-B06 copy
  installed 2026-10-13) was synced to this repository's, the generated `ExecStart` carries
  `--publish 127.0.0.1:54642:20000`, and the container, created from scratch, went `LOGGED_OUT` (2.1 s)
  to `ONLINE` (14.1 s) - faster than any earlier start, with the new publish in place. From the host:
  the bind is `127.0.0.1:54642` only; `POST https://127.0.0.1:54642/v1/detect` with the workbench's
  envelope answers `{"code":0,"message":"detect successfully","data":{"pubkey":""}}`, the same through
  the domain form (`--resolve localhost.sangfor.com.cn:54642:127.0.0.1`), and the gated
  `/v1/service/status` answers with the portal's own `Referer`. Three things were read off the live
  endpoint that the reference doc had wrong or did not have: the certificate is not self-signed but
  the client's own chain for the name (`CN=localhost.sangfor.com.cn`, SAN the same, 3 certs carrying
  DigiCert's names, `openssl verify` against the host's bundle: `error 20 at 0 depth lookup`), an
  `OPTIONS` is a wrong method and not a preflight handler (404 `Unsupported url` on `/v1/detect`,
  503 on `/v1/service/status`, allow-origin echoed beside both), and the vendor's SDK sends the agent
  calls with `noHeader` - no `Content-Type`, so a cross-origin call from the portal's page is a
  simple request that never preflights. The portal's own SPA carries the same six-address list
  (`localhost.sangfor.com.cn:{54631,54642,54653}` and `127.0.0.1:{54630,54641,54652}`), fetched from
  it and matched against the client's assets, so `54642` is a port that page will use.
* 2026-10-16 — the human half is the only open item, and it waits on a browser on the host: the
  `/etc/hosts` line needs `sudo` (password-protected here) and the certificate exception needs a
  person. The README's "The login in your browser" is the procedure; what has to be watched is the
  portal's login page finding the client (the six-address race above is what it does) and the tunnel
  coming up without VNC.
* 2026-10-16 — the exposure is decided (`PublishPort=127.0.0.1:54642:20000`, on by default, one
  drop-in to remove) and landed with its reason in the unit's comment. The port is the decision's own
  evidence: the vendor's workbench probes six addresses
  (`https://localhost.sangfor.com.cn:{54631,54642,54653}` beside
  `https://127.0.0.1:{54630,54641,54652}` - `web/old/jssdk/common/config.js` in the image and the
  compiled `web/assets/` bundle both carry the list), so any of the six reaches the client; on a host
  whose own aTrust client is installed (it is here - `atrust 2.5.16.41-1`, same two first-choice
  constants `DEFAULT_PORT=54630`/`DOMAIN_DEFAULT_PORT=54631`) the first choice cannot be published:
  measured on a scratch unit with this unit's `Restart=always` + `StartLimitIntervalSec=0` +
  `RestartSec=15s`, an occupied host port makes pasta fail the bind (`Listen failed for HOST TCP port
  127.0.0.1/15437: Address already in use`), `podman run` exit 126, the unit `activating
  (auto-restart)` and each retry 15 s later - the container never starts, and it starts by itself
  once the port is free. A spare leaves both startable.
* 2026-10-16 — the relay stays, and the alternative was measured rather than assumed. pasta's own
  `-t` accepts a target address (`[ADDR/]P:toaddr/P`), and `pasta:-t,127.0.0.1/15438:127.0.0.1/15438`
  is accepted and binds the host's `127.0.0.1:15438` - but forwards nowhere: the host's connect
  completes and no byte ever arrives, while the container's own listener on `127.0.0.1:15438` is up
  (the control, `-t,15439` to the namespace's own address with the server on `0.0.0.0`, answers at
  once). Delivery to a namespace's loopback is the one thing pasta does not do, so a socket on the
  container's non-loopback address is mandatory.
* 2026-10-16 — the off switch is a drop-in and was verified on a scratch unit: `[Container]` plus an
  empty `PublishPort=` in `atrust.container.d/*.conf` clears the list (the generated `ExecStart`
  loses its `--publish`), so turning the exposure off needs no edit of the shipped unit and no image.
* 2026-10-11 — written on request ("中继端口这个，单独做个plan"), with the measurements above already
  in hand. The security note is the reason the publish is not simply added to the shipped unit
  without a decision: what the host gains is the ability to end the client's session and drop the
  tunnel, which is exactly what this project's own supervisor is trusted to do - but nothing else on
  the host should be able to do it by accident.
