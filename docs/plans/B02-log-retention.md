<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B02 — Log retention

Status: ⏸ backlog — deferred 2026-10-09 as more machinery than the benefit justifies
Depends on: —

## Goal

The client rotates only its xtunnel streams (20 MB, one previous generation); the tray and agent logs
are reset when the client restarts and a fresh per-day file is started every day, so the mounted
profile grows by roughly 0.2 GB/day. A cleanup script plus a user timer were written once and dropped.

## Deliverables

- ⏸ A cleanup script (delete `~/.atrust-data/.aTrust/logs/*` older than N days) and, if a timer is
  wanted, a user unit beside the Quadlet one.

## Exit criteria

- ⏸ The profile stops growing without losing the logs a live investigation needs (the last day's).

## Progress log

* 2026-10-10 — written as backlog from the retired roadmap (its item "log retention"). The churn that
  once made the logs grow 20 MB every two minutes was this project's own busy loop, fixed since.
