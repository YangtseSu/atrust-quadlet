<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 01 — GNOME notifications for state changes

Status: ✅ done
Depends on: —
Touches: `quadlet/atrust-notify.sh`, `quadlet/atrust-notify.service`, `quadlet/atrust-notify.timer`,
`tests/test_notify.py`, `README.md`

## Goal

Every state that needs a human, and every change of the tunnel's state, reaches the desktop instead of
a journal nobody watches: the captcha hand-over (`NEED_VNC`), a login the client's window cannot finish
(the same state, with the reason in its hint — what a forced password change looks like from here),
the tunnel going down (`DEGRADED`, `LOGGED_OUT`) and coming back (`ONLINE`). The supervisor already
writes all of it to `state.json`; this step mirrors it, host-side, without touching the engine.

The notifier is additive: it reads the state out of the container with `podman cp` and writes only
its own temporaries under `$XDG_RUNTIME_DIR` plus the marker `$XDG_RUNTIME_DIR/atrust-notify.last`,
so no other file of the project changes, nothing else depends on it, and uninstalling it is
uninstalling three files.

## Deliverables

- ✅ `quadlet/atrust-notify.sh`: copies `state.json` (and, when needed, `NEED_VNC` and the captcha)
  out of the container with `podman cp` into `$XDG_RUNTIME_DIR` - no host mount, no exec session -
  and compares `(state, since)` with the marker in
  `$XDG_RUNTIME_DIR/atrust-notify.last`. One `notify-send` per transition, never two: `NEED_VNC` is
  `critical`, takes its body from the hint file (first line) and its icon from the captcha image when
  there is one; `DEGRADED`/`LOGGED_OUT` are `normal` and carry `detail`; `ONLINE` is `normal` and
  fires only when the previous state was not `ONLINE`; the first run after install seeds the marker
  silently (except when a human is already waited for). Classes can be muted with
  `ATRUST_NOTIFY_MUTE` (comma separated, case-insensitive; a muted class still moves the marker, so
  it neither rings nor delays a later unmuted one); the urgences are fixed at `critical` for
  `NEED_VNC` and `normal` for the tunnel changes; `podman` or the container missing is silence, not
  an error.
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

- ✅ The offline test passes; the stub log shows exactly one notification per transition.
- ✅ On a live GNOME session a real transition (stopping the container's tunnel by whatever the human
  allows) produces the notification, and the `Notify` call is captured with `dbus-monitor` rather than
  asserted by eye; the captured arguments are in the `## Progress log`.
- ✅ The container is back to `ONLINE` after the live transition (no unit change is part of this
  step), and the existing live checks (`atrustd --status`, both proxies through the tunnel) still pass.

## Progress log

* 2026-10-10 — written as step 01. The state file already carries everything the mapping needs
  (`state`, `since`, `message`, `detail`, `vnc_hint`), so no engine change is planned.
* 2026-10-10 — amended before starting, on review: the notifier must be removable and must not change
  anything else, so the `atrust.container` state mount is dropped - the script reads through
  `podman exec` - and the urgences became configurable (`ATRUST_NOTIFY_URGENCY_*`); the README
  carries the install, tune and uninstall lines.
* 2026-10-10 — the poll first read the state with `podman exec cat` and flooded the user journal: the
  container runs with the journald log driver, so every exec session writes `container exec` /
  `container exec_died` records through the driver itself - outside the process's stderr and outside
  `--log-level`, both measured as no-ops. The read is now `podman cp` of `state.json`, `NEED_VNC` and
  `captcha.*` into `$XDG_RUNTIME_DIR`, which creates no exec session: the same unit under
  `systemd-run --user` wrote 0 records instead of 2.
* 2026-10-10 — live acceptance on this workstation's GNOME session. Installed from the README lines
  while the state was `ONLINE`: the first tick wrote the marker as `ONLINE` + that `since` and sent
  nothing, and the polls after it stayed silent - the journal holds only systemd's
  `Starting`/`Finished`, no podman records. A real transition came from
  `systemctl --user restart atrust.service` (the state file is recreated, so its first cycle writes a
  fresh state), captured with
  `dbus-monitor --session "interface='org.freedesktop.Notifications',member='Notify'"`:

      method call ... member=Notify
      string "aTrust"
      uint32 0
      string ""
      string "aTrust: session gone, logging in again"
      string "no utun7: Device \"utun7\" does not exist.; 0 route(s) via utun7; not probed, no datapath yet"
      ... urgency: byte 1 (normal)

  and 16 s later `aTrust: tunnel is up` with `utun7 2.0.0.1/24; 30 route(s) via utun7; probe
  <probe> ok (HTTP/1.1 200)`. Exactly two `Notify` calls, one per transition; the supervisor
  recovered by itself (`tunnel up after the client login`, attempts 0), `atrustd --status` reads
  `ONLINE`, and both proxies answered 200 (`curl -x http://127.0.0.1:8888`, `curl
  --socks5-hostname 127.0.0.1:1080`). The captcha icon has no live source yet (the portal is not
  asking for a captcha), so its rendering stays offline-verified; the shape it is sent with was
  captured live instead - `notify-send -i <absolute path>.png` shows up as the `image-path` hint of
  the same capture. The uninstall lines were then run verbatim: nothing of it left in
  `~/.local/bin`, `~/.config/systemd/user` or the timer list, `atrust.service` stayed active and
  `ONLINE`, and the install lines brought the timer back (re-seeded, still silent).
* 2026-10-10 — two corrections after the close. (1) The urgency knobs were a misreading: the request
  was per-class muting, so `ATRUST_NOTIFY_URGENCY_*` is replaced by `ATRUST_NOTIFY_MUTE` (comma
  separated, case-insensitive, unknown tokens warn and are ignored; a muted class still moves the
  marker, so it neither rings nor delays a later unmuted class) and the urgences are fixed again at
  `critical` for `NEED_VNC` and `normal` for the tunnel changes. (2) The dropped state mount: the
  plan's `Volume=%h/.atrust-data/run:/run/atrustd` was dropped while working, on reading the "no impact
  on other parts" constraint as "no other file changes" - a decision that should have been reported
  when it was taken, not at the close; the read is `podman cp` instead, which keeps
  `atrust.container` untouched and the feature removable.
