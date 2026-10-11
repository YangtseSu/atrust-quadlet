<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 12 — The client's own state as a supervisor input

Status: ⬜ not-started
Depends on: — (`docs/CLIENT-LOCAL-API.md` carries the measurements this step builds on)
Touches: `atrustd/clientapi.py` (new), `atrustd/__main__.py`, `atrustd/config.py`, `atrustd/state.py`,
`tests/test_clientapi.py` (new), `docs/DESIGN.md`, `docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

The supervisor decides everything with the data plane, and that stays true: `probe.check()` forks `ip`
twice and sends a real request through the container proxy, which is what proves the tunnel carries
traffic. What the client *thinks* is a second, much cheaper signal the supervisor never reads today -
`POST /v1/service/status` is one loopback request (`docs/CLIENT-LOCAL-API.md`, verified live) and it
answers with the client's own user state (`online`, `offline`, `disconnect`, `logout`, ...), its tunnel
state, the logged-in user name, the login time and the server guid.

This step lands the client's view as a *recorded* input first - beside the data-plane detail in
`state.json` and in the transition log - and takes the decision about acting on it only from the
measurement below. The point is not to trust the client over the probe (it can report
`tunnelAvailable` while the netstack drops traffic, which is why the probe exists) but to have the
fields the data plane cannot see: who is logged in, since when, and whether the client believes it is
online at all.

## Deliverables

- ⬜ `atrustd/clientapi.py` (stdlib only): port discovery - read the port from
  `/usr/share/sangfor/.aTrust/var/run/httpserver`, fall back to the `+11` candidates
  (`54630`, `54641`, `54652`), never assume; the request envelope from the reference doc; a
  `status()` call with a bounded timeout that returns a small dataclass and never raises into a
  cycle; a `session()` helper for the gated routes that sets `Referer: <portal>/`.
- ⬜ `tests/test_clientapi.py`: envelope construction, port discovery (file present, absent,
  malformed, drifted), response parsing (success, business error, garbage, timeout), and the
  Referer gate - all offline, against a socket the test owns.
- ⬜ `cycle()` records the client's view: `state.json` gains the client's user state, tunnel state,
  user name and login time (kept short; the file is read by `quadlet/atrust-notify.sh`), and the
  transition log line carries it beside `probe.check()`'s detail. Nothing in the state machine
  changes yet.
- ⬜ The measurement the decision needs, recorded here: sample `POST /v1/service/status` beside the
  data plane across at least one full recovery (a controlled down and back up) and one `NEED_VNC`
  hand-over - does `tunnelStatus` lead, lag or disagree with the probe, and what does the client
  report in each of `ONLINE`, `DEGRADED`, `LOGGED_OUT`, `NEED_VNC`? With that table in hand, decide
  in this step (and write down) whether any state-machine transition may read the client's view -
  for example skipping the recovery when the client reports `otherSdpCLogin`/`otherSdpCOffline`,
  which no data-plane check can distinguish from a plain outage.
- ⬜ `docs/DESIGN.md`: the supervisor section says what the client's view contributes (and what it
  deliberately does not).

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ Live: `podman exec atrust python3 -m atrustd --status` carries the client's own view in every
  state the container passes through in one observed cycle, and the measurement table above is in
  this file.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-11 — written after the reference doc landed. The reason this is a step and not a patch: the
  only honest way to use the client's own state is to know where it disagrees with the data plane,
  and that needs a measurement across a real recovery, not a guess at the desktop.
