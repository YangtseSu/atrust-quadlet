<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B03 — Long-run observation

Status: ⏸ backlog — scheduled only if the container is ever run unattended
Depends on: an unattended run of a week or more
Touches: `atrustd/state.py`, `atrustd/__main__.py`, `tests/test_history.py`, `README.md`

## Goal

Two questions are answered today by scrolling a journal: how often the portal demands a captcha, and
how long a recovery takes. Both are decisions a user makes once (is the hand-over rare enough to live
with?) and both become data with a transition record and one summary command. The record also feeds
step 01's notifications: the same file could carry the reason a human was paged.

Both questions only matter while nobody is watching: an operator who starts the container when the
tunnel is needed stands in front of every drop and every captcha. The week of data this step closes on
is therefore its own precondition, not a formality.

## Deliverables

- ⏸ `state.py` appends one JSON line per transition to `history.jsonl` in the state directory:
  `{"t": <epoch>, "state": ..., "message": ..., "detail": ...}`, append-only, stdlib only, no new
  dependency; the file is created on first use and never rewritten.
- ⏸ `python3 -m atrustd --history [--since 7d]` prints the summary: transitions per state, the
  `NEED_VNC` reasons grouped by their hint text, the recovery time between a down state and the next
  `ONLINE` (count, median, worst), and the time span covered — numbers, not prose.
- ⏸ `tests/test_history.py`: a sequence of transitions writes exactly one line each; the summary over
  a synthetic file prints the expected counts and percentiles.
- ⏸ The step closes on **data**, not on code: at least a week of the live container's `history.jsonl`
  is summarised in the `## Progress log` (captcha hand-overs, kicks, recovery times), which is also
  what the retired roadmap's "long-run observation" item wanted to know.

## Exit criteria

- ⏸ `--history` prints the summary on the live container's state directory.
- ⏸ Seven days of transitions are recorded here with the numbers, or the step stays open with the
  reason (for example: the container was not running for part of the window).

## Progress log

* 2026-10-10 — written as step 02.
* 2026-10-10 — retired to the backlog before starting, on review: the container is started on demand,
  so the supervisor is watched exactly when it fails and the week of unattended transitions the step
  closes on never accumulates. The design above is what it would be, unchanged, once the container
  runs without anybody at the desk.
