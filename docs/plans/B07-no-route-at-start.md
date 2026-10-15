<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B07 — A container started with no usable route comes up dark

Status: ✅ done — 2026-10-15, the unit holds the start while the host has no usable route and comes up
by itself, 13 s after a route appears in the unit-level acceptance
Depends on: — (every number is in this file)
Touches: `quadlet/atrust.container`, `tests/test_route_check.py`, `docs/DESIGN.md`, `README.md`,
`docs/plans/README.md`

## Goal

B06 took the 90 s wait off the unit's start, and with it the window in which the network could come up
*before* the container did. What is left is the case that wait accidentally covered: the host has no
usable address when the container starts - a Wi-Fi credential in the login keyring, a slow DHCP, a
link that comes up after the user logs in.

Measured 2026-10-15 (podman 6.1.4, the pasta it ships - `2026_10_02` - and this repository's image):

* pasta **starts** such a container: in a netns with no usable address (`unshare -rn`, a dummy
  interface carrying only a link-local) it prints "No interfaces with usable IPv4/IPv6 routes ... use
  local mode" and configures the sandbox with `169.254.2.1/16` and a default route through its own
  `169.254.2.2` - nothing behind it, exit 0. Not the start failure B06's file had assumed, and not
  "no route out" either (this file's first version said so): the sandbox's own files carry the default
  route, and a connect in it is answered `ECONNREFUSED` in 0.0 s.
* pasta decides at startup: an address and a default route added to the host after the sandbox came
  up never reached it (the sandbox's addresses sampled every second for ten seconds stayed in local
  mode).
* the supervisor then cycles exactly as designed - `STARTING -> DEGRADED -> LOGGED_OUT`, its portal
  login failing `<urlopen error [Errno 101] Network is unreachable>` in the `--network=none` shape (no
  interface at all) and answered `ECONNREFUSED` in pasta's local-mode one, the client's own window
  driven to its `connection` page with the address typed in, `next attempt in 15s`, and the `NEED_VNC`
  hint after 2 attempts - and nothing inside the container can repair the route.

Without a hold the container is up, the state says what is wrong, the desktop notification fires, and
the repair is a container restart (`systemctl --user restart atrust`), which re-runs pasta.

## What landed

The hold, in the unit's own `ExecStartPre=` (no new host-side file: the unit stays one file to copy):
it exits 1 while the host has no route pasta could use, and the retry policy B06 landed tries again
15 s later. The rule mirrors pasta's criterion instead of guessing "online": IPv4 wants a non-loopback
route that is neither link-local (as a destination nor as a gateway) nor the broadcast address, IPv6 a
non-loopback route with a real prefix - a default route is *not* enough, because a default through a
link-local gateway is exactly what pasta's local-mode tap carries - and either family passes. A host
with an IPv4 default route, with only an on-link route, with only a static route, or with an IPv6
prefix and its default starts; the host that has nothing but link-local addresses waits. It fails open
where neither `/proc/net/route` nor `/proc/net/ipv6_route` can be read.

The two mechanisms that were weighed and not taken:

* **Documenting the restart** alone: it leaves the container dark and the repair to whoever notices -
  the reason this step exists.
* **A watchdog inside the supervisor** (exit after the sandbox has had no route for N minutes, so
  `Restart=always` rebuilds it): the signal is not as clean as this file first claimed (the local-mode
  sandbox *has* a default route, so "no route" would have to be spelled "a default through a link-local
  gateway", pasta's own shape rather than a fact about the host), it cannot tell a host that is offline
  for good from one whose address has simply not arrived - a permanently offline host would rebuild
  the container every N minutes - and it pays N minutes of darkness before its first attempt. The hold
  decides earlier, on the host, at the start, and costs nothing while it waits.

## Deliverables

- ✅ The sandbox's own route files measured on both sides: the healthy sandbox carries the host's
  copied interface (measured live as `enp34s0`, the host's own NIC name) with its default route, plus
  the client's `utun7` routes; the local-mode one carries `tap0` with `169.254.2.1/16`, a default
  through `169.254.2.2`, a link-local IPv6, a v6 default through `fe80::1` and nothing else. Both
  shapes are pinned in `tests/test_route_check.py`, the local-mode pair as the fixture that must be
  *held* - it is what a "it has a default route, so it is usable" rule would wrongly accept.
- ✅ One mechanism landed: the `ExecStartPre` hold, with B06's retry policy as the waiting and no file
  a deployment has to install.
- ✅ The live acceptance, in the three parts it could be measured in: (1) the check's decisions in
  netns of the real shapes - dark, link-local-only and the local-mode files held; a v4 default, an
  on-link-only route and a v6 prefix accepted; (2) the unit-level shape on a scratch unit with the
  same policy and the real snippet behind a gate - held while the gate is absent
  (`activating/auto-restart`, no `start-limit-hit`), `active` 13 s after the gate appeared, by itself;
  (3) the real unit on this host - the check passes, `systemctl --user restart atrust.service` reaches
  `ONLINE` in 15 s, no refusal in the journal. What could not be reproduced: the host's *own* netns
  darkened and then given an address. A user-level test cannot do it - a user unit's
  `PrivateNetwork=` netns cannot be entered or configured from outside (measured: `Operation not
  permitted` for both `nsenter` and an `ip link add` inside it) and cutting the real link is not a
  measurement tool. The chain from "a route appears" to `ONLINE` is the ordinary path every start of
  this unit takes, and it is measured in (3).

## Exit criteria

- ✅ A start on a host whose address appears later reaches `ONLINE` without a human: the unit is held
  (no dark sandbox is ever built), the retry policy starts it the moment a route exists (13 s on the
  scratch unit), and that start follows the ordinary path to `ONLINE` (15 s, measured live).

## Progress log

* 2026-10-15 — opened from B06's measurement; the local-mode pasta run, the dark supervisor's own log
  and the "the state is visible, the repair is a restart" note are in B06's `## Progress log`.
* 2026-10-15 — the sandbox side measured properly before choosing a mechanism: `podman
  --log-level=debug` shows the invocation (`pasta --config-net --dns-forward 169.254.1.1 -t none
  -u none -T none -U none --no-map-gw --quiet --map-guest-addr 169.254.1.2 --netns
  /run/user/1000/netns/netns-<uuid>`), and a netns that carries no usable address gives the local-mode
  files quoted above, every connect in that sandbox answered `ECONNREFUSED` in 0.0 s. pasta's own
  accept/refuse decisions were probed the same way: a v4 on-link route alone is a template, a v4
  static route *without an address* is not, a link-local v4 address alone is not, and a v6 prefix with
  its default is - and pasta answers per family, so a host can be local-mode on v4 and templated on
  v6 at once.
* 2026-10-15 — the check written as one `sh -c` line in the unit's `ExecStartPre=` (the unit stays a
  single file to copy) with `[ -r ]` guards and "neither file readable, start anyway" as the fail-open
  door. Its decisions were measured in `unshare -rn` netns of each shape before it was installed -
  dark, v4 link-local, v4 default, v4 on-link, v4 static-without-address, v6-only, and this host - and
  the live restart it precedes still reached `ONLINE` in 15 s.
* 2026-10-15 — the local-mode fixture caught a real hole in the first IPv6 arm, which accepted any
  non-link-local destination: that sandbox's v6 default (through `fe80::1`) was the one route the rule
  let through. The arm now wants a real prefix (`plen` not `00`), which also makes the v6 default route
  of a correct host irrelevant instead of necessary.
* 2026-10-15 — the unit-level acceptance on a scratch unit (`StartLimitIntervalSec=0`,
  `RestartSec=15s`, the real snippet behind a gate file): `activating/auto-restart` while the gate is
  absent, no rate-limit hit, `active` 13 s after the gate appeared - the start came by itself.
* 2026-10-15 — landed: the unit, `tests/test_route_check.py` (it reads the snippet out of the unit and
  runs it against the measured fixtures, so the rule under test is the rule shipped),
  `docs/DESIGN.md`'s "Starting the container" (the hold, the rule, the shapes) and the README
  paragraph. B06's log gained the two corrections this step forced: the local-mode sandbox does carry
  a default route, and the case that paragraph left to the operator is closed.
