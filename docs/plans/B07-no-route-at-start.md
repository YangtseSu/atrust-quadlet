<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B07 — A container started with no usable route comes up dark

Status: ⏸ backlog — measured 2026-10-15 while closing B06; no mechanism chosen
Depends on: — (the measurement is in this file; a sandbox's own routes are readable from inside)
Touches: `quadlet/atrust.container`, `atrustd/__main__.py`, `tests/`, `docs/DESIGN.md`, `README.md`

## Goal

B06 took the 90 s wait off the unit's start, and with it the window in which the network could come up
*before* the container did. What is left is the case that wait accidentally covered: the host has no
usable address when the container starts - a Wi-Fi credential in the login keyring, a slow DHCP, a
link that comes up after the user logs in.

Measured 2026-10-15 (podman 6.1.4, the pasta it ships - `2026_10_02` - and this repository's image):

* pasta **starts** such a container: in a netns with no usable address (`unshare -rn`, a dummy
  interface carrying only a link-local) it prints "No interfaces with usable IPv4/IPv6 routes ... use
  local mode" and configures the sandbox with `169.254.2.1/16` and no route out, exit 0 - not the
  start failure B06's file had assumed.
* pasta decides at startup: an address and a default route added to the host after the sandbox came
  up never reached it (the sandbox's addresses sampled every second for ten seconds stayed in local
  mode).
* the supervisor then cycles exactly as designed - `STARTING -> DEGRADED -> LOGGED_OUT`,
  `GET /passport/v1/public/authConfig failed: <urlopen error [Errno 101] Network is unreachable>`,
  the client's own window driven to its `connection` page with the address typed in, `next attempt in
  15s`, and the `NEED_VNC` hint after 2 attempts (a `--network=none` throwaway container of the
  published image, 150 s) - and nothing inside the container can repair the route.

So the container is up, the state says what is wrong, the desktop notification fires, and the repair
is a container restart (`systemctl --user restart atrust`), which re-runs pasta now that the address
is there.

## The mechanisms this step weighs

* **Nothing, documented**: README's "Operating it" already carries the restart. Cheapest, and the
  state plus the notification make the case visible - a host that never logs in before its link is up
  never sees it.
* **An `ExecStartPre` that refuses to start without a usable route**, with the retry policy B06 landed
  (15 s apart) doing the waiting: the start then happens when pasta would find a template. The check
  has to mirror pasta's own criterion (an interface with a usable - not loopback, not link-local -
  route, in either family) and it has to fail open: where it cannot decide, the container still
  starts, or a wrong guess means a unit that never comes up. It reads `/proc/net/route` and
  `/proc/net/ipv6_route` on the host, so no `iproute2` is needed.
* **A watchdog inside the supervisor**: exit when the sandbox has had no route out for N minutes, so
  `Restart=always` rebuilds the container (pasta re-runs and finds the address now). The signal is
  precise and local (the sandbox's own route files: the healthy sandbox carries the host's default
  route through the copied interface, the local-mode one only the `169.254.0.0/16` on-link route), but
  it is a new exit path in `atrustd`, and N has to be long enough that a roaming or briefly
  reconnecting link is not mistaken for a missing one.

## Deliverables

- ⬜ The sandbox's own route files measured on both sides - a healthy container and a local-mode one
  (`/proc/net/route`, `/proc/net/ipv6_route`) - so whatever reads them is pinned by data rather than
  by the shape of a `169.254` address.
- ⬜ One mechanism landed, or the step closed with the reason the operator's restart stays.
- ⬜ The live acceptance: a container started while the host has no usable address comes up by itself
  once one appears (a dummy interface added to the host's netns is enough to reproduce), or the step
  records why it cannot.

## Exit criteria

- ⬜ A start on a host whose address appears later reaches `ONLINE` without a human, or the step
  closes with the reason the restart stays in the README.

## Progress log

* 2026-10-15 — opened from B06's measurement; the local-mode pasta run, the dark supervisor's own log
  and the "the state is visible, the repair is a restart" note are in B06's `## Progress log`.
