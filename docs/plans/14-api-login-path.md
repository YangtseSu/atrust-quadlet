<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 14 — The API login path

Status: ✅ done — 2026-10-11, landed and measured live (the supervisor's own recovery through the
ticket path: `LOGGED_OUT` 23:51:50.8 → `ONLINE` 23:51:56.2, and a cold-engine-session one 31 s end
to end; the window fallback recovered the forced failure)
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

- ✅ `portal.py`: `sid_ticket()` - the `ticketExchange` call, with the same headers and session the
  login already uses, returning the ticket or raising `PortalUnreachable`; offline test against a
  fake portal (the request shape, the missing-`data` answer, a non-zero code).
- ✅ `clientapi.py`: `start(ticket)` - the envelope, the `Referer` gate, a bounded timeout, and the
  `11119054` ("already logged in") answer treated as success, since that is what an online client
  answers.
- ✅ `cycle()`: the dead-session branch tries the API path first - portal login (already there) →
  `sid_ticket()` → `start()` → the existing `wait_for_tunnel()` - and falls back to the current
  token-plus-window path when any step fails or the tunnel does not come up within its bound. Which
  path ran goes into the transition detail and the journal; `uiauto` is not removed.
- ✅ Tests: the fallback decision (start fails / start succeeds / tunnel does not come up), and the
  `start` answer handling (`code 0`, `11119054`, a schema error, a timeout) - all offline.
- ✅ Live acceptance: one controlled recovery through the API path on the live container (the way the
  measurement above did it, but driven by the supervisor), with the journal showing the path and the
  time from `LOGGED_OUT` to `ONLINE`; then one forced failure (an invalid ticket) showing the
  fallback still reaches `ONLINE`.
- ✅ The measurement of a cold `start`: what the portal answers when the account's session is cold
  (a fresh client, no cookies) - `start` with a ticket minted from a fresh engine login, recorded
  here. If it asks for a captcha or a factor, that answer is the finding and the fallback stays the
  primary path.
- ✅ `docs/DESIGN.md`: "How the login works" and "The supervisor" say which path brings the tunnel up
  and what the window is still for.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` and `reuse lint` stay green (112 tests; `reuse lint` covers the new `tests/test_portal.py`).
- ✅ Live: the API path recovers one session and the fallback recovers the forced failure, both with
  their times in this file ("The measurements" below).
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## The measurements (live, 2026-10-11, dev container)

Three recoveries were observed on the live container (`localhost/atrust-quadlet:dev`, client
2.5.16.30) with this step's code in the image; private values are placeholders.

**The ticket path recovers a session (the exit criterion).** A controlled client-side logout
(`POST /v1/service/logout {"type":"force"}`, through `clientapi.ClientAPI.session`) put the client at
`logout`/`tunnelUnavailable`. The supervisor's own cycle then walked:

| time | line |
|---|---|
| 23:49:26.4 | `ONLINE -> DEGRADED (tunnel not usable)` - woken by the client's own `logout` event |
| 23:49:26.4 | `web session is alive but the tunnel is not; restarting the client` - the engine's portal session was still alive, so the restart branch ran first (see "the detour" below) |
| 23:51:50.8 | `DEGRADED -> LOGGED_OUT (the client has to log in again)` |
| 23:51:50.9 | `ticketExchange minted a 73-character sidTicket` |
| 23:51:51.1 | `the client took the ticket; waiting up to 60s for the tunnel` |
| 23:51:56.2 | `LOGGED_OUT -> ONLINE (tunnel up after the ticket login)` |

Five seconds from `LOGGED_OUT` to `ONLINE`, no window opened, `uiauto` never called; the client's
events (`leaveInitial`, `login`, `enterOnline`, `enterOnlineRun`, `tunnelStatus`, `status`) arrived
within the same second as `start`.

**A cold engine session: the fresh login first, then the same path.** A second controlled logout,
with the engine's portal session gone cold, made the cycle log in again:

| time | line |
|---|---|
| 23:53:46.6 | `DEGRADED -> LOGGED_OUT (the client has to log in again)` |
| 23:53:46.9 | `password auth ok (next=auth/authCheck)` - a fresh engine login, no captcha asked |
| 23:53:47.0 | `portal login ok, tokens: tid(36 chars),tid.sig(43 chars)` |
| 23:54:07.3 | `wrote tid,tid.sig into ...` (the tray's own stop spent its 20 s SIGTERM budget first) |
| 23:54:12.4 | `ticketExchange minted a 73-character sidTicket` |
| 23:54:17.7 | `LOGGED_OUT -> ONLINE (tunnel up after the ticket login)` |

31 s end to end, 5.5 of them the ticket work; the rest is the tray's own stop and restart around the
token write. That is the cold-start answer: on this account and portal the fresh login and the mint
both answer `code 0` - no captcha, no factor; the engine reuses the client profile's stored
`tid`/`tid.sig` first, as it always does, and the captcha question stays with step 05's capture
recipe.

**The forced failures, and the fallback.** Three refusals were seen live, all read as failures and
fallen back on:

* an empty envelope guid (a client that had just started): `start` answered
  `Invalid schema: #/properties/guid` (23:44:30). This was the step's first live run, and it found
  the gap; the guard that skips the attempt until the client publishes a guid went into the cycle
  commit with its own test. The window path then reached `LOGGED_OUT -> ONLINE (tunnel up after the
  client login)` at 23:47:29, 9 s after the window login submitted.
* a stale ticket, measured directly against the live client (logged out, guid set): `75500304
  当前票据已失效`.
* an empty ticket: `10000001 invalid_param in body`.

**The restart detour, measured again.** The `web session is alive but the tunnel is not` branch runs
before the ticket path whenever the engine's portal session is still alive. In the first drill it
cost 23:49:26 → 23:51:50 - 2.2 minutes of the tray's stop, its restart and the 120 s tunnel wait
that could not succeed, because a client-side logout is not something a restart repairs - before the
ticket path recovered the same session in five seconds. That is the skip-the-restart candidate step
12 recorded; it still needs its own change and its own measurement.

### Faster or slower, against the old path

The same container, the same client states - which path wins depends on whether the ticket path can
run at all:

| case | old path (window) | this step | net |
|---|---|---|---|
| tray up, session gone, engine session alive: the ticket path (23:51) | - | `LOGGED_OUT` 23:51:50.8 → `ONLINE` 23:51:56.2 = 5.3 s | **faster** |
| the window fallback in that same client state (23:44 and 23:47) | submit → online 8.8-8.9 s, plus X11/`uiauto` | - | the ticket path is ~3.5-4 s ahead of it, window-free |
| a cold engine session, a fresh login first (23:53) | the login, the token write and the tray's restart are the same work | 31 s end to end, 5.5 s of it the ticket work | level |
| a container cold start, where the ticket path cannot run (no `sdpcguid`) | 13.5 s (23:44, an equivalent restart) | 54.4 s (23:46) | **slower, ~40 s**: ~20 s are this step's own bounded waits (10 s for the service and 10 s for the guid - a fresh client publishes none for 35 s+), the rest is the portal's own `publish_apps` latency (4 s in one run, 24 s in the other), paid by both paths |

What did not move: the `web session is alive` restart branch (2.2 minutes whenever the engine's
session is alive), the tray's own ~20 s stop around the token write, and the portal's call latency.
Those - not the login call itself - still dominate an end-to-end recovery; this step shortened the
login part of it (~9 s of window work to ~5 s of HTTP, no X11).

Two follow-ups the numbers suggest, each needing its own change and measurement: the skip-restart
candidate step 12 recorded, and a tighter guid wait - a tray restart publishes the guid within ~5 s
while a fresh container's client does not for 35 s+, and nothing measured so far tells the two
apart, so every cold start pays the ten-second bound for the chance to win a tray restart.

## Progress log

* 2026-10-11 — written after the live measurement: `logout` (measured to work with
  `{"type":"force","guid":...,"addr":...}`) put the client at `logout`/`tunnelUnavailable` with no
  routes, the engine's own login minted a ticket, and `start` brought the tunnel back in three
  seconds - with the event channel showing `logout` → `enterInitial` → `resourceReady: 0` and then
  `login` → `enterOnline` → `enterOnlineRun` → `tunnelStatus` → `status` two seconds later. This is
  the first path this project has that logs the client in without its window.
* 2026-10-11 — implementation landed as three commits (`feat(portal): mint the session ticket the
  client's own login takes`, `feat(clientapi): hand the client the session ticket`, `feat(atrustd):
  recover a logged-out client through its own calls`), with `tests/test_portal.py` (new, a stub-portal
  socket), the `start` cases in `tests/test_clientapi.py` and the fallback cases in
  `tests/test_cycle_pacing.py`. Deviation from the `Touches:` line: `docs/CLIENT-LOCAL-API.md` also
  changed - its `start` row, its "not exercised" table and its candidate list all said the handover
  was untested and nothing used the interface, and this step made both untrue.
* 2026-10-11 — the first live run (image rebuilt, container recreated) exercised the new path and
  found the empty-guid gap described above; the fix went into the cycle commit, so the delivered
  code is the version that skips the attempt and waits ten seconds for the guid.
* 2026-10-11 — the measurements above, then `docs/DESIGN.md` (the client-login section now lists the
  ticket path first and the window as the fallback, with the measured limits; the supervisor section
  says which path ran goes into the transition and the hand-over detail). Offline at the close: 112
  tests green, `reuse lint` 89/89. Closed with this file's markers and the index row in one commit.
* 2026-10-12 — appended after the close, from the same container's numbers: the faster-or-slower
  accounting is now "Faster or slower, against the old path" above - the ticket path is faster
  (5.3 s against the window fallback's 8.8-8.9 s in the same client state, and no X11), level when
  a fresh login comes first, and up to ~20 s of its own bounded waiting slower when a container cold
  start forces the fallback. The end-to-end stays dominated by the restart branch, the tray's token
  stop and the portal's own latency - two follow-ups are named above for later steps.
