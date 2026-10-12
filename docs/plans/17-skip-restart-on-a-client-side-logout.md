<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 17 — Skip the client restart when the client itself says it is logged out

Status: ✅ done
Depends on: step 12 (the candidate, and its measurement) and step 14 (the ticket path, and the drill that
priced the branch)
Touches: `atrustd/__main__.py`, `tests/test_cycle_pacing.py`, `docs/DESIGN.md`, `docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

The `web session is alive but the tunnel is not` branch restarts the client and waits up to 120 s for the
tunnel before anything else runs. A client-side logout is not something a restart repairs - the portal has
ended that session, and the client's own view says so from its first sample (`logout`/`tunnelUnavailable`
in the same 2 s sample the data plane went down, step 12's drill). Step 14's drill priced the branch:
`ONLINE -> DEGRADED` at 23:49:26.4, the restart, the tray's own stop and the 120 s tunnel wait spent by
23:51:50.8, after which the ticket path recovered the same session in 5.3 s. That gap - 2.2 minutes - is
the largest term left in an end-to-end recovery that is not the portal's own latency, and the skip is the
one candidate step 12's measurement supports.

Nothing tracks it today: it is recorded in step 12's "What may act on it" and in step 14's "Two follow-ups
the numbers suggest", both of which are closed files, and the plan index had no row for it.

## The decision (2026-10-13)

The branch is skipped for exactly one view, and nothing else: `logout` with `tunnelUnavailable` -
the portal has ended the session and the client says so itself, which is the state a restart cannot
repair (2.4 minutes measured on 2.5.16.41, the ticket path then recovering in 5.4 s). Everything
else keeps the branch exactly as it is today:

| the client's own view | the branch |
|---|---|
| `logout`/`tunnelUnavailable` | skipped; the login path (ticket, then window) runs in the same cycle |
| anything else it answers (`online`/`tunnelUnavailable`, `otherSdpCOffline`, `otherSdpCLogin`, a `logout` whose tunnel reads anything but `tunnelUnavailable`) | kept |
| the read failed (`{'error': ...}`, the service unreachable) | kept |
| no view at all (the API is switched off, `ATRUST_CLIENT_API=0`) | kept |

A failed or missing read keeps it because the client's own service is unreachable for ~2-4 s around
a restart (measured live) and a status the client did not answer is not a statement about its
session; only a positive `logout` is. The recorded view of the DEGRADED transition *is* the sample -
`note()` already reads the client at the transition and returns the record - so the decision costs
no extra request and sees exactly what `state.json` carries.

Who owns the portal login: the cycle does. `_api_login` runs the fresh login when the engine's
session is cold (it is the window path's ground work either way), and the window path's own
`refresh_tokens` right after it was measured to be refused (`75500006 当前账号已在线，无需重复上线`,
0.3 s after the first had landed, 2026-10-12), which made the journal read like a failed login
although the first one stood. So a cycle the ticket path has logged in runs the window with that
session and does not ask the portal again; a cycle where the ticket path never ran the login keeps
today's refresh exactly, token rotation and all.

## Deliverables

- ✅ The decision, recorded here ("The decision", 2026-10-13): which view skips the branch (`logout` with
  `tunnelUnavailable`, and nothing else), what a failed or missing read means (the service is unreachable
  for ~2-4 s around a restart, so only a positive `logout` sends the branch aside), and who owns the
  portal login in a cycle the ticket path has already logged in (the cycle does; the window reuses it).
- ✅ `cycle()`: the branch consults the client's own view before it calls `tokens.stop_client()`, and skips
  both the restart and its tunnel wait when the client itself reports it is logged out; the journal and the
  transition detail say the branch was skipped and on what (`client logout/tunnelUnavailable; not
  restarting it`), so the next line in the log is the login path's.
- ✅ The same cycle does not ask the portal for a login twice: `_api_login` returns a `TicketAttempt`
  carrying whether it ran the fresh login itself, and the window path reuses that session instead of
  calling `refresh_tokens` again (`75500006 当前账号已在线，无需重复上线`, measured live 2026-10-12 - 0.3 s
  after the first had succeeded); a cycle where the ticket path never logged in keeps today's refresh
  exactly. The ownership is recorded in "The decision".
- ✅ Tests (`tests/test_cycle_pacing.py`): the skip (the view reports `logout`), the keeps (no API, the view
  unreachable, the view reports `online`/`tunnelUnavailable`, a `logout` with another tunnel), that the
  skipped cycle reaches the ticket path in that same cycle instead of returning to the backoff, and that
  the window path reuses the login the ticket path ran. The skip's condition was mutation-checked:
  dropping the tunnel half of it fails exactly the near-miss keep.
- ✅ Live, on the dev image, quoted here: one controlled client-side logout with the supervisor's own
  journal - `LOGGED_OUT` to `ONLINE` in one line and no `web session is alive` restart in between -
  against step 14's 23:49:26.4 -> 23:51:56.2. This costs a portal session, so it is its own drill and its
  own commit.
- ✅ `docs/DESIGN.md`: the supervisor section says the view decides this one branch - `logout` with
  `tunnelUnavailable` skips the restart and its wait, measured 5.4 s against 2.4 minutes - the recovery
  walk and the "measured limits of the way in" paragraph carry it, and the restart branch is still what
  repairs a session the client's own view does not call ended.

## The measurement (live, 2026-10-13, the dev image with this change, a forced logout)

A `POST /v1/service/logout` on the running container (`{"code":0,"message":"OK"}`), the client's own
logout event waking the cycle:

```
01:48:13.619 INFO atrustd: woke on client event(s): leaveOnlineRun, leaveOnline, logout, enterInitial
01:48:13.622 INFO atrustd: tunnel interface is up but routes are not installed yet; waiting up to 30s
01:48:43.686 INFO atrustd: ONLINE -> DEGRADED (tunnel not usable); client logout/tunnelUnavailable user=<user> since=2026-10-13 01:46:35
01:48:43.725 INFO atrustd: client logout/tunnelUnavailable; not restarting it
01:48:43.768 INFO atrustd: DEGRADED -> LOGGED_OUT (the client has to log in again); client logout/tunnelUnavailable user=<user> since=2026-10-13 01:46:35
01:48:44.049 INFO atrustd: the client took the ticket; waiting up to 60s for the tunnel
01:48:49.138 INFO atrustd: LOGGED_OUT -> ONLINE (tunnel up after the ticket login); client online/tunnelAvailable user=<user> since=2026-10-13 01:46:27
```

`DEGRADED` to `ONLINE` is 5.4 s, there is no `web session is alive` line and no restart anywhere in
the window; `stop_client`/`wait_client` never ran (one orphan reaped at the wake, nothing else). The
30 s before the transition are the pre-existing `TUNNEL_GRACE` wait - the client's logout event woke
the cycle while its tunnel interface was still up with the routes gone - not this branch. The same
drill on the published image before the change (Progress log) took 2.5 minutes from `DEGRADED` to
`ONLINE`, 2.4 of them inside the restart branch. No `portal login attempt failed` line either: the
ticket path's own fresh login stood and the window path reused it, which is this step's one-login
rule seen live.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` (123) and `reuse lint` (92/92) stay green.
- ✅ Live: a controlled client-side logout reached `ONLINE` 5.4 s after `DEGRADED` with no restart branch
  in the journal (2.5 minutes for the same state before the change, 2.4 of them inside the branch), quoted
  under "The measurement".
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-12 — opened, tracked where it belongs: the candidate existed only inside step 12 ("What may act on
  it (the decision)") and step 14 ("The restart detour, measured again" / "Two follow-ups the numbers
  suggest"), both closed, so the work was one `git log` away from being retired with them. The numbers to
  beat are step 14's drill: `ONLINE -> DEGRADED` 23:49:26.4, `DEGRADED -> LOGGED_OUT` 23:51:50.8 (the tray's
  own stop and the 120 s tunnel wait that could not succeed live in that gap) and `LOGGED_OUT -> ONLINE`
  23:51:56.2 (the ticket path, five seconds).
* 2026-10-12 — a second item, from step 18's live recreations: the fresh login `_api_login` runs is repeated
  by the window path in the same cycle, and the second attempt comes back refused (`75500006 当前账号已在线，
  无需重复上线`, 0.3 s after the first had succeeded). It is recorded here because the branch order this
  step owns is what produces the repeat, and it lands with the skip rather than as a step of its own.
* 2026-10-13 — the numbers to beat, re-measured on client 2.5.16.41, the published image, a forced
  `POST /v1/service/logout`: `ONLINE -> DEGRADED (tunnel not usable); client logout/tunnelUnavailable` at
  01:25:15.3, the same `web session is alive but the tunnel is not; restarting the client` branch, `DEGRADED
  -> LOGGED_OUT` at 01:27:39.7 (2.4 minutes: the tray's own stop plus the 120 s tunnel wait that cannot
  succeed), `the client took the ticket` and `LOGGED_OUT -> ONLINE (tunnel up after the ticket login)` at
  01:27:45.1 — the recovery itself 5.4 s, the branch's detour 2.4 minutes. So the branch still costs the
  same on the new client, and the client's own view said `logout`/`tunnelUnavailable` in its first sample
  after the logout, which is the skip's candidate. The drill is quoted in `base/README.md`.
* 2026-10-13 — every item is in and the step closes. The skip landed with its decision, its keeps and its
  tests (the condition mutation-checked), the one-login rule took the loose return type out of `_api_login`
  and gave the window path a session instead of a refused second login, and the drill above is the live
  half: 5.4 s from `DEGRADED` to `ONLINE`, no restart in the window. `docs/DESIGN.md`'s supervisor section
  and the way-in paragraph now say which branch the view decides and what the restart is still for.
* 2026-10-13 — the skip is in and the drill above is its live half: the branch stands aside on the
  client's own `logout`/`tunnelUnavailable`, the cycle pays the ticket wait only and lands `ONLINE` 5.4 s
  after `DEGRADED` (against 2.5 minutes for the same state before the change, 2.4 of them inside the
  branch), and the window path did not ask the portal for a second login.
