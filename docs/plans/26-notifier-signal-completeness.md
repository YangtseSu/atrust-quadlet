<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 26 — The notifier reports the state it samples, not every state that exists

Status: 🚧 in-progress
Depends on: — (the browser line, which waited on step 16's exposure decision, has landed first; the
rest of the step depends on nothing)
Touches: `quadlet/atrust-notify.sh`, `quadlet/atrust-notify.service`, `tests/test_notify.py`,
`README.md`, `docs/DESIGN.md`, `docs/plans/README.md`

## Goal

Step 01's notifier is right about the states it sees and silent about three things it does not:

1. **A dead supervisor is silence.** The script reads `state`/`since`/`message`/`detail` and never
   `updated` (and never the file's mtime), so a container that stopped - or an `atrust.service` in its
   restart loop, `StartLimitIntervalSec=0` makes that a loop rather than a `failed` unit - leaves
   `state.json` frozen at the last `ONLINE` and the desktop quiet. Being told the tunnel is unknown is
   the one thing the notifier should be first at.
2. **The client's own view never reaches the desktop**, although `state.json` carries it (live,
   2026-10-15: `"client": {"state": "online", "tunnel": "tunnelAvailable", "user": "<user>",
   "login": "2026-10-15 23:35:21"}`) and `docs/DESIGN.md` already says a human *and
   `quadlet/atrust-notify.sh`* read *who* is logged in and since when. `field()` matches the top level
   only, by design (the nested object has a `state` of its own), so the notifier reads neither field.
3. **A `NEED_VNC` that must not be answered in VNC** - the refused password or the lockout
   (`portal.HELD_CLASSES`) - arrives as the same critical "human action required" as a captcha, and its
   reason (`the portal refused the password login (wrong-password, N attempts left): ...`) is the whole
   body. That class needs an edit to `~/.config/atrust.env` and a restart, not a desktop.

Beside those: the body leads with the supervisor's own jargon (`detail`, and for `LOGGED_OUT` the
`client .../...; not restarting it` phrase) while `message` ("tunnel up after the ticket login") is the
human sentence, kept only as a fallback; and successive same-class notifications stack.

## Deliverables

- ⬜ `quadlet/atrust-notify.sh`, staleness: the file exists and `updated` is older than
  `ATRUST_NOTIFY_STALE_AFTER` (default 300 s) → one notification of its own class (muteable like the
  others, `critical`), re-armed when the file freshens; a missing file stays silent (a deployment that
  has not started yet must not ring). The `(state, since)` marker gains a third line for it.
- ⬜ The client's own view in the body of `ONLINE`/`LOGGED_OUT`: `state/tunnel`, `user=` and
  `since=`, read from the nested object with a four-space `field()` variant, absent fields simply
  omitted (an older container writes no `client` object, an unreachable client writes its `error`).
- ⬜ The recovery body carries how long the tunnel was down: `ONLINE` after a down state subtracts the
  marker's `since` (integer part) from `date +%s`.
- ⬜ `ONLINE`'s body leads with `message` (how it came back) and keeps `detail` after it; the
  `DEGRADED`/`LOGGED_OUT` bodies keep `detail` and fall back to `message` as they do.
- ⬜ A refused-password or lockout hint (`case "$body" in *"refused the password login"*)`) gets its own
  title (`aTrust: password refused, N attempts left`), so the one class that is an env-file edit does
  not read like a captcha.
- ⬜ `send()` passes `-h string:x-canonical-private-synchronous:aTrust-<class>`, so a repeated class
  replaces its previous notification while different classes still stack; verified on the live GNOME
  session with `dbus-monitor`, like step 01's capture, before it is called done.
- ⬜ `ATRUST_NOTIFY_CMD`: one executable, four arguments (`urgency title body icon`), default
  `notify-send`, so a host without a session bus can send the same states somewhere else (an ntfy or
  mail wrapper), with one README example and the four-argument contract written beside the script's
  other variables.
- ⬜ `tests/test_notify.py` writes its `state.json` through `atrustd.state.Status.to_json()` instead of
  a hand-built dict: `field()` depends on `indent=2` and the top-level key names, and today a change to
  the writer would break the notifier while the test stayed green (both sides hand-write the shape).
- ⬜ The `/tmp` fallback hardens: `umask 077` before the temporaries and the captcha copy are written
  when `XDG_RUNTIME_DIR` is unset (the runtime directory itself is 0700, a bare `/tmp` is not).
- ⬜ The sampling semantics are stated instead of implied - the script header and one README line: a
  state shorter than the poll interval may be missed or caught mid-walk; the notifier reports the
  state you would find. Measured example for the text: `ONLINE → DEGRADED → LOGGED_OUT → ONLINE` in
  13.2 s (2026-10-15 23:36:02 → 23:36:15) is 0 to 3 notifications depending on where the 15 s tick
  lands, which is deliberate, not a bug.
- ✅ When step 16 publishes the agent's port: `ATRUST_NOTIFY_WORKBENCH=<url>` appends "or finish the
  login in your browser: <url>" to the `NEED_VNC` body - host knowledge, host side: `atrustd/vnc.py`'s
  hint stays deployment-agnostic, because the container cannot know whether the host publishes a port.
  One class is excluded: a body naming a refused credential or a lockout, whose fix is
  `~/.config/atrust.env` and which a browser login would be refused for as well (it keys on
  `atrustd`'s own held-class message). The variable is in the script's header; the README shows it
  beside the publish, with the 2026-10-16 measurement (a human's portal login brought a logged-out
  client up in 55 s).

## The alternatives this declines, and why

* **A `.path` unit instead of the timer** (`PathChanged=`/`PathExists=` on `state.json`): inotify, no
  polling, ~1 s latency - but it fires on *every* write (one per cycle, one per transition), so the
  13.2 s blip above becomes three notifications instead of a phase-dependent 0-3, and a feature the
  README sells as "three files and it is gone" grows a fourth. The staleness bound above needs a timer
  anyway.
* **A FIFO or a socket with a resident reader**: the supervisor's writes can block on a host reader
  that is not running (FIFO) or vanish silently (datagram), and the host gains a process to supervise.
  The file is *state*, so the derivation is idempotent and any downtime is caught up on the next
  start; that is worth more than the ≤15 s.
* **Reading the journal**: the transition line already carries the client's phrase, but it is prose, it
  needs a resident `journalctl -f`, and the container's journald driver adds records of its own.
* **Mounting the session bus into the container** so the supervisor notifies directly: a vendor binary
  as root would own the bus every application of the user talks on.
* **Feeding the notifier from the agent's API once step 16 publishes it**: the API is unreachable
  exactly when the client is restarting, i.e. when the notification matters, and sh has no business
  long-polling HTTP.
* **An action button on the notification** (`notify-send -A --wait`, "open the VNC client"): the wait
  belongs to a process that outlives the notification, and this service is a oneshot with a start
  timeout; one-click access is the desktop's own launcher entry, not the notifier's job.
* **Moving the marker to `$XDG_STATE_HOME`** (so a reboot does not reseed it): that is the new
  semantics "report what happened while you were away", not a hardening. The transient marker matches
  "tell me about now", which is what the silent first-run seeding already encodes.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green, with a staleness case (an old
  `updated` rings once, a fresh one re-arms) and a client-view case.
- ⬜ Live: a stopped container rings once; a real transition carries the client's user and the outage
  duration; a repeated same-class notification replaces the previous one and a different class stacks
  (`dbus-monitor` capture in the `## Progress log`).

## Progress log

* 2026-10-15 — written on request ("当前 atrust-notify，还有什么改进的空间，或者别的实现方式？"),
  as a design review rather than a fault: nothing here has disrupted a deployment yet. The evidence is
  from the live host: tonight's journal (`ONLINE → DEGRADED → LOGGED_OUT` 23:36:02, `ONLINE` 23:36:15,
  the client unreachable around a restart), the state file's `client` object above, `docs/DESIGN.md`'s
  claim about the notifier beside `field()`'s two-space match, and the measurement that the user
  manager writes one state record per oneshot activation (transient oneshot, `Started [systemd-run]
  /bin/true.`), which is the whole cost of the 15 s timer.
* 2026-10-15 — the declined mechanics above were weighed in the same review; the `.path` unit lost on
  the blip noise and the file count, not on latency, and the API feed lost on being unreachable
  exactly when it is needed. The ordering inside this file is the value: staleness first, then the
  content, then the transport questions, which need no transport change at all.
* 2026-10-15 — promoted to step 26 on request ("提成 step 26"), with the review's recommendations
  taken as this step's decisions: the canonical-synchronous hint and the outage duration are in, the
  action button and the marker move are out (both recorded above), and the browser line stays
  host-side (`ATRUST_NOTIFY_WORKBENCH` in the unit or a README drop-in; `atrustd/vnc.py` untouched).
  Nothing is landed: the first item is the staleness class.
* 2026-10-16 — the browser line landed first, ahead of this step's other items: it was the one item
  gated on step 16's exposure decision, that step closed today, and the operator asked for exactly
  this behaviour (a `NEED_VNC` that also says the login can be finished in the browser). The rest of
  the step is untouched and its ordering stands. Landed: `ATRUST_NOTIFY_WORKBENCH` (documented in the
  script header and in the README beside the publish) appends `or finish the login in your browser:
  <url>` to the `NEED_VNC` body, with the refused-credential/lockout class excluded - that one is an
  env-file edit and a browser login would be refused for it too. Verified offline-first: four runs
  against a synthetic state directory with a capturing `notify-send` (variable set -> the line is
  there; unset -> it is not; the held-class body, with and without the variable -> never the line),
  then one real delivery captured on the session bus (`member=Notify`: app `aTrust`, `urgency` byte
  2, title `aTrust: human action required`, body the hint's first line plus the browser line).
