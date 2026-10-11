<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 12 — The client's own state as a supervisor input

Status: ✅ done — 2026-10-11, landed and measured live (a controlled logout sampled every 2 s beside
the probe: the client's own view never disagreed with the data plane, and no transition reads it yet)
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

- ✅ `atrustd/clientapi.py` (stdlib only): port discovery - read the port from
  `/usr/share/sangfor/.aTrust/var/run/httpserver`, fall back to the `+11` candidates
  (`54630`, `54641`, `54652`), never assume; the request envelope from the reference doc; a
  `status()` call with a bounded timeout that returns a small dataclass and never raises into a
  cycle; a `session()` helper for the gated routes that sets `Referer: <portal>/`.
- ✅ `tests/test_clientapi.py`: envelope construction, port discovery (file present, absent,
  malformed, drifted), response parsing (success, business error, garbage, timeout), and the
  Referer gate - all offline, against a socket the test owns. 14 tests; the stub joins its serve
  thread on close, because a listener closed while `accept()` is in flight stays in LISTEN until
  that call returns and the next test's bind raced it.
- ✅ `cycle()` records the client's view: `state.json` gains the client's user state, tunnel state,
  user name and login time (kept short; the file is read by `quadlet/atrust-notify.sh`), and the
  transition log line carries it beside `probe.check()`'s detail. Nothing in the state machine
  changes yet.
- ✅ The measurement the decision needs, recorded here: sample `POST /v1/service/status` beside the
  data plane across at least one full recovery (a controlled down and back up) and one `NEED_VNC`
  hand-over - does `tunnelStatus` lead, lag or disagree with the probe, and what does the client
  report in each of `ONLINE`, `DEGRADED`, `LOGGED_OUT`, `NEED_VNC`? With that table in hand, decide
  in this step (and write down) whether any state-machine transition may read the client's view -
  for example skipping the recovery when the client reports `otherSdpCLogin`/`otherSdpCOffline`,
  which no data-plane check can distinguish from a plain outage. *See "The measurement" below.*
- ✅ `docs/DESIGN.md`: the supervisor section says what the client's view contributes (and what it
  deliberately does not); the new `ATRUST_CLIENT_API_PORT_FILE` also joined the README's
  configuration table beside the other client paths.

## The measurement (live, 2026-10-11, client 2.5.16.30, one observed cycle)

A sampler inside the container read `POST /v1/service/status` beside `probe.check()` every 2 s, and
the daemon recorded its own view at every transition, across one controlled down and back up: a
forced `/v1/service/logout` at 21:08:37 and the supervisor's own recovery. Private values are
placeholders (`<user>`, `<portal>`).

| supervisor state | data plane | client's own view (`state`/`tunnelStatus`) | note |
|---|---|---|---|
| `ONLINE` | 30 routes, a real request answers `200` | `online`/`tunnelAvailable` + `<user>` + login time | agree |
| down (logout at 21:08:37) | routes gone, the probe fails | `logout`/`tunnelUnavailable` | both flipped in the **same 2 s sample**; the supervisor's `DEGRADED` followed 32 s later (its 90 s cadence) |
| `DEGRADED` (21:09:10, 21:13:23) | down | `logout`/`tunnelUnavailable` | `user` blank and `loginTime` an epoch string while logged out |
| `LOGGED_OUT` (21:11:34, 21:15:48) | down | `logout`/`tunnelUnavailable` | |
| `NEED_VNC` (21:16:52) | down | `logout`/`tunnelUnavailable` | reached on the `attempts >= ATRUST_LOGINS_BEFORE_VNC` branch (`attempts: 2`; the hint says "the tunnel is still down after 2 login attempt(s)"); the portal served a captcha image on request although it was not asking for one; the human half was not needed - see below |
| recovery (`LOGGED_OUT -> ONLINE`, 21:33:28) | the probe comes back | `online`/`tunnelAvailable` | again the **same 2 s sample**; the supervisor's transition followed 4 s later (its 5 s wait poll) |

What else the drill measured - this is what made the recovery 25 minutes instead of the usual ~2:

* the forced logout ends the client's session, but the portal keeps the account "online" and refuses
  the engine's password login with `code=75500006 当前账号已在线，无需重复上线`; two attempts (21:11:35,
  21:15:48) were refused and the next one (21:32:53) was accepted - ~24 min after the logout, in line
  with the portal's own ~20 min session expiry. The client's window login (submitted by `uiauto` with
  the right credentials, twice) did not bring the tunnel up either.
* the supervisor's `web session is alive` branch restarted the client and waited its 120 s in both
  rounds (~2.4 min each) although the client's own view said `logout` from the first second - and a
  restart cannot restore a session the portal has already ended.
* `/v1/service/online` - the client-side ticket half of the vendor's re-attach path - answered
  `code=75500307 非法的随机校验码` while the client was logged out: that path needs a live session.
* during a client-family restart the API answers nothing for ~2-4 s; a transition sampled inside that
  window records the reason instead of a view (the recreation cycle below shows one).

### What may act on it (the decision)

**Nothing in the state machine reads the client's view yet.** Where both existed it never disagreed
with the probe - they flipped within one 2 s sample in both directions - so it adds no earlier
warning; it cannot replace the probe (the client can report `tunnelAvailable` while its netstack
drops traffic); and the one vocabulary no data-plane check can express, `otherSdpCLogin`/
`otherSdpCOffline` (this client online to another portal), could not be produced on a deployment
that talks to a single portal, so nothing is decided from it.

The measurement supports one candidate, recorded here for whatever step acts on this interface: when
the client itself reports `logout` while the tunnel is down, skip the `web session is alive` branch's
client restart - it cannot help, and it costs ~2.4 minutes per round before the login path is reached
anyway. That is a state-machine change and needs its own measurement (including what the view says
inside a restart window, where the client is unreachable).

## The live cycle the exit criterion names

The dev image (`localhost/atrust-quadlet:dev`, a temporary `Image=` drop-in) was observed through one
container recreation; the daemon's own transitions carried the client's view in each state (the
private values replaced):

```
ONLINE -> DEGRADED (tunnel not usable); client unreachable: the client service is not listening (54630, 54641, 54652)
DEGRADED -> LOGGED_OUT (the client has to log in again); client unreachable: the client service is not listening (54630, 54641, 54652)
LOGGED_OUT -> ONLINE (tunnel up after the client login); client online/tunnelAvailable user=<user> since=2026-10-11 21:06:26
```

At the first two transitions the client family was still starting (the recreation), so the record is
the honest "unreachable" - the observed drill cycle above is the one where every state carried a
view. `podman exec atrust python3 -m atrustd --status` at the end prints `state: ONLINE` with
`client: {state: online, tunnel: tunnelAvailable, user: <user>, login: 2026-10-11 21:32:44}`.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` and `reuse lint` stay green (85 tests; 87/87 files).
- ✅ Live: `podman exec atrust python3 -m atrustd --status` carries the client's own view in every
  state the container passes through in one observed cycle, and the measurement table above is in
  this file. The drill cycle is the one that satisfies it - every state it passed through carried a
  view (the recreation's first two transitions recorded the honest "unreachable" while the client
  family was still starting; both are quoted above).
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-11 — written after the reference doc landed. The reason this is a step and not a patch: the
  only honest way to use the client's own state is to know where it disagrees with the data plane,
  and that needs a measurement across a real recovery, not a guess at the desktop.
* 2026-10-11 — implementation landed as three commits (`feat(atrustd): read the client's own view
  over its local API`, `test(clientapi): pin the envelope, the gates, the port fallbacks and every
  failure`, `feat(atrustd): record the client's own view beside the data plane`). Deviations from the
  `Touches:` line, both recorded here: `quadlet/atrust-notify.sh`'s `field()` now matches the top
  level only (the nested `client` object has a `state` of its own, and the notifier must never read
  it), and two test files changed - `tests/test_notify.py` writes the new file shape, and
  `tests/test_cycle_pacing.py` gained the recording test plus a stubbed `ClientAPI` so the daemon
  tests stay off loopback. Offline: 85 tests green, `reuse lint` 87/87.
* 2026-10-11 — one measurement before the drill, taken ad hoc on the live container: the envelope
  `guid` may be empty for `/v1/service/status` (the full state comes back and `sdpcguid` comes out of
  it), and without the `Referer` the same call blanks `username` - so the client sends the portal
  origin on every call, status included.
* 2026-10-11 — live observation on the dev image (drop-in `Image=localhost/atrust-quadlet:dev`, one
  container recreation as in step 11): the cycle quoted under "The live cycle" above. The recreation
  itself is the first controlled down and back up - the supervisor went `ONLINE -> DEGRADED` at its
  first cycle and `LOGGED_OUT -> ONLINE` 13 s later, i.e. about 1¾ min after the restart began (most
  of it the container recreation itself).
* 2026-10-11 — the drill that produced "The measurement": `POST /v1/service/logout`
  `{"type":"force"}` through `ClientAPI.session` (the tray's own shape, `code 0 "OK"`), sampled by a
  throwaway 2 s sampler inside the container beside `probe.check()`. The `NEED_VNC` row came from the
  supervisor itself (the `attempts` branch, hint and captcha written); the recovery was the
  supervisor's own retry after the portal's session expiry - no human half was needed, and the
  `NEED_VNC` hint of a captcha-*required* hand-over is still only observed once (step 04). Findings
  that belong to the reference doc were added there: the portal's `75500006` refusal and the
  logged-out `75500307` on `/v1/service/online`.
* 2026-10-11 — the live container runs the local `:dev` image through the temporary drop-in until the
  published image carries this step; removing the drop-in puts it back on `:latest`.
* 2026-10-11 — closed. Offline green at the close (85 tests, `reuse lint` 87/87); the live container
  runs the step's code and its `--status` carries the view; the two sampler logs are kept outside the
  tree (`/tmp/step12-drill-*.jsonl`, scratch). What shipped is the record only - the state machine is
  untouched, which is this step's decision as much as its scope. The one measurement this step
  suggests against is now on the table for the step that acts on the interface: the ~2.4 minutes per
  round the `web session is alive` branch spends restarting a client whose own view already says
  `logout`.
