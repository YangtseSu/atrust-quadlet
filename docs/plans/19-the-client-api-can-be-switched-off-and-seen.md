<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 19 — The client's local API can be switched off, and its refusals are visible

Status: 🚧 in-progress
Depends on: — (no new measurement: the interface's shapes are in `docs/CLIENT-LOCAL-API.md`, and they were
all read out of the running client because Sangfor documents none of them)
Touches: `atrustd/config.py`, `atrustd/__main__.py`, `tests/test_cycle_pacing.py`, `README.md`,
`AGENTS.md`, `docs/DESIGN.md`, `docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

Every use of the client's loopback API is a measurement of an interface nobody documents: the port file,
the envelope, the routes and their answers were read out of the running client, and a client bump may move
any of them with nothing in any release note to say so - the project's own bump ritual (a new
`base/build-args/<arch>.env`, the live acceptance, the `uiauto` geometry) has no step for them either. The
design already survives that: every call is optional, every failure is a value, the probe still decides and
the window still logs in. What is missing is the two ends of it:

* **no way back.** Switching the API off means downgrading the image; there is no knob a deployment can
  turn while it works out whether a client bump broke the interface.
* **the cost is quiet.** When the ticket path cannot run, the journal carries it at INFO and the wait it
  cost, and the state file carries the reason only once a cycle escalates to `NEED_VNC` - so a drifted
  route shows up as a slower recovery, not as a statement.

After this step the switch exists, the refusal is where a human reads it, the waits the drift would pay are
sized by the measurements, and the bump ritual asks for the interface's own acceptance.

## Deliverables

- ✅ `ATRUST_CLIENT_API` (default on) → `Config.client_api`, read once in `run_daemon`: off means no
  `ClientAPI`, no event poller, no status read, no ticket path - the data-plane-only supervisor this image
  had before the interface - with one journal line saying the interface is off. `README.md`'s configuration
  table gains the row; the parameter is in the table's established style (what it is, what the default is,
  what it does).
- ✅ The ticket path's refusal is visible where a human looks: the fallback logs a warning (it was INFO),
  and the window path's `ONLINE`/`LOGGED_OUT` transition detail carries `; the ticket login: <reason>` -
  the same shape the `NEED_VNC` branch already uses, and the field the notifier shows on the desktop.
- ⬜ The wait a drift would cost: decide `API_TUNNEL_WAIT` (60 s today) against its own measurement - the
  ticket path brought the tunnel up about three seconds after `start` (step 14) - and write the new number
  with its reason beside it, or record why it stays.
- ⬜ `AGENTS.md`: the client-bump rule gains the interface's acceptance (a status read, the event channel,
  the ticket path - one command each, on the live container) beside the live acceptance and the `uiauto`
  geometry it already names.
- ⬜ Live: one start with `ATRUST_CLIENT_API=0` showing a supervisor that talks to the data plane only
  (`--status` without the `client` object, no `client event` lines in the journal) and one start with it
  back on; the numbers and the journal lines quoted here.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ Live: the switch off produces a supervisor with no API traffic and the same states as before the
  interface existed; the switch on recovers a session through the ticket path.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-12 — opened from the interface's own status, not from a symptom: the API is undocumented and
  measured here, a client bump can move it silently, and the code's answer so far is "fall back", which
  costs time the deployment cannot see. The two landed items are the ones that need no new measurement; the
  two open ones are a number that needs a decision and an acceptance that needs the live container.
* 2026-10-12 — both landed items are in, the same session the file was opened: `ATRUST_CLIENT_API` parses
  through a new `flag()` helper, `run_daemon` builds no `ClientAPI` and starts no poller when it is off
  (one journal line says so), and the README's table carries the row; the ticket path's refusal is a
  WARNING and reaches the recovery's own state detail as `the ticket login: ...`. The cycle test pins the
  switched-off supervisor's state file (no view recorded) and the environment parse (117 tests offline,
  `reuse lint` 92/92). Left: the `API_TUNNEL_WAIT` decision, the bump ritual's line in `AGENTS.md`, and the
  live start with the switch off.
