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

- ⬜ `atrustd/clientapi.py` gains the poller: a long poll with a bounded timeout (the request's own
  timeout must exceed the server's `timeout` field), the last-seen id tracked across calls, a filter
  that decides which events are worth waking for, reconnect on error with backoff, and a
  `threading.Event` the daemon's waits can watch. It must never raise into the daemon and must stop
  promptly when the daemon's stop event is set.
- ⬜ `run_daemon` starts the poller beside the cycle loop and `pause()` waits on `stop OR event`, so
  a transition cuts the remaining `ATRUST_WATCH_INTERVAL` short; the cycle logs why it woke (the
  event that fired) and the transition detail carries it.
- ⬜ `tests/test_clientapi.py`: a fake long-poll server (a socket the test owns) exercises the id
  tracking, a timeout with no events, an event wake, a dropped connection and the stop path - all
  offline, no sleeps longer than the fake's own timeout.
- ⬜ The measurement, recorded here: with the poller running, a controlled down (the client family
  stopped, the way the supervisor does it) is acted on in *seconds* - the next cycle starts on the
  event instead of waiting for the interval - and the same run's journal shows the poller's
  reconnect after the agent's own restart. Compare against the blind-poll baseline (the last cycle's
  `updated` timestamp against the moment the client actually went down).
- ⬜ `docs/DESIGN.md`: the supervisor section says what wakes a cycle and what still decides it.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ Live: one controlled down shows the wake latency and the recovery path in the journal, and the
  numbers are in this file.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-11 — written after the reference doc landed. The poller is deliberately a *wake* and not a
  second state machine: the client's own view can be wrong in both directions (it can report a
  tunnel it cannot carry), and the only thing that ever decided the supervisor's state is the probe.
