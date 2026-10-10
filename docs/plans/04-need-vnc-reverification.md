<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 04 — NEED_VNC hand-over re-verification

Status: ✅ done
Depends on: —
Touches: `docs/plans/README.md` (this row), and the one defect the drill turned up:
`atrustd/__main__.py` + `tests/test_cycle_pacing.py`

## Goal

The hand-over — the supervisor gives up on its own pipeline, writes the hint and the captcha image,
and a human finishes the login in the VNC session, after which the supervisor notices the tunnel and
returns to `ONLINE` — was last verified on the *previous* base image. The new base replaced the VNC
server (tigervnc on Debian 13), which is the one component that path depends on, so it is re-run once
on the own base. It costs a portal login attempt (`ATRUST_LOGINS_BEFORE_VNC` is 2), which is why it is
a step with a window rather than part of a normal cycle.

## Deliverables

- ✅ Produce the state on the own base, with a spare account and a deliberately wrong password on a
  profile whose tokens are current. The portal's *first* password answer was already the captcha
  demand (`code=75500000`, `graphCheckCodeEnable: 1`), so the hand-over arrived on the first attempt
  and `ATRUST_LOGINS_BEFORE_VNC` was never reached. The portal's own counter was then read off the
  client window's wrong-password attempt: `The username or password is incorrect. You still have 9
  attempts left` — the drill cost that account **one** attempt (10 → 9).
- ✅ The evidence of the state: the state file read `NEED_VNC` (`attempts: 1`, `since` 16:16:39),
  `$ATRUST_STATE_DIR/NEED_VNC` held the hint, the portal's `captcha.jpg` (272x192 JPEG) was written
  beside it, and the journal carried the reason
  (`portal requires the graphical captcha: 图形验证码已超时，请重试`).
- ✅ The human half: the captcha was answered in the client's own window (the client log records
  `graphcode expired` → `checking graph code` → `statusEvent|login`), the tunnel came up, and the
  supervisor logged `NEED_VNC -> ONLINE (tunnel up after human action)`. The operator confirmed the
  VNC login was their own hand, so this deliverable does not rest on an inference from the log.
- ✅ Step 01's notification is seen for this transition: the notifier's `Notify` call, captured with
  `dbus-monitor` on the session bus (see the `## Progress log` for the call itself). This was the one
  transition step 01 could not produce live.

## Exit criteria

- ✅ The state file, the hint and the journal lines are quoted in the `## Progress log`, with the
  portal attempt count (one, the portal's own counter 10 → 9), the wall-clock time the human took
  (**82 s** from the hint to `ONLINE`, of which ~52 s was the human's own captcha+login work), and
  the `Notify` call the notifier sent for it.
- ✅ The supervisor clears the hint on recovery: `$ATRUST_STATE_DIR` after the transition holds only
  `state.json` and `apps.json` - `NEED_VNC` and `captcha.jpg` are gone.

## Progress log

* 2026-10-10 — written as step 04. Not to be run casually: each attempt is one of the portal's.
* 2026-10-10 — step 01 landed, so the notification deliverable is no longer conditional and now names
  the gap it closes: `NEED_VNC` is the one transition step 01 could not produce live (no captcha to
  serve), and this step produces it for real.
* 2026-10-10 — **run, and it closed.** Setup: `atrust.service` stopped, `~/.config/atrust.env` and the
  whole profile copied to a timestamped backup outside the tree, the env switched to the spare account
  with a deliberately wrong password, and the client's cookie store removed so neither the engine nor
  the client could resume the previous account's session. All private data (portal, account names, the
  intranet target) is replaced by placeholders here.
* 2026-10-10 — the timeline, all times local wall clock:
  * `16:15:26` the engine's password auth was rejected for the captcha: `portal requires the graphical
    captcha: 图形验证码已超时，请重试` (first cycle, `attempts: 1`).
  * `16:15:39` `uiauto` submitted the client's login window with the wrong password.
  * `16:16:39` the hint was written and `LOGGED_OUT -> NEED_VNC (waiting for a human in VNC)`, with
    `detail: "no utun7: Device \"utun7\" does not exist.; 0 route(s) via utun7; not probed, no datapath
    yet"` and `attempts: 1`.
  * `16:16:47` the timer's `notify-send` reached the session bus. Captured call, verbatim from
    `dbus-monitor` (the third string is the app icon, the hints carry the image and the urgency):

    ```
    member=Notify
       string "aTrust"
       uint32 0
       string ""
       string "aTrust: human action required"
       string "the portal is asking for the graphical captcha; answer it in the client window over VNC"
       dict entry( string "image-path" variant string "<state dir>/captcha.jpg" )
       dict entry( string "urgency" variant byte 2 )
    ```

    (`byte 2` is `critical`; `image-path` is the captcha the portal served, which the notifier reads
    out of the mounted state directory.)
  * `16:17:05`-`16:17:57` the human's part, from the client's own log: `graphcode expired` →
    `/passport/v1/auth/psw` answering `code 75500000 "The characters has expired. Please try again"`
    with `graphCheckCodeEnable: 1` → `checking graph code` → one more `auth/psw` answered `The username
    or password is incorrect. You still have 9 attempts left` → `statusEvent|login`. No automation of
    this project can read a captcha, so this is the human half, and the operator confirmed by hand that
    the VNC login was theirs.
  * `16:18:00.97` the supervisor's probe found the tunnel and logged
    `NEED_VNC -> ONLINE (tunnel up after human action)`; the hint and `captcha.jpg` were gone with it.
    The datapath was confirmed independently from the host through the container's HTTP proxy
    (`host -> 127.0.0.1:8888 -> 10.0.0.10:80` → `HTTP 200`).
* 2026-10-10 — the drill earned its window: the recovery transition reported a **stale** `detail`. The
  `transition()` call in the `NEED_VNC` wait passed no detail, and that function keeps the previous one
  when it is empty, so the state file - and the recovery notification, which prints the same field as
  its body - said `tunnel up after human action` beside `no utun7: … not probed, no datapath yet`.
  Fixed in `fix(atrustd): report the tunnel the human recovery actually saw`, with a regression test in
  `tests/test_cycle_pacing.py` that drives `cycle()` through the wait loop (it fails on the old code,
  passes on the new one).
* 2026-10-10 — the operator's own account was restored from the backup afterwards (env file and
  profile), and the container was back to `ONLINE` 17 s after the start
  (`16:21:13 DEGRADED -> LOGGED_OUT`, `reusing tid,tid.sig from the client profile`, `password auth
  ok`, `16:21:25 submitted the login form of the client window`,
  `16:21:30 LOGGED_OUT -> ONLINE (tunnel up after the client login)`), with the host-side proxy probe
  answering `200`. The drill's own evidence (state snapshots, the journal, the D-Bus capture, the
  client's login lines) was kept in the same backup directory.
