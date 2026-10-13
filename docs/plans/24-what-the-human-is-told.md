<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 24 — What the human is told

Status: ✅ done
Depends on: — (the live half repeats step 04's hand-over drill; the rest is offline)
Touches: `atrustd/uiauto.py`, `atrustd/__main__.py`, `atrustd/vnc.py`,
`tests/test_page_naming.py`, `tests/test_cycle_pacing.py`, `README.md`
(each `- ⬜` item below is one commit)

## Goal

The hand-over says one thing: the client window is not showing the password form. The client's own log
carries the SPA's console - the `checkCode` request `uiauto` already reads for its captcha marker,
`getHistoryAddr`, `final route:login` (`docs/DESIGN.md`) - and the second-factor pages have names of
their own (`totpAuth`, `smsAuth`, `page_auth_trust_terminal`, step 05). `EZ4Connect` classifies the
analogous line stream into typed events precisely so the human is told which prompt it is
([`coreoutputparser.cpp#L5-L81`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/coreoutputparser.cpp#L5-L81)).
The hint can name the page for the same cost it already pays to read the file.

Two README paragraphs are the other half of what a human reads:

* a host-side TUN proxy (Clash and friends) must send the portal host and the intranet ranges
  **direct**: the container's own traffic leaves through the host stack, so a proxy that captures it
  and loops it back into the same tunnel breaks both sides - `EZ4Connect` documents the same rules for
  its own host
  ([`docs/ADVANCED_USAGE.md`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/docs/ADVANCED_USAGE.md)),
  `zju-connect` for its own
  ([`docs/service.md`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/docs/service.md));
* the client's `sdpcguid` is one per image and host (measured 2026-10-11, `docs/DESIGN.md`), so a
  portal that binds a "trust this terminal" grant to it sees every container built from the image on
  that host as the same terminal. The grant's own binding is an inference - no portal here grants one -
  and the paragraph must say so rather than assert it.

And one thing the deployment should be told before it is surprised:
`ATRUST_PROBE_DISCOVER=0` with no `ATRUST_PROBE_TARGET` sends no traffic at all, and a tunnel that
carries only `CONNECT`s expires in ~10.3 minutes against over an hour with real requests (measured
2026-10-09). The combination is a session that expires by configuration, and today neither the README
row nor the daemon says a word about it.

## Deliverables

- ✅ The `NEED_VNC` reason and the state detail carry the last page/route token the client's own log
  published, best-effort beside the captcha marker, and `log_since` re-reads a tail that does not end
  on a newline with a small overlap, so a marker split by the writer is not lost.
- ✅ Tests: the page-token picker over recorded tails (a token, a marker split across the read
  boundary, a tail with neither - which degrades to today's text).
- ✅ `run_daemon` warns once when `ATRUST_PROBE_DISCOVER=0` and no target is configured, naming the
  expiry measurement; the README row for the switch says the same.
- ✅ `README.md`: the host-proxy paragraph beside the Zero Omega one (the portal host and the intranet
  ranges on the host proxy's direct list, and why a capture loops).
- ✅ `README.md`: the device-identity paragraph (the guid measurement, the inference marked as one).
- ✅ Live: one hand-over whose hint names the page, with the token in the journal - step 04's drill
  repeats it; if a second-factor page is what the portal asks for, the same day step 05 unblocks.
  (Run 2026-10-13/14 against a local build of this tree; the hint's own first line is in the
  `## Progress log`.)

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` and `reuse lint` stay green (172 tests, 2026-10-13).
- ✅ The live hand-over is recorded in `## Progress log` with the hint's own text.
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened by the split of the survey archived at
  `docs/archive/2026-10-13-atrust-reimplementation-lessons.md` (then `B07`): the page-name candidate
  and the two documentation notes are its review's.
* 2026-10-13 — a pointer from step 21: the `NEED_VNC` reason is no longer built in one place.
  `__main__.py` now hands over from two shapes - `_refused_reason()` (a credential the portal
  refused, with `wrong-password`/`rate-limited` stopping the engine's logins; the window never
  submitted there, so there is no page to name) beside the captcha/window reasons this step extends -
  and `vnc.py` is untouched by that (the reason is still just a string into `vnc.hint`). The
  page-name work has to compose with both and keep both shapes in the tests.
* 2026-10-13 — the offline half landed in five commits (the page in the reason, the state detail and
  the hint; the tests; the discover warning with its README row; the two README paragraphs). The one
  `- ⬜` left is the live hand-over: it repeats step 04's drill - the deployment's session goes down
  for the length of the drill and a human is needed at VNC - so it is a window with the operator,
  not a cycle. What the offline half was measured against:
  * the token's shape and its depth: the SPA's router guard writes `final route:<token>` into the tray
    log (live client log 2026-10-13: 167 `login`, 59 `app_center`, 34 `connectSetting`), and the
    newest route line sits far behind the write frontier - ~200 KB of console after it, 14 minutes
    into a session's 2 MB day-file - so the picker reads the whole file (18.6 MB worst case here:
    47 ms read + 31 ms regex, measured) instead of a bounded tail that would usually miss it;
  * replayed on the recorded hand-over of 2026-10-08 (the drill step 04 quotes: the log up to its
    `checking graph code` line) the picker says `login`, i.e. a hand-over at that moment would have
    named the page. A read since the cycle's own marker would have found nothing - the last route
    line was ~2.5 minutes older than the captcha - which is why the picker reads the file, not the
    marker;
  * in the live container (a `podman cp` of the tree to `/tmp`, a practice state dir, one
    `podman exec`): `run_daemon --once` reached `ONLINE` (`utun7 2.0.0.1/24; 30 route(s) via utun7;
    probe ok (HTTP/1.1 200)`), `uiauto.last_page` read `app_center` off the client's own log, and the
    composed hint's first line was `NEED_VNC: the portal is asking for the graphical captcha; answer
    it in the client window over VNC; the client's own log last named the page "app_center"`;
  * the warning, same container, practice state dir, `ATRUST_PROBE_DISCOVER=0` with the target
    emptied: `ATRUST_PROBE_DISCOVER=0 and no ATRUST_PROBE_TARGET: no request is sent through the
    tunnel, so nothing keeps the portal session alive - … name a target or leave discovery on`, said
    once, and the cycle was `ONLINE` off the interface and its routes alone (`…; 30 route(s) via
    utun7`, no probe detail). The deployment's own environment names a target, so the warning does
    not fire there;
  * `python3 -m unittest discover -s tests` (172 tests) and `reuse lint` green;
  * the tests live in `tests/test_page_naming.py` rather than the two files the step projected: the
    log tail, the picker and the clause the hint carries are one concern with their own shapes, and
    the `Touches:` line above now says so.
* 2026-10-13 — the runbook for the live window, so it costs one portal attempt and one outage: stop
  `atrust.service`; back up `~/.config/atrust.env` and `~/.atrust-data`; point the env at a spare
  account with a deliberately wrong password and start it; the portal's first answer is the captcha
  demand (or the wrong-password row), the hand-over follows, and the evidence is
  `$ATRUST_STATE_DIR/NEED_VNC`'s first line plus the journal's `human action required` line - both
  must name the page. The human then finishes the login in VNC (`NEED_VNC -> ONLINE`), and the env
  and the profile go back from the backup. If the portal asks for a second factor instead of the
  captcha, this same window is what step 05 unblocks on.
* 2026-10-13/14 — **the drill ran, and this is what it said.** It ran against a local build of this
  tree (`podman build -t localhost/atrust-quadlet:dev .` from the tree, fitted to the unit with a
  temporary `atrust.container.d/10-drill-image.conf` drop-in, removed afterwards), because the
  deployed `:latest` predates the change: the *first* hand-over of the drill ran that image and its
  hint named no page - so the clause is visibly the new code's. The operator's call on the account:
  the deployment's own, with the client's own cookie store renamed aside
  (`AppCache/Cookies` → `Cookies.drill-bak`, which is what forces a fresh login; the client wrote a
  fresh store with the human's login, and the renamed one was deleted after the drill).
  `~/.config/atrust.env` (unmodified) and the pre-drill `state.json` sit in
  `~/atrust-drill-20261013-235944/`. Times are the container's (UTC):
  * `16:04:50` the engine's own login was refused by the captcha:
    `portal requires the graphical captcha: 图形验证码已超时，请重试` (`code=75500000` - the class the
    gate in front of the password check answers with, step 21's measurement);
  * `16:04:57` `uiauto` submitted the client window:
    `client window: submitted: credentials submitted [page=login]`;
  * `16:05:58` the hand-over. `state.json`'s detail:
    `code=75500000 class=captcha message=图形验证码已超时，请重试; the ticket login: no live portal
    session to mint a ticket from; the client's own log last named the page "login"`, and the hint's
    first line, verbatim:
    `NEED_VNC: the portal is asking for the graphical captcha; answer it in the client window over
    VNC; the client's own log last named the page "login"` - the token is the SPA's own route line
    read off the live log in that cycle (the same `login` the 2026-10-08 replay predicted), and it
    reached the hint file, the journal's `human action required (…)` line and the state detail;
  * the human half: the captcha was answered in the client window; the client's own events (`login`,
    `enterOnline`, `enterOnlineRun`, `tunnelStatus`) woke the cycle and `16:06:53`
    `NEED_VNC -> ONLINE (tunnel up after human action)` followed - 55 s after the hint - with the hint
    file and `captcha.jpg` gone and the probe answering `HTTP/1.1 200` through the tunnel's 30 routes;
  * the deployment went back to `ghcr.io/yangtsesu/atrust-quadlet:latest` (drop-in removed), where the
    client resumed its own session: `LOGGED_OUT -> ONLINE (tunnel up after the client login)`, probe
    `ok`.
