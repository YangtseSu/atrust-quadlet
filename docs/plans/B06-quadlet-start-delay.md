<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B06 — A start waits ~90 s on `network-online.target`

Status: ⏸ backlog — a start works, it is just 95 s late
Depends on: — (measured on the live host, 2026-10-11)
Touches: `quadlet/atrust.container`, `README.md`, `docs/DESIGN.md`, `docs/plans/README.md`

## Goal

Quadlet adds an implicit network dependency to every user container unit: `Wants=` and
`After=podman-user-wait-network-online.service`. Measured on this host by running the user generator
against scratch units: the dependency is emitted for a unit with and without an `[Unit]
After=network-online.target` line of its own, so the unit's own line is *not* what causes it and
dropping that line does not remove it. Quadlet's man page documents the opt-out for this implicit
dependency: `[Quadlet] DefaultDependencies=false` (not to be confused with systemd's `[Unit]
DefaultDependencies`, which means something else).

The helper is podman's own unit (`/usr/lib/systemd/user/podman-user-wait-network-online.service`):

```ini
TimeoutStartSec=90s
ExecStart=/bin/sh -c 'until systemctl is-active network-online.target; do sleep 0.5; done'
```

so it only *queries* the system manager's `network-online.target` - it never starts it - and the
container's own start job waits for the helper's job either way. The dependency is only `Wants=`, so
the helper's failure does not fail the container; it just costs the 90 s first.

On this host that target is inactive: the only unit that ever pulls it in is
`archlinux-keyring-wkd-sync.service` (through its weekly timer; `systemctl list-dependencies
--reverse network-online.target` lists nothing else), so for the rest of a boot in which that timer
has not fired yet, `systemctl is-active network-online.target` answers `inactive` and the helper
polls until its timeout. Measured 2026-10-11 on a host booted 19:16 (`restart`, and `stop` followed
by an immediate `start`): the stop returns in 2 s and the container's `Starting` comes 95 s later,
with the journal naming the helper (`podman-user-wait-network-online.service: start operation timed
out. Terminating.` after `TimeoutStartUSec=1min 30s`). The automatic path pays it too: the unit's
one `Restart=always` restart (2026-10-10) shows `Scheduled restart job` at 20:56:16 and `Starting
aTrust ...` at 20:57:47 - 91 s where `RestartUSec=100ms` was asked for. When the target *is* up, what
it means is `NetworkManager-wait-online.service` -> `nm-online -s -q`: NetworkManager has activated
every auto-activate connection it could - nothing pings, and no particular link is named.

Nothing in the project needs that order: the supervisor retries the portal login on its own backoff
(base 15 s, doubling) and the client retries its own connect - that is what the supervisor is for.
The finding is written down instead of fixed on the spot because removing the wait changes what the
unit assumes at boot: on a host whose link really is down when the unit starts, the client would come
up against a network that is not there yet and the supervisor would have to carry the whole recovery
- which is the design, but it has not been measured. The unit's own `After=network-online.target`
line is inert in a user manager (podman's man page: user units cannot wait for system units, so that
target "doesn't do anything there and is instead ignored"); whether it stays as a hint for a
deployment that installs the unit in the system manager is part of what this step decides.

## What upstream says (checked 2026-10-11)

It is podman's own workaround, they know about it and there is no fix yet:

* `containers/podman#22197` ("Podman fail to autostart containers through quadlet", closed as
  completed) is where it came from - rootless pasta containers failed at boot because pasta needs
  the host's addresses. `containers/podman#24305` (in 5.3.0) landed the shipped helper unit and the
  implicit dependency this file turns off.
* `containers/podman#24796` ("User units and network-online.target", **open** since 2024-12-08,
  last activity 2026-06-13) is the same report this file makes, from Arch, Debian 13, openSUSE
  Leap/MicroOS, Fedora CoreOS, Flatcar, NixOS and Manjaro - and its 2024-12-09 comments reach the
  same conclusion measured here: on Arch the only unit that ever pulls the target in is
  `archlinux-keyring-wkd-sync.service`, so it stays `inactive` and the helper times out.
* The maintainers' position in that thread: a user unit cannot wait for a system unit
  (`systemd/systemd#3312`), activating the target as root is not podman's business, the helper is
  an ugly workaround, and the proper fix is pasta updating its addresses and routes dynamically
  (`bugs.passt.top` 141 / the netlink-monitor pad) - after which they would drop the helper
  (a 2025-10-16 comment suggests reverting it "maybe as part of 6.0"; the 6.1.3 here still ships it
  unchanged).
* The opt-out is documented upstream (`DefaultDependencies=false` in the `Quadlet` section) and
  confirmed working by others in the thread. Verified here both ways: the generator's output drops
  `Wants=`/`After=` for the helper, and with a scratch unit plus a real `systemctl --user
  daemon-reload`, `systemctl --user show` reports `Wants=` empty and no `network-online.target` in
  `After=`. The documented way to look at a generated unit without installing it is
  `QUADLET_UNIT_DIRS=<dir> podman-system-generator --user --dryrun`.
* Host-side alternatives the thread records, for a deployment that cannot change the unit: make the
  *system* target actually reachable (a `network.target.requires/network-online.target` symlink via
  `systemctl --system add-requires network.target network-online.target`, a symlink into
  `multi-user.target.wants/`, or a small anchor service that `Wants=After=network-online.target`),
  or mask the helper in the user session (`systemctl --user mask
  podman-user-wait-network-online.service`). All of them change the host, not the unit, which is why
  this step prefers the `[Quadlet]` line.

The "make the target reachable" direction is not the one this step takes, and systemd's own guidance
says so (`docs/NETWORK_ONLINE.md`): the target is deliberately *not* pulled into the boot - "normally,
if no service requires it ..., this target is not pulled into the boot, thus avoiding any delays
during boot should the network not be available"; "if a network DHCP server does not react, this
should not slow down boot"; and "if you are a developer, ... please just fix your program to be
friendly to dynamically changing network configuration". A failing wait does not fail the boot -
measured in a user manager here with scratch units: with a wait that exits non-zero, the target still
becomes active and the ordering anchor still starts, in 40 ms - but it *delays* the boot by up to the
target's own timeout, which is the deliberate trade-off of that direction and the wrong one for a
host that must come up with no network. The program on this side of the equation is a supervisor that
retries with a backoff, so what this step measures is removing a wait, not adding one.

## The candidates, and the one this step takes

Five ways out were on the table. The host must boot with no network, which alone rules one of them
out; the rest separate on who has to change what.

| candidate | the good | the cost |
|---|---|---|
| do nothing | no change anywhere; the container always starts after the network, so a first-run pull and pasta both have what they need | every start is 90 s late (boot, a crash restart, a manual one), the user manager's `default.target` is held with it, and the helper writes a journal line twice a second while it waits |
| `[Quadlet] DefaultDependencies=false` plus a retry policy (`[Service] RestartSec=` around 15 s, so an offline boot cannot trip systemd's start limit) | changes nothing on the host and nothing in the boot path, and the container comes up by itself once the network is there - the shape this project's supervisor already works in | needs the measurement below first: `podman run` with no host address (pasta) and a first-run pull with no network, and whether the unit then recovers on its own |
| `systemctl --user mask podman-user-wait-network-online.service` | one command, no root, immediate, reversible (`unmask`), and it covers every rootless Quadlet of that user | a host-local configuration the repository cannot ship, and without the retry policy it trades a slow start for a container that can stay failed after an offline boot |
| make the *system* target really reachable (an anchor unit, `systemctl --system add-requires network.target network-online.target`, a `multi-user.target.wants/` symlink) | the meaning the helper was built to proxy: the container really waits, and anything else ordering after the target benefits; `nm-online` cost this host nothing (started and finished in the same second, 22:54:03) | a network wait inside the boot transaction (bounded by the target's 90 s and `nm-online`'s 60 s) - the one thing a network-less boot cannot take; root and host-local |
| `[Service] ExecStartPre=` polling for a default route | delays only this unit | "guessing what online means", which podman upstream explicitly rejected, and it is wrong where there is no default route (an IPv6-only or host-only setup); still a wait |

This step takes the second row - the `[Quadlet]` line with a retry policy, measured first - because
it is the only candidate that needs nothing from the host and adds nothing to the boot path, while
the container's own retries (the client's restart loop, the supervisor's backoff) are the mechanism
this project already relies on. The mask is the relief a deployment can apply today, while the
measurement runs. The system-target fix is right only for a host that *wants* its rootless containers
to wait for the network, which is not the machine this file was written on. The route poll is
rejected upstream for guessing, and doing nothing is what this file exists to stop. One day none of
this may matter: podman plans to drop the helper once pasta updates its addresses itself (see the
section above).

If that host-side direction is ever taken, the *shape* of the puller decides whether it gates the
boot, and that was measured here in a user manager against a 3 s stand-in for the wait service:

| puller shape | `systemctl start` returned after | waits? |
|---|---|---|
| a target that `Wants=` the wait - which is what a `multi-user.target.wants/network-online.target` symlink or `systemctl add-requires network.target network-online.target` amounts to | 3.02 s | yes |
| a *service* with `Wants=` and **no** `After=`, `Type=oneshot`, `ExecStart=/bin/true` | 0.02 s | no - the target runs in the background |
| the same service with `After=` added | 3.04 s | yes |

A target's job waits for everything it wants (which is also why `multi-user.target` is only reached
once its enabled services have started), so the symlink and `add-requires` forms trade boot time for
the wait, bounded by the target's 90 s and `nm-online`'s 60 s. The only non-gating puller is the
third shape, and it is the one a host-side fix would have to use: it drags `network-online.target`
into the transaction without anything ordering after it.

## Deliverables

- ⬜ Measure a start with `[Quadlet] DefaultDependencies=false`: wall clock from `start` to `Starting`
  and to `ONLINE` on a host whose network is already up, and what the supervisor logs on one whose
  link comes up later. The offline case is part of it, because a host has to boot without a network:
  what happens when the container cannot start at all (pasta with no host address to copy, or a
  first-run image pull with no network)? `Restart=always` retries every 100 ms, but systemd's default
  start limit gives up after 5 attempts in 10 s, so the measurement has to say whether the unit then
  stays failed until a manual start - and if it does, which of `StartLimitIntervalSec=`,
  `StartLimitBurst=` or a `RestartSec=` the unit needs to come up by itself once the network is there.
- ⬜ If the client comes back the same way, land the line (and decide what the now-dead `[Unit]
  After=network-online.target` becomes) and write down in `docs/DESIGN.md` what orders the start
  instead.
- ⬜ The live numbers (stop -> `Starting` -> `ONLINE`, with and without) in this file, and what the
  README's quick start should say, if anything.

## Exit criteria

- ⬜ A `systemctl --user restart atrust.service` reaches `ONLINE` without the 90 s gap, or the step
  closes with the reason the wait has to stay.

## Progress log

* 2026-10-11 — found while re-running the live container for step 13. `systemctl --user stop`
  returned in 2 s and the container was created 95 s later; the helper's timeout line and the
  `inactive` system target are quoted above. The same run's stop path (`client stop took 1.60s`, the
  container died 1.67 s after the signal) is unaffected - the delay sits in the start job only.
* 2026-10-11 — corrected the same day: the first version of this file blamed the unit's own
  `After=network-online.target` and proposed dropping it, and the generator run against scratch units
  shows that the `podman-user-wait-network-online.service` dependency is Quadlet's implicit one and
  appears either way. Also corrected: the system target is not unreachable forever, it is down until
  something pulls it in, and on this host that is only the weekly keyring timer; the documented
  opt-out is `[Quadlet] DefaultDependencies=false`.
* 2026-10-11 — the automatic path measured the same way, from the unit's own journal: the only
  `Restart=always` restart in its history shows `Scheduled restart job` at 20:56:16 and `Starting
  aTrust ...` at 20:57:47 on 2026-10-10 - 91 s, against the `RestartUSec=100ms` systemd was asked
  for. So the 90 s is not a manual-`systemctl` artifact; it sits in every start job of the unit while
  the system target is down.
* 2026-10-11 — upstream checked (see "What upstream says"): the helper is podman's own, shipped by
  PR #24305 for #22197; the open issue for exactly this symptom is #24796, where users on Arch,
  Debian, openSUSE, Fedora CoreOS, Flatcar, NixOS and Manjaro report the same 90 s and the
  maintainers say the real fix is pasta's netlink monitor, after which the helper would be dropped
  (still present in 6.1.3 here). The documented `[Quadlet] DefaultDependencies=false` opt-out was
  verified on this host end to end: the generator drops the `Wants=`/`After=` lines and, after a real
  `systemctl --user daemon-reload` of a scratch unit, `systemctl --user show` has `Wants=` empty and
  no `network-online.target` in `After=`.
* 2026-10-11 — the five candidates compared under "The candidates" and this step's choice recorded:
  the `[Quadlet]` line with a retry policy, measured first, because it needs nothing from the host
  and adds nothing to the boot path; the user-session mask is named as the relief a deployment can
  apply today, and the system-target direction as right only for a host that wants its rootless
  containers to wait for the network.
* 2026-10-11 — the puller shapes measured before anyone writes one (3 s stand-in, user manager):
  a target that `Wants=` the wait (the `.wants/` symlink and `add-requires` forms) waits - 3.02 s;
  a service with `Wants=` and no `After=` does not - 0.02 s; the same service plus `After=` waits
  again - 3.04 s. So a host-side fix, if it ever happens, has to be the third shape.
