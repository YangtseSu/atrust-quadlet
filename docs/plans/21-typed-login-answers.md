<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 21 — The portal's and the agent's answers, classified

Status: ⬜ not-started
Depends on: — (the offline half has no prerequisite; the live drill that captures a wrong password's
code needs a portal whose password check is not gated behind the graphical captcha - the 2026-10-10
drill showed the portal's counter moves only after a human has answered the captcha)
Touches: `atrustd/portal.py`, `atrustd/clientapi.py`, `atrustd/__main__.py`, `atrustd/vnc.py`,
`tests/test_portal.py`, `tests/test_cycle_pacing.py`, `docs/DESIGN.md`, `docs/CLIENT-LOCAL-API.md`
(each `- ⬜` item below is one commit)

## Goal

Two things the supervisor leans on are prose. The captcha is `CAPTCHA_HINTS` matched against the
portal's message, and a failed login is read by a human out of `code=… message=…` in the journal. The
same graphical-captcha demand reached the client's own log in English (`The characters has expired.
Please try again`) while the engine's own login answered `图形验证码已超时，请重试` - `CAPTCHA_HINTS`
matches the second and none of the first - and the portal publishes the better signal as a *field*:
`graphCheckCodeEnable` in the `auth/psw` data, which the sibling reimplementation of this protocol
family returns as the captcha answer itself
([`auth/psw.go#L99-L111`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/psw.go#L99-L111)).

The rest of the family is typed there, and decided per class: `10000004`/`75500002` are
`ErrSessionInvalid` while every other `authConfig` failure is retried
([`auth/request.go#L114-L117`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/request.go#L114-L117));
`EZ4Connect` pins its own classification of the same family as one tested table
([`coreoutputparser.cpp#L5-L81`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/coreoutputparser.cpp#L5-L81)
+ [`tests/coreoutputparser_test.cpp#L24-L38`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/tests/coreoutputparser_test.cpp#L24-L38)).

Two decisions read that vocabulary and are why this step exists:

* a redundant login is refused with `75500006 当前账号已在线，无需重复上线` (measured 2026-10-11; the
  portal keeps the account online for ~24 minutes after a client-side logout) - today the cycle
  carries that as a note beside a login it already ran, not as a class it decided with;
* a wrong password is **counted** by the portal. The one decrement the 2026-10-10 drill saw (10 → 9)
  came after the human answered the captcha, and the row that carries it (`The username or password is
  incorrect. You still have N attempts left`) is prose. Today every cycle spends two of the account's
  attempts (`refresh_tokens` and `uiauto`'s own submit) and nothing stops the loop: a wrong password
  in the env file cannot become right without a restart, so every repeat is an attempt burned for
  nothing, at the exponential backoff, forever.

## Deliverables

- ⬜ `portal.py`: an answer-class table for the portal - `session-invalid` (`75500002`, `75500001`,
  and `10000004` from the sibling's own list), `already-online` (`75500006`), `captcha`
  (`data.graphCheckCodeEnable` first, `CAPTCHA_HINTS` second, `75500000` as the code the same demand
  arrives as once the attempt went stale), `wrong-password`, `rate-limited` - with
  `tests/test_portal.py`'s recorded answers replayed through it.
- ⬜ `clientapi.py`: the agent's answers keep a table of their own (its codes are a different space:
  `11119054` already logged in, `75500304` stale ticket, `10000001` invalid param, `11119003`,
  `11112002`, `11119064`), carried beside the code by `StartResult`/`ClientStatus`; the schema
  refusal (`Invalid schema: #/properties/guid`) stays the string it is.
- ⬜ The supervisor decides on classes: `LOGGED_OUT_CODES` and the captcha string test in
  `__main__.py` are replaced by the table, and the journal, `state.json` and the transition detail
  carry the class beside the code (`code=75500006 class=already-online`).
- ⬜ The retry gate: a `wrong-password` or `rate-limited` class ends the login attempts until the
  tunnel is up or the daemon restarts - no `refresh_tokens`, no `uiauto` submit - and the cycle goes
  to `NEED_VNC` with the portal's own row (its counter included when it parses) in the hint beside
  `atrustd --login-probe`, which stays the human's own explicit attempt.
- ⬜ Live: the wrong-password row's *code* captured into the table (a captcha-free portal; on a
  captcha portal the same row is what the client's log shows once a human answered), the gate seen to
  stop the loop, and the portal's counter showing no more attempts than the human spent.
- ⬜ `docs/DESIGN.md` says what the supervisor decides on and `docs/CLIENT-LOCAL-API.md` carries the
  codes as classes.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green; every recorded answer
  replays through the tables offline.
- ⬜ The live drill is in `## Progress log` with the captured code, the counter and the attempts the
  portal saw.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened by the split of the survey archived at
  `docs/archive/2026-10-13-atrust-reimplementation-lessons.md` (then `B07`): the measurements quoted
  above are its review's, and the class table and the gate are its candidates A and B.
