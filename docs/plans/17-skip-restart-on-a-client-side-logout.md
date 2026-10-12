<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 17 — Skip the client restart when the client itself says it is logged out

Status: ⬜ not-started
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

## Deliverables

- ⬜ The decision, recorded here: which view skips the branch (`logout` with `tunnelUnavailable`, and
  nothing else), and what the restart window's own answer means - the client's service is unreachable for
  ~2-4 s around a restart (measured live), so "no answer" must keep the branch exactly as it is today.
  `otherSdpCOffline`/`otherSdpCLogin`, `online`, an API that is switched off (`None`) and an empty answer
  all keep it too.
- ⬜ `cycle()`: the branch consults the client's own view before it calls `tokens.stop_client()`, and skips
  both the restart and its tunnel wait when the client itself reports it is logged out; the journal and the
  transition detail say the branch was skipped and on what (`client logout/tunnelUnavailable; not
  restarting it`), so the next line in the log is the login path's.
- ⬜ The same cycle does not ask the portal for a login twice: `_api_login`'s fresh login and the window
  path's own `refresh_tokens` both run, and the second is refused (`75500006 当前账号已在线，无需重复上线`,
  measured live 2026-10-12 - 0.3 s after the first had succeeded), which makes the journal read like a
  failed login although the recovery landed. Which of the two owns the login in a cycle the ticket path has
  already reached is the decision; it is the same branch's work as the skip above.
- ⬜ Tests (`tests/test_cycle_pacing.py`): the skip (the view reports `logout`), the keeps (no API, the view
  unreachable, the view reports `online`/`tunnelUnavailable`), and that the skipped cycle reaches the
  ticket path in that same cycle instead of returning to the backoff.
- ⬜ Live, on the dev image, quoted here: one controlled client-side logout with the supervisor's own
  journal - `LOGGED_OUT` to `ONLINE` in one line and no `web session is alive` restart in between -
  against step 14's 23:49:26.4 -> 23:51:56.2. This costs a portal session, so it is its own drill and its
  own commit.
- ⬜ `docs/DESIGN.md`: the supervisor section says the view can decide this one branch, and what the
  restart branch is still for (a session the client's own view does not call ended).

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ Live: a controlled client-side logout reaches `ONLINE` in ≲15 s, with no restart branch in the
  journal (step 14 measured 2.5 minutes for the same state).
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-12 — opened, tracked where it belongs: the candidate existed only inside step 12 ("What may act on
  it (the decision)") and step 14 ("The restart detour, measured again" / "Two follow-ups the numbers
  suggest"), both closed, so the work was one `git log` away from being retired with them. The numbers to
  beat are step 14's drill: `ONLINE -> DEGRADED` 23:49:26.4, `DEGRADED -> LOGGED_OUT` 23:51:50.8 (the tray's
  own stop and the 120 s tunnel wait that could not succeed live in that gap) and `LOGGED_OUT -> ONLINE`
  23:51:56.2 (the ticket path, five seconds).
* 2026-10-12 — a second item, from step 18's live recreations: the fresh login `_api_login` runs is repeated
  by the window path in the same cycle, and the second attempt comes back refused (`75500006 当前账号已在
  线，无需重复上线`, 0.3 s after the first had succeeded). It is recorded here because the branch order this
  step owns is what produces the repeat, and it lands with the skip rather than as a step of its own.
