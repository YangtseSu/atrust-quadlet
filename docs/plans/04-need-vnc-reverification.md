<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 04 — NEED_VNC hand-over re-verification

Status: ⬜ not-started
Depends on: a maintenance window and at least one spare portal login attempt
Touches: `docs/plans/README.md` (this row), nothing in the tree unless a defect turns up

## Goal

The hand-over — the supervisor gives up on its own pipeline, writes the hint and the captcha image,
and a human finishes the login in the VNC session, after which the supervisor notices the tunnel and
returns to `ONLINE` — was last verified on the *previous* base image. The new base replaced the VNC
server (tigervnc on Debian 13), which is the one component that path depends on, so it is re-run once
on the own base. It costs a portal login attempt (`ATRUST_LOGINS_BEFORE_VNC` is 2), which is why it is
a step with a window rather than part of a normal cycle.

## Deliverables

- ⬜ Produce the state on the own base: a deliberately wrong password on a profile whose tokens are
  current, and record how many attempts it cost (the portal answers with its own counter, "You still
  have N attempts left").
- ⬜ The evidence of the state: `atrustd --status` reads `NEED_VNC`, `$ATRUST_STATE_DIR/NEED_VNC` holds
  the hint, `captcha.png`/`captcha.jpg` is present when the portal served one, and the journal shows
  the reason.
- ⬜ The human half: finish the login in the VNC session (the captcha is the realistic case, its dialog
  expires in under a minute) and record the transition back — `NEED_VNC → ONLINE (tunnel up after human
  action)`.
- ⬜ Step 01's notification is seen for this transition. Step 01 landed on 2026-10-10 with every other
  transition captured live, but `NEED_VNC` - its critical notification, the hint line as the body and
  the captcha image as the icon - had no live source then; this step has one. Capture the `Notify`
  call with `dbus-monitor` the way step 01 did.

## Exit criteria

- ⬜ The state file, the hint and the journal lines above are quoted in the `## Progress log`, with the
  portal attempt count, the wall-clock time the human took, and the `Notify` call the notifier sent
  for it.
- ⬜ The supervisor clears the hint on recovery (`NEED_VNC` and the captcha image are gone).

## Progress log

* 2026-10-10 — written as step 04. Not to be run casually: each attempt is one of the portal's.
* 2026-10-10 — step 01 landed, so the notification deliverable is no longer conditional and now names
  the gap it closes: `NEED_VNC` is the one transition step 01 could not produce live (no captcha to
  serve), and this step produces it for real.
