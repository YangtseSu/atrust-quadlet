<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 16 — The agent's API reachable from the host

Status: 🚧 in-progress
Depends on: — (the measurements are in `docs/CLIENT-LOCAL-API.md`, "Reaching it from the host")
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
- ⬜ Verification, both halves:
  - from the host, `POST https://127.0.0.1:54631/v1/detect` (the `-k` and `Referer` rules are in the
    reference doc) answers `detect successfully` on the live container;
  - in the host's browser, the portal's login page detects the client and a web login brings the
    tunnel up - the human criterion, recorded here with what the page did and how long it took.
- ⬜ `docs/CLIENT-LOCAL-API.md`'s "Reaching it from the host" flips from "what fails and why" to what
  the deployment now does, keeping the measurements as the reason.

## Exit criteria

- ⬜ `reuse lint` stays green and the unit still starts the container from scratch (the relay runs
  before the client's own port exists, so a start must not depend on ordering).
- ⬜ The host-side `POST /v1/detect` is answered, and the browser half is either seen or the step
  stays open with the reason.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

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
