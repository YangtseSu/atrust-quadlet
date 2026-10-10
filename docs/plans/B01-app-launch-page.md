<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B01 — App launch page

Status: ⏸ backlog — scheduled only if the published app list turns out to be used interactively
Depends on: —
Touches: `atrustd/apps.py`, `README.md`, a template

## Goal

`atrustd --apps` prints what the portal grants, with each app's launch URL and method. Those URLs are
plain HTTP(S) to intranet hosts, so the host can already open them through the container's proxies —
with the right proxy configuration and no click-through. A small landing page served by the container
(or one proxy alias per app) would make it one click, and would also make a "default-browser" app
reachable without editing the host's proxy rules.

## Deliverables

- ⏸ A page generated from `apps.json` (name, launch URL, server address) and served on a loopback port
  the Quadlet unit publishes; links go through the container's HTTP proxy.
- ⏸ One line in `README.md`'s operating section.

## Exit criteria

- ⏸ Opening the page on the host reaches one of the account's apps through the tunnel.

## Progress log

* 2026-10-10 — written as backlog from the retired roadmap (its item "launching the apps").
* 2026-10-10 — the dependency on step 02 was dropped with that step's retirement to the backlog: the
  gate is whether the published app list gets used at all, which the operator answers directly, not
  data the supervisor would have to collect first.
