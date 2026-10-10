<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B01 — App launch page

> **Retired 2026-10-10.** The launch URLs are opened in the browser through the container's published
> proxies and this project does not grow a second, host-facing UI of its own (see
> `docs/ROADMAP.md`). Kept as the record of the direction and why it was dropped; the live plan is
> [`../plans/`](../plans/).

Status: ⏹ retired 2026-10-10 — the browser reaches the apps through the container's proxies
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
* 2026-10-10 — **retired, not implemented.** The operator's answer to the gate above: one app, opened
  from a bookmark, with a per-URL proxy rule in the browser sending that launch URL to `127.0.0.1:8888`
  and everything else direct - the app list is not used as a list, so a landing page would only replace
  a bookmark. A third party's case has the same shape (a browser, a proxy rule, the URL), and a second,
  host-facing UI is what `docs/ROADMAP.md`'s "No GUI of our own" rules out. The one piece worth keeping
  is the host-side recipe, which `README.md` now spells out beside `--apps`; the "one proxy alias per
  app" alternative would only pay off with many apps or with a browser that cannot be given a proxy
  rule, and the project has neither case.
