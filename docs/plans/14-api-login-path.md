<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 14 — The API login path

Status: ⬜ not-started
Depends on: — (the sequence is measured; step 12 lands the module this would reuse if it goes first)
Touches: `atrustd/portal.py`, `atrustd/clientapi.py`, `atrustd/__main__.py`, `tests/`, `docs/DESIGN.md`,
`docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

The supervisor's recovery for a dead session is: log in to the portal, write `tid`/`tid.sig` into the
client's cookie store, restart the tray, then drive the client's own window with X11 input
(`uiauto`) until the tunnel comes up. The client's own web workbench does the same login without any
of that, and its calls are reachable - verified live 2026-10-11 (`docs/CLIENT-LOCAL-API.md`, "The
login path, verified"):

1. the engine's portal session mints a ticket - `POST /passport/v1/public/ticketExchange` (the
   engine's cookies, empty body) → `sidTicket` (73 characters);
2. the agent takes it - `POST /v1/service/start {"sidTicket": ...}` → `{"code":0,"message":""}`;
3. the tunnel is up about three seconds later, with the client's own `/v1/service/status` reading
   `online/tunnelAvailable` and `ip route show dev utun7` back to its 30 routes.

No window, no X11, no cookie surgery, no tray restart - the same three calls the workbench's SPA
makes when a user logs in on the portal page.

The one thing the measurement did *not* cover is what a portal that asks for a captcha or a second
factor does on this path: the account in front of this deployment has neither. The step therefore
lands the path behind the existing one (the window stays the fallback), records what a cold
`start` does with the account that exists, and leaves the captcha/second-factor question to the
capture recipe in step 05.

## Deliverables

- ⬜ `portal.py`: `sid_ticket()` - the `ticketExchange` call, with the same headers and session the
  login already uses, returning the ticket or raising `PortalUnreachable`; offline test against a
  fake portal (the request shape, the missing-`data` answer, a non-zero code).
- ⬜ `clientapi.py`: `start(ticket)` - the envelope, the `Referer` gate, a bounded timeout, and the
  `11119054` ("already logged in") answer treated as success, since that is what an online client
  answers.
- ⬜ `cycle()`: the dead-session branch tries the API path first - portal login (already there) →
  `sid_ticket()` → `start()` → the existing `wait_for_tunnel()` - and falls back to the current
  token-plus-window path when any step fails or the tunnel does not come up within its bound. Which
  path ran goes into the transition detail and the journal; `uiauto` is not removed.
- ⬜ Tests: the fallback decision (start fails / start succeeds / tunnel does not come up), and the
  `start` answer handling (`code 0`, `11119054`, a schema error, a timeout) - all offline.
- ⬜ Live acceptance: one controlled recovery through the API path on the live container (the way the
  measurement above did it, but driven by the supervisor), with the journal showing the path and the
  time from `LOGGED_OUT` to `ONLINE`; then one forced failure (an invalid ticket) showing the
  fallback still reaches `ONLINE`.
- ⬜ The measurement of a cold `start`: what the portal answers when the account's session is cold
  (a fresh client, no cookies) - `start` with a ticket minted from a fresh engine login, recorded
  here. If it asks for a captcha or a factor, that answer is the finding and the fallback stays the
  primary path.
- ⬜ `docs/DESIGN.md`: "How the login works" and "The supervisor" say which path brings the tunnel up
  and what the window is still for.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ Live: the API path recovers one session and the fallback recovers the forced failure, both with
  their times in this file.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-11 — written after the live measurement: `logout` (measured to work with
  `{"type":"force","guid":...,"addr":...}`) put the client at `logout`/`tunnelUnavailable` with no
  routes, the engine's own login minted a ticket, and `start` brought the tunnel back in three
  seconds - with the event channel showing `logout` → `enterInitial` → `resourceReady: 0` and then
  `login` → `enterOnline` → `enterOnlineRun` → `tunnelStatus` → `status` two seconds later. This is
  the first path this project has that logs the client in without its window.
