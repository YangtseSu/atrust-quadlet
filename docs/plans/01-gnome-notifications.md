<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 01 — GNOME notifications for state changes

Status: 🚧 in-progress
Depends on: —
Touches: `quadlet/atrust-notify.sh`, `quadlet/atrust-notify.service`, `quadlet/atrust-notify.timer`,
`tests/test_notify.py`, `README.md`

## Goal

Every state that needs a human, and every change of the tunnel's state, reaches the desktop instead of
a journal nobody watches: the captcha hand-over (`NEED_VNC`), a login the client's window cannot finish
(the same state, with the reason in its hint — what a forced password change looks like from here),
the tunnel going down (`DEGRADED`, `LOGGED_OUT`) and coming back (`ONLINE`). The supervisor already
writes all of it to `state.json`; this step mirrors it, host-side, without touching the engine.

The notifier is additive: it reads the state through `podman exec` and writes only
`$XDG_RUNTIME_DIR/atrust-notify.last`, so no other file of the project changes, nothing else depends
on it, and uninstalling it is uninstalling three files.

## Deliverables

- ✅ `quadlet/atrust-notify.sh`: reads `state.json` through
  `podman exec <container> cat /run/atrustd/state.json` (nothing on the host is mounted or written
  except the marker) and compares `(state, since)` with the marker in
  `$XDG_RUNTIME_DIR/atrust-notify.last`. One `notify-send` per transition, never two: `NEED_VNC` is
  `critical`, takes its body from the hint file (first line) and its icon from the captcha image when
  there is one; `DEGRADED`/`LOGGED_OUT` are `normal` and carry `detail`; `ONLINE` is `normal` and
  fires only when the previous state was not `ONLINE`; the first run after install seeds the marker
  silently (except when a human is already waited for). Urgency is configurable per class via
  `ATRUST_NOTIFY_URGENCY_NEED_VNC` / `ATRUST_NOTIFY_URGENCY_STATE`, invalid values fall back to the
  default; `podman` or the container missing is silence, not an error.
- ✅ `quadlet/atrust-notify.service` (oneshot) + `quadlet/atrust-notify.timer` (every 15 s,
  `OnBootSec=30s`), in the style of the repository's other units, but installed into
  `~/.config/systemd/user/`: Quadlet ignores `.timer` files (checked with the generator), so a
  `.timer` in `~/.config/containers/systemd/` would never run.
- ✅ `tests/test_notify.py`: drives the script with a temporary state directory and stub `podman` and
  `notify-send` earlier on `PATH`, asserting the emitted `(urgency, title, body)` for seeding,
  `ONLINE → DEGRADED`, `DEGRADED → ONLINE`, `→ NEED_VNC` (hint text and captcha icon), `NEED_VNC →
  ONLINE`, the urgency overrides, and that a missing container is silence.
- ✅ `README.md`: an "Operating it" paragraph with the install lines, the urgency drop-in, the
  uninstall lines and where the notifications come from.

## Exit criteria

- ⬜ The offline test passes; the stub log shows exactly one notification per transition.
- ⬜ On a live GNOME session a real transition (stopping the container's tunnel by whatever the human
  allows) produces the notification, and the `Notify` call is captured with `dbus-monitor` rather than
  asserted by eye; the captured arguments are in the `## Progress log`.
- ⬜ The container is back to `ONLINE` after the live transition (no unit change is part of this
  step), and the existing live checks (`atrustd --status`, both proxies through the tunnel) still pass.

## Progress log

* 2026-10-10 — written as step 01. The state file already carries everything the mapping needs
  (`state`, `since`, `message`, `detail`, `vnc_hint`), so no engine change is planned.
* 2026-10-10 — amended before starting, on review: the notifier must be removable and must not change
  anything else, so the `atrust.container` state mount is dropped - the script reads through
  `podman exec` - and the urgences became configurable (`ATRUST_NOTIFY_URGENCY_*`); the README
  carries the install, tune and uninstall lines.
