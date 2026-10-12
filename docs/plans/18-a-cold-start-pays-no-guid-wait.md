<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 18 — A cold start pays no wait for a guid the client cannot publish yet

Status: ✅ done — 2026-10-12, landed and measured live (three container recreations on the dev image: the
ticket path's way in costs 4.7 s instead of the twice-paid ten-second bounds, and the recovery is 18.3 s
end to end against step 14's 54.4 s for the same state and its 13.5 s old-path figure)
Depends on: — (step 14's cold-start numbers and its own follow-up, "a tighter guid wait")
Touches: `atrustd/clientapi.py`, `atrustd/__main__.py`, `tests/test_clientapi.py`,
`tests/test_cycle_pacing.py`, `docs/DESIGN.md`, `docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

The ticket path's way in pays `CLIENT_RESTART_WAIT` (ten seconds, one read a second) for a client whose
HTTP service is not answering yet or whose `sdpcguid` is still empty. The bound is priced for a tray that
has just restarted - its service is unreachable for ~2-4 s and its guid appears within ~5 s - but a
container that has just been recreated publishes no guid for 35 s+, and nothing told the two apart:
step 14 recorded exactly that ("nothing measured so far tells the two apart, so every cold start pays the
ten-second bound for the chance to win a tray restart"), with the cold start at 54.4 s against the old
path's 13.5 s - ~20 s of it these two bounds, the one case where the image got slower.

The discriminator is already in the daemon's hand and needs no new probe: whether *this daemon* has ever
seen a guid from its client. A daemon that has (the tray restart, the client restarted around a token
write, an hours-old session ending) pays the bound as today; one that has not - a container whose client
has just started with it - reads once and lets the window path, whose login runs in that case anyway, take
the cycle.

## Deliverables

- ✅ `atrustd/clientapi.py`: `ClientAPI.status()` adopts a non-empty `sdpcguid` into `self.guid` and
  remembers that it has seen one (`seen_guid`), so the envelope's guid and the wait decision have one
  source; the docstring says what the memory is for.
- ✅ `atrustd/__main__.py`: `_api_login()`'s two `_client_view(..., CLIENT_RESTART_WAIT, want_guid=True)`
  calls wait `CLIENT_RESTART_WAIT if api.seen_guid else 0.0` - one read where a guid has never been
  published, the bound where a restart is the likely cause. The refusals it can still return are unchanged
  (`the client has no session guid yet`, `the client service did not answer: ...`).
- ✅ Tests: `tests/test_clientapi.py` pins the memory (a read carrying a guid, then one without, keeps
  `guid` and `seen_guid`); `tests/test_cycle_pacing.py` pins that a daemon which has never seen a guid does
  not sleep for one and records why the attempt could not run, and that a daemon which has seen one still
  pays the bound.
- ✅ Live, on the dev image: one container recreation with the journal quoted - the ticket path's way in
  costs no ten-second pause, the reason it could not run is in `state.json`, and the recovery lands beside
  step 14's 13.5 s old-path figure instead of its 54.4 s one. *See "The measurement" below: 4.7 s of way in,
  18.3 s end to end, twice.*
- ✅ `docs/DESIGN.md`: the ticket path's limits carry the discriminator (a guid this daemon has seen)
  beside the 35 s+ cold-start number, and the supervisor section names the switch.

## The measurement (live, 2026-10-12, client 2.5.16.30, the dev image, three container recreations)

`localhost/atrust-quadlet:dev` run from `podman run` with the unit's own flags, so every start is a
container recreation: a fresh `atrustd`, an in-memory engine (the cookie jar lives in the process, so a
recreation starts without a portal session) and the client's profile on the host. One recreation's own
journal, container clock, private values are placeholders:

| time | line |
|---|---|
| 14:02:16.17 | the container starts; the daemon's first cycle runs immediately |
| 14:02:16.3 | `ONLINE -> DEGRADED (tunnel not usable); client unreachable: the client service is not listening (54630, 54641, 54652)` |
| 14:02:16.3 | `DEGRADED -> LOGGED_OUT (the client has to log in again)` - the ticket path's way in begins |
| 14:02:16.67 | `password auth ok (next=auth/authCheck)` - the fresh login the path runs when the engine session is cold |
| 14:02:16.84 | `portal login ok, tokens: tid(36 chars),tid.sig(43 chars)` |
| 14:02:20.96 | `app list written to /run/atrustd/apps.json` (`publish_apps`; the portal's own latency, 4.1 s here) |
| 14:02:21.00 | `the client published no session guid; the ticket cannot be handed over` |
| 14:02:21.00 | `WARNING the ticket login did not bring the tunnel up (the client has no session guid yet); falling back to the client window` |
| 14:02:21.31 | `WARNING portal login attempt failed: login rejected: code=75500006 当前账号已在线，无需重复上线` (the window path's own login) |
| 14:02:29.40 | `uautod`: `submitted the login form of the client window` |
| 14:02:34.49 | `LOGGED_OUT -> ONLINE (tunnel up after the client login)` - 18.3 s after the container started |

The way in cost **4.7 s** - the fresh login and the app list - where the first read used to wait ten
seconds and the second one ten more. Two recreations measured end to end at **18.3 s** (14:02:16.17 ->
14:02:34.49 and 13:55:09.78 -> 13:55:28.07), against step 14's 54.4 s for the same state and its 13.5 s
for the old path: the ~20 s the bounds cost are gone, and what is left is the engine's login, the
portal's app-list latency and the client's own window. A third recreation ran with the interface switched
off (`ATRUST_CLIENT_API=0`) and reached `ONLINE` in the same 18.2 s (13:59:04.29 -> 13:59:22.53), i.e.
the path that ran here is the one the old image ran, at the old image's speed.

The state file carried the refusal where a human reads it - captured by a 0.25 s reader during the same
recreation (it is replaced by the next woken cycle within seconds, which is what step 13 does):

```
"detail": "utun7 2.0.0.1/24; 30 route(s) via utun7; probe <intranet target>:80 ok (HTTP/1.1 200);
           the ticket login: the client has no session guid yet"
```

Two findings from the same runs, both recorded where the step that owns them can act:

* the fresh login `_api_login` runs is repeated by the window path in the same cycle and the second one is
  refused (`75500006 当前账号已在线，无需重复上线`, 0.3 s after the first had succeeded). The recovery
  landed anyway, but the journal reads like a failed login; step 17 owns the branch order that would skip
  the repeat.
* the client's own view reported a `since` 28 s *older* than the container's own start, and the portal
  answered the fresh login `already online`: the view reflects the session the portal holds, which on this
  account was another device's - nothing in this step reads the field, but a recovery's `since` cannot be
  assumed to be this container's own.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` and `reuse lint` stay green (117 tests; 92/92 files).
- ✅ Live: a container recreation shows no ten-second pause in the ticket path's way in (4.7 s for the
  fresh login and the app list, then the refusal - "The measurement" above), and the state file carries
  the reason it could not run when it cannot (the captured `detail` above).
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-12 — opened from step 14's own follow-up. Started ahead of step 17 (the number is the execution
  order; this one is a two-line behaviour fix whose evidence is already on the table, and the cold start it
  fixes is the same session's request). The measurement this step has to show is deliberately the cheap
  one: a recreation, no forced logout, no extra portal login.
* 2026-10-12 — the code half landed in the same session it was opened: `ClientAPI.status()` adopts a guid
  into `self.guid` and remembers it (`seen_guid`), `_api_login()`'s two reads wait `CLIENT_RESTART_WAIT if
  api.seen_guid else 0.0`, and the two test files pin the memory and both sides of the wait (117 tests
  offline, `reuse lint` 92/92). What is left is the live item: the dev image rebuilt and one container
  recreation on it, which is the recreation this step's own exit criterion names.
* 2026-10-12 — closed. The dev image was built here (a scratch `Containerfile` in `/tmp` that differs from
  the repository's only in the apt mirror: `deb.debian.org` is unreachable from this host today, two builds
  died inside its apt stage, and the suite lists came from a reachable mirror; the layers above the apt
  step are the repository's own). Three recreations on it, quoted under "The measurement": the way in costs
  4.7 s and the recovery 18.3 s twice, against step 14's 54.4 s pre-fix and 13.5 s on the old path, and the
  switched-off control run landed in the same 18.2 s. The live run also produced two findings that belong to
  other steps (the duplicate portal login - now step 17's item - and the client's `since` reflecting a
  session the container did not create); both are written down above.
