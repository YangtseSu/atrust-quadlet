<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 01 — GNOME notifications for state changes

Status: ⬜ not-started
Depends on: —
Touches: `quadlet/atrust-notify.sh`, `quadlet/atrust-notify.service`, `quadlet/atrust-notify.timer`,
`quadlet/atrust.container`, `tests/test_notify.py`, `README.md`

## Goal

Every state that needs a human, and every change of the tunnel's state, reaches the desktop instead of
a journal nobody watches: the captcha hand-over (`NEED_VNC`), a login the client's window cannot finish
(the same state, with the reason in its hint — what a forced password change looks like from here),
the tunnel going down (`DEGRADED`, `LOGGED_OUT`) and coming back (`ONLINE`). The supervisor already
writes all of it to `state.json`; this step mirrors it, host-side, without touching the engine.

## Deliverables

- ⬜ `quadlet/atrust-notify.sh`: reads `state.json` — from `$ATRUST_STATE_HOST_DIR` when the unit
  mounts the state directory, else through `podman exec <container> cat /run/atrustd/state.json` — and
  compares `(state, since)` with the marker in `$XDG_RUNTIME_DIR/atrust-notify.last`. One
  `notify-send` per transition, never two: `NEED_VNC` is `--urgency=critical`, takes its body from the
  hint file (first line) and its icon from the captcha image when there is one; `DEGRADED`/`LOGGED_OUT`
  are normal and carry `detail`; `ONLINE` is normal and fires only when the previous state was not
  `ONLINE`; the first run after install seeds the marker silently.
- ⬜ `quadlet/atrust-notify.service` (oneshot) + `quadlet/atrust-notify.timer` (every 15 s,
  `OnBootSec=30s`), both in the style of the repository's other units.
- ⬜ `quadlet/atrust.container` mounts the state: `Volume=%h/.atrust-data/run:/run/atrustd`. The host
  then reads the file directly (no exec per poll) and the marker survives container recreation.
- ⬜ `tests/test_notify.py`: drives the script with a temporary state directory and a stub
  `notify-send` earlier on `PATH`, asserting the emitted `(urgency, title, body)` for seeding,
  `ONLINE → DEGRADED`, `DEGRADED → ONLINE`, `→ NEED_VNC` (hint text and captcha icon) and
  `NEED_VNC → ONLINE`.
- ⬜ `README.md`: an "Operating it" paragraph with the three install lines and where the notifications
  come from.

## Exit criteria

- ⬜ The offline test passes; the stub log shows exactly one notification per transition.
- ⬜ On a live GNOME session a real transition (stopping the container's tunnel by whatever the human
  allows) produces the notification, and the `Notify` call is captured with `dbus-monitor` rather than
  asserted by eye; the captured arguments are in the `## Progress log`.
- ⬜ The service is back to `ONLINE` after the unit change, and the existing live checks
  (`atrustd --status`, both proxies through the tunnel) still pass.

## Progress log

* 2026-10-10 — written as step 01. The state file already carries everything the mapping needs
  (`state`, `since`, `message`, `detail`, `vnc_hint`), so no engine change is planned.
