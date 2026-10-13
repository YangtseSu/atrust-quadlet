<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 20 — The probe target is found by the supervisor itself

Status: ✅ done
Depends on: — (the route table is what check #2 already reads; the discovery rule below is the one the
host-side keepalive script has been running with, and both were re-measured live for this step)
Touches: `atrustd/probe.py`, `atrustd/config.py`, `atrustd/__main__.py`, `tests/test_probe_retry.py`,
`tests/test_cycle_pacing.py`, `quadlet/atrust.env.example`, `README.md`, `docs/DESIGN.md`,
`docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

`ATRUST_PROBE_TARGET` is one of the few things a deployment has to know about its own intranet: a
`host:port` that (a) answers HTTP, so the request is real traffic and keeps the portal's session from
expiring (an `https` target is probed with `CONNECT` and does not count as activity), and (b) is
reachable only through the tunnel, so an answer proves the tunnel and a failure means something. Getting
it wrong used to be the trap the environment example named: a value that never answers kept the
supervisor in `DEGRADED` and restarted the client for nothing.

This step makes the supervisor find the target itself, and settles two questions:

* **which source** - the portal's app list (this project already fetches it: `atrustd.apps`, written to
  `apps.json` at every successful portal login) or the tunnel's own route table (the host-side keepalive
  script's `discover_target`: `ip route show dev <tun>`, the bare host routes, one real request each,
  the first that answers wins);
* **what a failing target means** - the case "the value does not answer while the client is plainly in a
  session": today it is a `DEGRADED` that restarts the client, logs the portal in again and can end in a
  `NEED_VNC` hand-over. A target that is only a *witness* must not be able to do that on its own.

## The decision

**1. The tunnel's own routes are the source; the portal's app list is not.**

| | the app list (`apps.json`) | the tunnel's routes |
|---|---|---|
| exists when | a portal login landed in this container (`publish_apps`, called on every successful login and by `--apps --refresh`) | the datapath is up - i.e. exactly the moments the probe needs a target |
| a captcha deployment (`graphCheckCodeEnable: 1`, both logins stopped, the human logs in over VNC) | **nothing**: the engine's login never lands, so the file is never written | works: the client routes the resource list it got from its own login |
| what it names | an address the portal says the account *may* launch - nothing there says the tunnel routes it now, or that it answers | an address the tunnel currently routes, so a success proves the tunnel |
| evidence before use | none: its first test is the deciding probe | the request that finds it *is* a probe: only a candidate that answered becomes a target |
| cost | none extra | one request per candidate, only while nothing is configured |

The live container (2026-10-13, tunnel `ONLINE`) shows both sources agree where both exist - the route
table's first bare entry is the address the portal's app list names (`http://10.0.0.10/`,
`tcp 10.0.0.10:80`) - but only the route table exists without a session, and only it can hand out a
target that has already answered. The app list stays what it is: the apps this account may launch, for
the human (`atrustd --apps`, `apps.json`); its addresses can be pinned into `ATRUST_PROBE_TARGET` when a
deployment wants them.

**2. A target is a witness: one that fails stops nothing while another answers.**

The question the probe answers is "does the tunnel carry traffic", not "is that one host up". So each
check probes the configured target(s) **and** the candidates off the tunnel's own routes (one round, one
short attempt each, `PROBE_ATTEMPTS` rounds - the first answer wins), and the cycle is `ONLINE` as soon
as one of them answers:

* a configured target that cannot answer while another witness can: `ONLINE`, no client restart, no
  login, and the state detail says which witness answered (`no answer from <configured>; probe <route>
  ok (HTTP/1.1 200, route)`) - the operator reads their own value's state there and fixes the config if
  they want it to be the one;
* nothing answering at all, datapath up: `DEGRADED`, as before - that is the honest verdict and the case
  the recovery paths exist for. A deployment whose only routed host goes down for long reads it as a
  tunnel fault; the escape hatches are below;
* datapath down (no interface, no routes): nothing is probed - unchanged, and it must stay that way, or
  the probe's retry budget is paid on every cycle of an already-known-down tunnel.

**3. The configuration stays, and one switch is new.**

* `ATRUST_PROBE_TARGET` keeps its grammar (`host:port[,host:port]`, `ATRUST_PROBE_TARGET`) and its
  meaning as the witness the operator names; the only change is that an *unreachable* value no longer
  decides alone while another witness answers, and that **empty** now means "discover" instead of "no
  probe".
* `ATRUST_PROBE_DISCOVER` (default on) is the way back: `0` makes the interface and its routes the proof
  again - the supervisor this project had before this step, for a deployment whose routed hosts flap
  enough that a probe target should not be used at all.

## Deliverables

- ✅ `atrustd/probe.py`: the witness list (configured first, then the tunnel's route-derived candidates,
  deduplicated, capped), the round-robin probe (`PROBE_ATTEMPTS` rounds, the first answer wins), the
  route-line parse (a bare address or an explicit `/32` - the client's own subnet carvings are not
  candidates), `DISCOVERY_TIMEOUT = 3.0` for a route-derived candidate and `PROBE_TIMEOUT = 8.0` for a
  configured one - both with their measured numbers beside them. `proxy_probe` (the single-witness
  primitive) is gone: `probe_witnesses` is the one probe, and its single-witness case keeps the retry
  budget and the failure sentence the tests pinned.
- ✅ `atrustd/config.py`: `ATRUST_PROBE_DISCOVER` through the existing `flag()` helper.
- ✅ `atrustd/__main__.py`: one `data_plane(cfg)` helper carries the switch for the five `probe.check`
  call sites; nothing else moves (the tests' `probe.check` mocks still intercept it).
- ✅ Tests: the route-line parse (a live-shaped table → the two host routes, subnet carvings and IPv6
  out), the witness rule (a failed configured witness + an answering route-derived one → `online` with
  both in the detail; nothing answering → not `online`), the discovery wiring through `check()`, and the
  environment parse of the new switch.
- ✅ `README.md` (the `ATRUST_PROBE_TARGET` row rewritten around the witness rule, the new
  `ATRUST_PROBE_DISCOVER` row), `quadlet/atrust.env.example`, `docs/DESIGN.md` (supervisor step 3).
- ✅ Live: one `--once` cycle with `ATRUST_PROBE_TARGET` unset against the running container's tunnel,
  showing the discovered target answering in the state detail; the numbers quoted below.

## The measurement (live, 2026-10-13, the running dev container)

`ip route show dev utun7` holds 30 entries, of which exactly two are bare host routes - the two
candidates the parse keeps:

```
10.0.0.10      <- the address the portal's app list names (and the value in ~/.config/atrust.env)
198.18.255.1   <- the client's own virtual range, a bare route of the netstack's carve-up
```

Both were probed through the container's proxy the way the supervisor does it (`GET http://<addr>/` to
`127.0.0.1:8888`, user agent `atrustd`):

| candidate | answer |
|---|---|
| `10.0.0.10:80` | `HTTP/1.1 200` in **0.03 s** |
| `198.18.255.1:80` | **times out at the full 8.0 s** - no refusal, the netstack swallows it |

What the two numbers buy: a route-derived candidate is probed on a **3 s** leash (the accept/reject
budget a search can afford, and the same leash the host-side keepalive script uses for its own
discovery and its down-state cross-check), while the address a human named keeps the **8 s** the probe
has always used - a slow-but-alive intranet server must not lose its witness because a search pass was
impatient. A junk candidate (the pool address) costs its 3 s per round and nothing else; the worst case
of a check with nothing answering is `PROBE_ATTEMPTS` rounds over the two candidates plus the retry
delays, which is the budget a single configured target has always paid.

## The acceptance (live, 2026-10-13, the same container, the changed modules copied beside the image's)

The running daemon keeps the image's own `atrustd`; the step's modules were copied into
`/tmp/probe-check` in the container and imported from there (`PYTHONPATH`), so nothing the live
supervisor runs moved. One `--once` cycle with `ATRUST_PROBE_TARGET` unset, into a scratch state dir:

```
INFO atrustd: STARTING -> ONLINE (tunnel up)
detail: "utun7 2.0.0.1/24; 30 route(s) via utun7; probe 10.0.0.10:80 ok (HTTP/1.1 200, route)"
```

The three shapes `check()` has to answer, through the container's own tunnel (the first two in the same
run; the third is the case this step exists for):

| what | result |
|---|---|
| nothing configured, discovery on | `online=True probes_configured=True` - `... probe 10.0.0.10:80 ok (HTTP/1.1 200, route)` |
| nothing configured, `ATRUST_PROBE_DISCOVER=0` | `online=True probes_configured=False` - `utun7 2.0.0.1/24; 30 route(s) via utun7`, no request sent |
| a configured target that cannot answer (`10.0.0.99:80`) | `online=True probes_configured=True` - `no answer from 10.0.0.99:80; probe 10.0.0.10:80 ok (HTTP/1.1 200, route)` in **8.25 s** (the dead witness's first 8 s attempt, then the route witness's 0.03 s) |

The third row is the decision's point: the address a human named does not answer, the tunnel carries
traffic to the address the client itself routes, and the cycle is `ONLINE` with no restart, no portal
login and no `NEED_VNC` - the state detail names both.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` (128) and `reuse lint` stay green.
- ✅ Live: the container's tunnel `ONLINE`, a `--once` run with `ATRUST_PROBE_TARGET` unset writes a
  state detail whose `probe ...` half names the discovered address and carries `route`; with the switch
  off the same check names no probe at all (`probes_configured=False`, the interface and its routes are
  the proof).
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened with the decision made: the tunnel's own routes are the source (the app list loses
  on the captcha deployment it cannot serve, and on having no evidence before use), a witness that fails
  does not stop the cycle while another answers, the configuration stays with `ATRUST_PROBE_DISCOVER` as
  the way back to the data-plane-only supervisor. The live numbers the constants are sized with are
  above.
* 2026-10-13 — implemented and accepted in the same session. `probe.py` carries the witness list, the
  round-robin probe and the two leashes (the old single-target `proxy_probe` folded into
  `probe_witnesses`); `Config.probe_discover` parses through `flag()`; `data_plane()` in `__main__.py` is
  the one call site shape; the README row, the environment example and `docs/DESIGN.md`'s supervisor
  section carry the rule. Offline: 128 tests green (11 in `tests/test_probe_retry.py`, four of them new -
  the witness rule, the route parse, the wiring through `check()`, and the switch's parse) and `reuse
  lint` clean. Live, quoted under "The acceptance": the `--once` cycle with no configured target names
  the discovered witness (`probe 10.0.0.10:80 ok (HTTP/1.1 200, route)`), the switch off names none, and
  a configured target that cannot answer leaves the cycle `ONLINE` through the route witness in 8.25 s.
