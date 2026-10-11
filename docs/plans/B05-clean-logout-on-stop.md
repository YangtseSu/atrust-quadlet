<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B05 — A clean session end on stop

Status: ⏸ backlog — only if the portal's stale-terminal history becomes a problem
Depends on: — (`docs/CLIENT-LOCAL-API.md`, "Routes that exist but were not exercised")
Touches: `atrustd/__main__.py`, `atrustd/clientapi.py`, `docs/DESIGN.md`, `docs/plans/README.md`

## Goal

`systemctl --user stop atrust` sweeps the client family and the container goes away; the portal's
session is left to expire, and the portal's terminal list keeps the host's name until it does. The
agent has a route for the other ending - `POST /v1/service/logout` with
`{"type": "clientexit" | "passportTokenLogout" | "force", "guid": ..., "addr": ...}` (schema read out
of `libaTrustCore.so`; not exercised, because it ends a live session) - and the CSSDK documents the
same operation as `atrust_sync_logout`.

The stop path is deliberately fast (≲2 s measured) and every added step eats into that, so this is
backlog material, not a step: the cost is a loopback call before the sweep, the risk is a stop that
now depends on the agent answering, and the benefit is a portal that sees a logout instead of a
terminal that stopped talking.

## Deliverables

- ⏸ Measure first, in a throwaway container: what `logout` does to the session, what it answers, how
  long it takes, and whether the client family still has to be swept afterwards.
- ⏸ If it is cheap and reliable: `run_daemon`'s stop path sends it (bounded, best-effort - a stop
  must not fail because the agent is wedged) before `tokens.stop_client_family()`.
- ⏸ The live measurement: the stop time with and without, and what the portal's terminal list shows
  afterwards.

## Exit criteria

- ⏸ The stop stays ≲2 s and the portal records a logout, or the step closes with the reason it
  cannot.

## Progress log

* 2026-10-11 — written while cataloguing the local API; retired to the backlog on the same day,
  because nothing today depends on the portal's terminal history and the stop path's speed is a
  measured property this project protects.
