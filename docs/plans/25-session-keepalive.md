<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 25 — The engine's own portal session, kept warm

Status: ✅ done
Depends on: — (one live evening: the session's own lifetime turned out to be minutes, not the hours
this line once assumed)
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

- ✅ The measurement: three runs, one engine login each, a cheap read on a schedule from a process of
  its own (`onlineInfo` at 60-120 s; the same at a steady 90 s from the daemon's own `ONLINE` cycle;
  `authConfig?needTicket=0` at 90 s) - three sessions, three deaths at 11.0, 10.7 and 10.5 minutes
  from the login: the session does not outlive its own lifetime, and none of the reads extends it.
  Recorded in `## Progress log` with the wall-clock numbers.
- ✅ *Not taken:* no read extended the session, so no cadence landed and the `ONLINE` path still
  touches the portal not at all. (The read was written, run live for 17 minutes and reverted; the
  journal lines and the numbers are in the Progress log.)
- ✅ The finding landed instead: the cold path stays the recorded price of a long `ONLINE` run - 31 s,
  measured live again on a session the reads had reported cold - and it is in `docs/DESIGN.md` beside
  the recovery numbers.
- ✅ `docs/DESIGN.md` carries the engine session's measured lifetime (~10-11 minutes from the login)
  and the two reads that do not extend it; no switch was added, so `README.md` is unchanged.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` (172) and `reuse lint` stay green - the keep-warm code
  and its two tests were reverted with the finding, so nothing of them is left to pass.
- ✅ The measurement is in `## Progress log`: a recovery 31.2 minutes after the engine's login (its
  session dead since 01:11:05) paid the `password auth ok` line at 01:32:06 - the log carries the
  number that says why it cannot walk the ticket path (the ~10-11-minute lifetime).
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened by the split of the survey archived at
  `docs/archive/2026-10-13-atrust-reimplementation-lessons.md` (then `B07`): the keep-warm candidate
  is its review's, from the sibling's refresh loop and step 14's own 31 s-vs-5.3 s numbers.
* 2026-10-13 — a pointer from step 21: the `ErrSessionInvalid` this step's refresh loop reads is now
  a class - `portal.classify(...) == portal.SESSION_INVALID`; `LOGGED_OUT_CODES` is gone, so a
  refresh that answers session-death should go through the table rather than a code set of its own.
  `tests/test_cycle_pacing.py` has the `client()` stand-in a keepalive cycle test wants (a Mock with
  the refusal record's defaults, which `cycle()` reads). Step 21 added no portal call to the steady
  `ONLINE` path, only the clearing of the refused record, so this step's "the steady cycle touches
  the portal not at all" still holds when it starts measuring.
* 2026-10-14 — the instrument, first. The engine's session is the whole cookie family its login
  answers with, measured live: `tid`, `tid.sig`, `sid`, `sid.sig`, `sid-legacy`, `sid-legacy.sig`,
  `straceid`, `straceid.sig`, `sdp_limit_auth_tag`, `sdp_limit_auth_tag.sig`, `lang` - while the
  client's own profile only ever carries `tid`/`tid.sig` (`portal.tokens()`), so a read-only probe
  that loads the profile's pair is *not* the engine's session and its `session-invalid` answer says
  nothing about the daemon's jar: the two jars share only the `tid` pair, and every probe answer of
  that shape is therefore discarded (the daemon's own `is_logged_in()` stays the authority). The
  instrument for a live session is a process that runs the login itself.
* 2026-10-14 00:22:56 — the first forced recovery: a client-side logout
  (`POST /v1/service/logout {"type":"force"}`, the step-14 drill) 15.2 minutes after the engine's
  own login (00:07:15) made the cycle pay the fresh login (`password auth ok`, 00:23:27) - the
  engine's session was gone by then. What killed it is not yet known: that run's login was followed
  8 s later by the client's own window login, so either the client's login replaced it or its idle
  lifetime is shorter than the 15.2 minutes. A login of the engine's own kind does *not* disturb the
  client: a fresh engine login at 00:42:41 left the client at `online/tunnelAvailable` with no
  recovery in the journal - so the two sessions are separate and a measurement can use one without
  ending the other.
* 2026-10-14 00:42-00:55 — the read's own half, from a process of its own (one `login`, then
  `onlineInfo` on a widening schedule: 60 s ×5, 120 s ×3, 180 s ×3; same device id, same headers,
  and it did not disturb the client - the client stayed `online/tunnelAvailable` throughout). The
  session lived through all five 60-second gaps and through two 120-second gaps, and answered
  `75500002 会话无效` inside the third 120-second gap (+11.0 min, and again at +14.0). The journal
  shows nothing else touching the client in that window (no event, no login), so the death is the
  session's own; the only no-read bound the deployment had was the 16.2-minute one above, and
  whether the reads extended anything or the session simply died at a lifetime of its own was the
  next run's question.
* 2026-10-14 01:00-01:16, the dev image live (`localhost/atrust-quadlet:dev`, built from the tree,
  quadlet pointed at it for the run, client profile and state dir untouched): the cycle emitted
  `session keepalive: code=0 isOnline=True` every ~90 s (01:02:04, 01:03:35, 01:05:05, 01:06:35,
  01:08:05, 01:09:35 - six reads, 90-91 s apart) and then the session answered `75500002 会话无效`
  at 01:11:05 and stayed gone. The login was 01:00:21: **the session lived ~10.7 minutes and the
  reads did not extend it.** The independent probe run died at +11.0 minutes the same way. So
  `onlineInfo` is not the refresh: the engine's session has a fixed lifetime of about ten to eleven
  minutes from its login, and a read only *reports* it. The sibling's candidate -
  `authConfig?needTicket=0`, whose `data.isLogin` is *its* validity check - is what the next
  measurement runs (a login, then that read every 90 s; does it hold past the ~11-minute mark the
  two `onlineInfo` runs died at).
* 2026-10-14 01:17-01:31 — the sibling's own candidate, and the answer. A third session, with
  `authConfig?needTicket=0` every 90 s (the call `zju-connect` refreshes with, whose `data.isLogin`
  is its validity check), answered `code=0 isLogin=1` at +1.5, +3.0, +4.5, +6.0, +7.5 and +9.0
  minutes and `code=0 isLogin=0` at +10.5 - it died on the same clock, and this call answers a dead
  session with `code 0` and `isLogin=0`, not `75500002`. Three sessions, three runs, three
  schedules: **the engine's session has a fixed lifetime of about ten to eleven minutes from its
  login (11.0, 10.7 and 10.5 minutes to the last live answer), and neither cheap read extends it -
  only a full login creates a new one.** The tunnel's own traffic does not stand in: the 01:00-01:16
  run had the probe's real requests running through the tunnel the whole time and the engine's
  session died on schedule beside them, so the two sessions are separate and the datapath keeps the
  client's, not this one.
* 2026-10-14 — the finding is therefore the third deliverable's: the engine's session is a
  ~10-minute one, a recovery can mint a ticket in it only inside that window (the 5.3 s drill of
  2026-10-11 ran 5.1 minutes after a login), and after it the cold path is what a recovery pays (31
  s, ~20 of them the tray's own stop around the token write). No read cadence changes that, so the
  keep-warm code does not land: it would buy a portal read per cycle forever for a session that dies
  anyway. `docs/DESIGN.md` carries the lifetime and both candidates' measurements beside the
  31 s-versus-5.3 s numbers, and the step closes on that record.
* 2026-10-14 01:31:36-01:32:37 — the cold path's own number, live: a forced client-side logout 31.2
  minutes after the engine's login (that session dead since 01:11:05, which the keepalive's own
  reads had reported six times alive and then gone) made the cycle pay `password auth ok` (01:32:06),
  write the tokens after the tray's 20-second SIGTERM budget (01:32:26) and mint from the fresh
  session (01:32:32): `LOGGED_OUT` 01:32:06 → `ONLINE` 01:32:37, **31 seconds end to end** - the same
  number step 14 measured, seen rather than predicted. With that the exit criterion's negative arm is
  live: no keepalive code landed (the read was written, run for 17 minutes and reverted), the
  deployment went back to the published image and the quadlet's `Image=` to
  `ghcr.io/yangtsesu/atrust-quadlet:latest`, and `docs/DESIGN.md` now carries the engine session's
  lifetime beside the 31 s-vs-5.3 s numbers it explains.
