<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 13 — Event-driven supervision

Status: ⬜ not-started
Depends on: step 12 (the `clientapi` module and the port discovery it lands)
Touches: `atrustd/clientapi.py`, `atrustd/__main__.py`, `tests/test_clientapi.py`, `docs/DESIGN.md`,
`docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

A cycle runs every `ATRUST_WATCH_INTERVAL` (90 s) and the only thing that wakes it earlier is nothing:
a client-side transition - the portal ending the session, the tunnel going down, the client being
logged out - is seen at the next cycle at the earliest, which is most of the ~130 s recovery time the
milestone log measured. The client publishes exactly those transitions on its own event channel
(`docs/CLIENT-LOCAL-API.md`, verified live): `POST /v1/service/events` with
`{"fromId": <last id>, "timeout": <ms>}` blocks until something happens and answers with the event
and the new id.

This step subscribes to that channel from inside `atrustd` and lets an event *wake the loop*, not
decide for it: the cycle then runs as it does today and the data plane still decides. The vendor's
own guidance for the same channel says the same thing - after a logout or tunnel event, re-query the
state instead of trusting the event - and the event stream is also where `resourceReady`,
`enterOnlineRun` and the rest of the client's own vocabulary show up, which makes it the natural
place to learn what a *client-side* recovery looks like without guessing.

The long poll is the flavour to build on: it is a plain HTTPS POST with a bounded timeout, so the
standard library covers it, while the WebSocket flavour would need a hand-rolled RFC 6455 client for
no additional events.

## Deliverables

- ✅ `atrustd/clientapi.py` gains the poller: a long poll with a bounded timeout (the request's own
  timeout must exceed the server's `timeout` field), the last-seen id tracked across calls, a filter
  that decides which events are worth waking for, reconnect on error with backoff, and a
  `threading.Event` the daemon's waits can watch. It must never raise into the daemon and must stop
  promptly when the daemon's stop event is set.
- ✅ `run_daemon` starts the poller beside the cycle loop and `pause()` waits on `stop OR event`, so
  a transition cuts the remaining `ATRUST_WATCH_INTERVAL` short; the cycle logs why it woke (the
  event that fired) and the transition detail carries it.
- ✅ `tests/test_clientapi.py`: a fake long-poll server (a socket the test owns) exercises the id
  tracking, a timeout with no events, an event wake, a dropped connection and the stop path - all
  offline, no sleeps longer than the fake's own timeout.
- ✅ The measurement, recorded here: with the poller running, a controlled down (the client family
  stopped, the way the supervisor does it) is acted on in *seconds* - the next cycle starts on the
  event instead of waiting for the interval - and the same run's journal shows the poller's
  reconnect after the agent's own restart. Compare against the blind-poll baseline (the last cycle's
  `updated` timestamp against the moment the client actually went down).
- ✅ `docs/DESIGN.md`: the supervisor section says what wakes a cycle and what still decides it.

## The measurement (live, 2026-10-11, client 2.5.16.30, the dev image)

The daemon ran the step's code on the dev image (`localhost/atrust-quadlet:dev`, the temporary
`Image=` drop-in of steps 11-12). Its own journal timestamps are quoted (container clock); private
values are placeholders. Two controlled downs, each timed from the moment the stop was issued:

| # | the down | the channel | the poller | the woken cycle |
|---|---|---|---|---|
| 1 | `tokens.stop_client_family()` - the supervisor's own sweep (SIGTERM then SIGKILL, 1.9 s to return) | the in-flight long poll died with `Remote end closed connection without response` **+0.05 s** | the retry at **+2.1 s** answered `the client service is not listening` (backoff 4 s); `client event channel is up (id 7)` at **+6.6 s**; the agent's restart burst followed (`tunnelStatus` +6.93 s, `status` +6.98 s) | `woke on client event(s): tunnelStatus, status` **+7.1 s**; the probe found the tunnel back and wrote `tunnel up` at +10.9 s (no transition - the client's own restart had restored it first) |
| 2 | the tunnel killed (`pkill -9 -f` on `aTrustXtunnel-64`, its agent left alive) | nothing was published while it was down | - | the client respawned the tunnel itself and announced only the restored state: `tunnelStatus` **+5.1 s**, the wake **+5.3 s**, `tunnel up` written at +8.2 s |

Both downs were repaired by the client before any probe - the supervisor's or the client's own event
- could see the tunnel gone (drill 1: routes `30 -> 0` at +3.2 s and back by ~+7 s; drill 2: a new
tunnel pair within ~5 s), so neither produced a `DEGRADED` transition. What they measure is the wake,
which is what this step was for: **the next cycle started 7.1 s and 5.3 s after the down instead of
at the next interval**, and the journal carries the poller's whole reconnect path.

The blind-poll baseline, as the deliverable names it: the last cycle before drill 1 wrote its
`updated` at 14:21:06.94 and the family stopped at 14:21:31.85, so a supervisor without the poller
would have looked again at 14:22:36.94 - **65.9 s after the down** (the blind latency is uniform on
`ATRUST_WATCH_INTERVAL`, 0 to 90 s).

What drill 1 also shows is the shape the step started from: *no event can announce a down while the
thing that publishes events is the thing that died*. The channel's death is the down's own signal
(`not listening` at +2.1 s), and its return is what wakes the cycle. A transition the client can
publish while it is alive is delivered the same way - the session-enter vocabulary was logged live on
the same run (`leaveInitial`, `login`, `enterOnline`, `enterOnlineRun`, `tunnelStatus`, `status` at
the container start, and `state.json`'s detail carries `woke on client event leaveInitial, login,
enterOnline, enterOnlineRun, tunnelStatus, status`), and the session-*ending* vocabulary
(`leaveOnlineRun`, `leaveOnline`, `logout`, `enterInitial`) was captured from the same channel with a
throwaway subscriber while the implementation's shape was still being decided.

The filter held over the run: three wakes in ~5 minutes of journal, one per real transition, nothing
from the chatter it drops (read at DEBUG). The extra thread does not touch the stop path: `stop` ->
`signal 15 received` -> `client stop took 1.60s`, the container died 1.67 s after the signal; the
poller is not joined - its worst case is one bounded long poll, the stop event ends its loop and the
process exit takes the rest.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` and `reuse lint` stay green (96 tests; 88/88 files).
- ✅ Live: one controlled down shows the wake latency and the recovery path in the journal, and the
  numbers are in this file.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-11 — written after the reference doc landed. The poller is deliberately a *wake* and not a
  second state machine: the client's own view can be wrong in both directions (it can report a
  tunnel it cannot carry), and the only thing that ever decided the supervisor's state is the probe.
* 2026-10-11 — the shape was measured before the code was fixed, with a throwaway long-poll
  subscriber inside the running container and `tokens.stop_client()` as the down: the in-flight poll
  dies with `RemoteDisconnected` the moment the agent does, the agent's ids restart with it (a stale
  high `fromId` still received the new process's events, but `fromId: 0` - "from now" - is what the
  poller sends once a poll has failed, which is also what the reference doc's guidance implies), the
  reconnect is ~2 s, the burst that follows carries `tunnelStatus` and the full `status` object, and
  a quiet poll answers exactly at its own `timeout`.
* 2026-10-11 — implementation landed as three commits (`feat(atrustd): poll the client's own event
  channel in the background`, `feat(atrustd): let a client event wake the daemon's wait`,
  `test(clientapi): pin the long poll's ids, wakes, drops and stop`). Deviation from the `Touches:`
  line, recorded here: `tests/test_cycle_pacing.py` changed as well - the daemon tests needed the
  poller stubbed (a unit test must not poll loopback) and `pause()` gained the third argument, and
  the new behaviour is pinned there (a wake cuts a wait, a stop still wins, the reason reaches the
  cycle, `--once` starts no poller). Offline: 96 tests green, `reuse lint` 88/88.
* 2026-10-11 — live acceptance on the dev image (the temporary drop-in again). The poller subscribed
  after two backoffs (`client event channel is up (id 12)`) and logged the session-enter vocabulary;
  the cycle that ran on it carries the wake in `state.json`'s detail. Then the two controlled downs
  under "The measurement" above: the family sweep, where the poller reconnected after the agent's own
  restart and the woken cycle started 7.1 s after the down (blind baseline 65.9 s), and a killed
  tunnel, which the client repaired and announced in 5.1 s. The stop path stayed at 1.60 s with the
  poller running.
* 2026-10-11 — the dev image is what the live container runs through the drop-in until the published
  image carries this step.
