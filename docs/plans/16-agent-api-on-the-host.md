<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 16 — The agent's API reachable from the host

Status: ⬜ not-started
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

- ⬜ Decide and write down the exposure: which port is published (`127.0.0.1:54631:20000`, the
  domain form the workbench uses), whether it is on by default or a documented drop-in, and why -
  the service can `logout`, `offline`, read the status and stream the events, so it stays on
  `127.0.0.1` and the decision is recorded in the unit's comment, not just in this file.
- ⬜ `base/overlay/start.sh`: the relay is stated as what it is (the thing that makes the published
  port work) instead of an accident of a docker-era REDIRECT - either the dead rule goes or a
  comment says which runtime still needs it; if the IP-form port (`54630`) is wanted too, it gets a
  relay of its own, otherwise the choice is recorded here.
- ⬜ The Quadlet unit (or the documented drop-in) publishes the chosen mapping; `README.md` carries
  the host side: the `/etc/hosts` entry for `localhost.sangfor.com.cn`, the self-signed certificate
  exception, and what the exposure means.
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

* 2026-10-11 — written on request ("中继端口这个，单独做个plan"), with the measurements above already
  in hand. The security note is the reason the publish is not simply added to the shipped unit
  without a decision: what the host gains is the ability to end the client's session and drop the
  tunnel, which is exactly what this project's own supervisor is trusted to do - but nothing else on
  the host should be able to do it by accident.
