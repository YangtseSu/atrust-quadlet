<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 18 — A cold start pays no wait for a guid the client cannot publish yet

Status: 🚧 in-progress
Depends on: — (step 14's cold-start numbers and its own follow-up, "a tighter guid wait")
Touches: `atrustd/clientapi.py`, `atrustd/__main__.py`, `tests/test_clientapi.py`,
`tests/test_cycle_pacing.py`, `docs/DESIGN.md`, `docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

The ticket path's way in pays `CLIENT_RESTART_WAIT` (ten seconds, one read a second) for a client whose
HTTP service is not answering yet or whose `sdpcguid` is still empty. The bound is priced for a tray that
has just restarted - its service is unreachable for ~2-4 s and its guid appears within ~5 s - but a
container that has just been recreated publishes no guid for 35 s+, and nothing told the two apart:
step 14 recorded exactly that ("nothing measured so far tells the two apart, so every cold start pays the
ten-second bound for the chance to win a tray restart"), with the cold start at 54.4 s against the old
path's 13.5 s - ~20 s of it these two bounds, the one case where the image got slower.

The discriminator is already in the daemon's hand and needs no new probe: whether *this daemon* has ever
seen a guid from its client. A daemon that has (the tray restart, the client restarted around a token
write, an hours-old session ending) pays the bound as today; one that has not - a container whose client
has just started with it - reads once and lets the window path, whose login runs in that case anyway, take
the cycle.

## Deliverables

- ✅ `atrustd/clientapi.py`: `ClientAPI.status()` adopts a non-empty `sdpcguid` into `self.guid` and
  remembers that it has seen one (`seen_guid`), so the envelope's guid and the wait decision have one
  source; the docstring says what the memory is for.
- ✅ `atrustd/__main__.py`: `_api_login()`'s two `_client_view(..., CLIENT_RESTART_WAIT, want_guid=True)`
  calls wait `CLIENT_RESTART_WAIT if api.seen_guid else 0.0` - one read where a guid has never been
  published, the bound where a restart is the likely cause. The refusals it can still return are unchanged
  (`the client has no session guid yet`, `the client service did not answer: ...`).
- ✅ Tests: `tests/test_clientapi.py` pins the memory (a read carrying a guid, then one without, keeps
  `guid` and `seen_guid`); `tests/test_cycle_pacing.py` pins that a daemon which has never seen a guid does
  not sleep for one and records why the attempt could not run, and that a daemon which has seen one still
  pays the bound.
- ⬜ Live, on the dev image: one container recreation with the journal quoted - the ticket path's way in
  costs no ten-second pause, the reason it could not run is in `state.json`, and the recovery lands beside
  step 14's 13.5 s old-path figure instead of its 54.4 s one.
- ✅ `docs/DESIGN.md`: the ticket path's limits carry the discriminator (a guid this daemon has seen)
  beside the 35 s+ cold-start number, and the supervisor section names the switch.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ Live: a container recreation shows no ten-second pause in the ticket path's way in, and the state file
  carries the reason it could not run when it cannot.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-12 — opened from step 14's own follow-up. Started ahead of step 17 (the number is the execution
  order; this one is a two-line behaviour fix whose evidence is already on the table, and the cold start it
  fixes is the same session's request). The measurement this step has to show is deliberately the cheap
  one: a recreation, no forced logout, no extra portal login.
* 2026-10-12 — the code half landed in the same session it was opened: `ClientAPI.status()` adopts a guid
  into `self.guid` and remembers it (`seen_guid`), `_api_login()`'s two reads wait `CLIENT_RESTART_WAIT if
  api.seen_guid else 0.0`, and the two test files pin the memory and both sides of the wait (117 tests
  offline, `reuse lint` 92/92). What is left is the live item: the dev image rebuilt and one container
  recreation on it, which is the recreation this step's own exit criterion names.
