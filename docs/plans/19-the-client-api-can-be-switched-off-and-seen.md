<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 19 — The client's local API can be switched off, and its refusals are visible

Status: ✅ done
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
- ✅ The wait a drift would cost: `API_TUNNEL_WAIT` stays at 60 s, with the reason beside the constant -
  the wait is probe-driven and returns on the first passing sample (three seconds on step 14's drill,
  5.1 s on the 2.5.16.41 drill), so the bound is paid only when the tunnel is not coming on this path,
  which is the window fallback's case; a smaller number would only end a slow recovery sooner.
- ✅ `AGENTS.md`: the client-bump rule gains the interface's acceptance (a status read, the event channel,
  the ticket path - one command each, on the live container) beside the live acceptance and the `uiauto`
  geometry it already names.
- ✅ Live: one start with `ATRUST_CLIENT_API=0` showing a supervisor that talks to the data plane only
  (`--status` without the `client` object, no `client event` lines in the journal) and one start with it
  back on; the numbers and the journal lines are in "The measurement" below.

## The measurement (live, 2026-10-12, the dev image, container recreations)

The switch off (`ATRUST_CLIENT_API=0`, the same image and flags as the step-18 runs), first cycle:

```
13:59:04.289 INFO atrustd: the client's own API is off (ATRUST_CLIENT_API=0); the supervisor reads the data plane only
13:59:04.292 INFO atrustd: ONLINE -> DEGRADED (tunnel not usable)
13:59:04.357 INFO atrustd: DEGRADED -> LOGGED_OUT (the client has to log in again)
13:59:22.527 INFO atrustd: LOGGED_OUT -> ONLINE (tunnel up after the client login)
```

No `atrustd.clientapi` line in the whole run (no poller, no status read, no ticket path), no `; client
...` on any transition, and the state file's `client` is `{}` - the same recovery the old image ran, in
18.2 s. The runs with it back on are step 18's own (18.3 s, the ticket path's refusal in the journal at
WARNING and in the state file's detail).

The switched-off start also found a bug the offline tests did not: the daemon reads the previous
`state.json` at startup, and with no API in the cycle it kept writing that run's `client` object back -
the log lines claimed `client online/tunnelAvailable user=<user>` while nothing had been read
(measured 13:59:04.292, beside `the client's own API is off`). `note()` now clears the record when the
cycle has no API, and the cycle test seeds a stale view in the state file and asserts it does not
survive.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` (117) and `reuse lint` (92/92) stay green.
- ✅ Live: the switch off produces a supervisor with no API traffic and the same states as before the
  interface existed (18.2 s, quoted below); the switch on recovers a session through the ticket path -
  the 2.5.16.41 bump's drill on the published image did exactly that (`the client took the ticket;
  waiting up to 60s for the tunnel`, `LOGGED_OUT -> ONLINE (tunnel up after the ticket login)` 5.1 s
  later), quoted in `base/README.md`.
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

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
* 2026-10-12 — the live half is in, quoted under "The measurement": the switched-off start logs its one
  line, runs with no `atrustd.clientapi` traffic at all, writes `client: {}` and recovers in 18.2 s; the
  same image with it back on is step 18's run. The live run also earned a fix the offline half had missed:
  with no API the daemon was carrying the previous run's `client` object out of `state.json` into its own
  transitions (the log claimed a view nobody had read), which `note()` now clears and the cycle test pins
  with a seeded stale view. Still open: the `API_TUNNEL_WAIT` decision and the bump ritual's line.
* 2026-10-13 — the bump ritual's line is in `AGENTS.md`, written from the client 2.5.16.41 bump that ran
  the same day: the rule now names the three commands (the `PYTHONPATH` the image already sets keeps each
  to one `python3 -c` line) and what each has to answer, so the next bump cannot ship a moved interface
  silently. Measured on that bump: status `True online tunnelAvailable`, the event channel answering
  `25 []` (its id, nothing pending - the daemon's own poller had consumed the login burst, which is in
  the journal), and the ticket path recovering the session after a forced logout, quoted in the bump's
  own record (`base/README.md`).
* 2026-10-13 — closed with the `API_TUNNEL_WAIT` decision, which the bump's own drill supplied the number
  for: the constant keeps its 60 s and the reason moved beside it (`atrustd/__main__.py`), because the
  wait returns on the first passing probe - 5.1 s on that drill - and the bound only governs the case the
  window fallback owns. The exit criterion's live half is that same drill on the published image: the
  session recovered through the ticket path with the API switched on, and the switched-off half is the
  measurement above.
