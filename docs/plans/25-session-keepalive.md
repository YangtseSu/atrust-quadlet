<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 25 — The engine's own portal session, kept warm

Status: ⬜ not-started
Depends on: an idle `ONLINE` run long enough for the engine's session to expire (hours; a live
container left alone with its journal is the whole instrument)
Touches: `atrustd/portal.py`, `atrustd/__main__.py`, `tests/test_cycle_pacing.py`, `docs/DESIGN.md`,
`README.md`
(each `- ⬜` item below is one commit)

## Goal

The engine's cookies live in one process's memory, and the steady `ONLINE` cycle touches the portal
not at all - the probe through the tunnel is the keepalive for the *tunnel's* session, and nothing
keeps the *web* session alive. So it goes cold while everything is healthy, and the next recovery pays
the fresh login, the `tid`/`tid.sig` write and the tray's own stop: measured once at **31 s** end to
end against **5.3 s** with the session still alive (`docs/plans/14-api-login-path.md`).

`zju-connect` keeps the same kind of session alive instead of re-authenticating: a
`GET /passport/v1/public/authConfig?needTicket=0` whose `data.isLogin` is the validity check, every
`SessionRefreshInterval` = 1800 s, the refreshed cookies written back to its own state file, and
`ErrSessionInvalid` treated as fatal
([`configs/config.go#L86-L87`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/configs/config.go#L86-L87),
[`auth/refresh.go#L39-L43`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/refresh.go#L39-L43),
[`client/atrust/session.go#L25-L64`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/session.go#L25-L64)).
Whether a read extends *this* portal's session is not known, so the step is measurement first: the
`password auth ok` line in the journal is the expiry's own mark, and a deployment's recovery either
pays the cold path or does not.

The refresh must stay a *read*: a full login rotates the device token and drops the client's own
session with it (the reason the engine's login and the client's login are one event here), so only
`onlineInfo`- or `authConfig`-shaped calls are candidates.

## Deliverables

- ⬜ The measurement: an idle `ONLINE` run's journal timestamps (the expiry shows as the next
  recovery's `password auth ok`), then the same run with one cheap read (`onlineInfo`, or
  `authConfig?needTicket=0`) every hour - does the session outlive its idle lifetime with the reads
  in between? Recorded in `## Progress log` either way, with the wall-clock numbers.
- ⬜ If a read extends it: the cycle (or a small timer beside it) emits that read on a slow, named
  cadence, and a test pins that the steady `ONLINE` state emits nothing more often than the cadence.
- ⬜ If it does not: the finding is the deliverable - the cold path stays the recorded price of a long
  `ONLINE` run, and `docs/DESIGN.md` says so beside the recovery numbers.
- ⬜ `docs/DESIGN.md` carries the measured lifetime of the engine's session and what, if anything,
  refreshes it; `README.md` mentions the cadence only if it became a switch.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ The measurement (and, if it landed, the refresh) is in `## Progress log`: a recovery after hours
  of `ONLINE` either walks the ticket path with no `password auth ok` line, or the log carries the
  number that says why it cannot.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened by the split of the survey archived at
  `docs/archive/2026-10-13-atrust-reimplementation-lessons.md` (then `B07`): the keep-warm candidate
  is its review's, from the sibling's refresh loop and step 14's own 31 s-vs-5.3 s numbers.
