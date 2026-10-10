<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 08 — Client process family on container stop

Status: 🚧 in-progress — the code and the copy measurements are done; the live-container acceptance
is left (it needs the new image published and the container restarted in a maintenance window)
Depends on: a maintenance window for the live acceptance (the container has to be restarted)
Touches: `atrustd/__main__.py`, `atrustd/tokens.py`, `tests/test_stop_family.py`,
`tests/test_cycle_pacing.py`, `quadlet/atrust.container`, `docs/DESIGN.md`, `README.md`

## Goal

Stopping the container today always spends podman's in-container stop timeout. `run_daemon` sets a
flag from the SIGTERM handler but reads it only after `cycle()` returns, and CPython re-enters
`time.sleep` with the remaining timeout after a signal (PEP 475), so a stop lands anywhere inside a
`ATRUST_WATCH_INTERVAL` (90 s default), a `TUNNEL_WAIT` (120 s) or a `vnc_wait` (900 s) wait and is
answered only when that wait ends — after podman's default 10 s it SIGKILLs PID 1 and the runtime
tears the cgroup down.

That is the failure the AUR package's drop-in describes from the host side: the vendor unit sets
`KillMode=process`, so systemd signals only the main PID, while the client's own family — the core
plugin (`aTrustAgent --plugin plugins/aTrustCore`, user `sangfor`), the tunnel
`aTrustXtunnel-64` and its `-check 10 -ec 3 watchdog` child — lives on, holding `/home` and `/tmp`
until `systemd-shutdown` gives up. In a container the cgroup teardown does kill that family, so
nothing leaks here; what transfers is the shape of the fix and the reason to have it: the family is
reachable only by name, and the container's PID 1 has to be responsive for a stop to be graceful at
all. `killall $VPN_PROCS` in the vendored restart loop covers `aTrustAgent` only, and in the live
container both `aTrustXtunnel-64` processes have `PPID 1` (reparented), so no parent-based cleanup
would ever reach them.

Measured 2026-10-10 (podman 6.1.3, rootless, the published image):

| what was stopped | `podman stop` |
|---|---|
| a copy of the real image, real entrypoint, client family up (`aTrustTray`, `aTrustTray2`, 2× `aTrustAgent`, `aTrustXtunnel-64` + watchdog) | 8.4 s |
| a container whose PID 1 ignores SIGTERM, with a detached `setsid` orphan that also ignores it | 10.2 s (podman's full `--stop-timeout`, the default) |

No `aTrust*` process survived either stop (13 host PIDs of the copy checked after `podman stop`).

## Deliverables

- ✅ `run_daemon` waits on a `threading.Event` instead of `time.sleep` (`pause()`), and the waits
  that can last minutes - `wait_for_tunnel`, the `ATRUST_VNC_WAIT` loop - take the same event, so
  SIGTERM is answered within a second from any of them. A stop inside a cycle still waits for the
  step it is in (a UI step, a probe retry): seconds, and recorded in `docs/DESIGN.md`.
- ✅ A stop sweep of the client family (`tokens.stop_client_family()`, `CLIENT_FAMILY`): SIGTERM to
  the tunnel with its watchdog child, the agents and the trays, then SIGKILL after 1 s for what is
  still there. Matching is by the binary's path (`pkill -f`), because `pkill -x` compares the
  command name and the kernel truncates that to 15 characters - the tunnel binary is
  `aTrustXtunnel-6` there. Measured: the tunnel, the trays and the client's own restarts leave on
  SIGTERM (the tunnel ends up a zombie nobody reaps, which `_live_pids` already skips), the plugin
  daemon and the Electron children do not (3 to 6 of the 12-13 family processes per run).
  The sweep belongs to the stop path only - `tokens.stop_client()` on the refresh path stays
  tray-only, which a copy measurement confirmed (trays gone, agent and tunnel alive).
- ✅ Quadlet `[Container] StopTimeout=5` (validated with `quadlet -dryrun`: `--stop-timeout 5` on the
  generated `podman run`), `[Service] TimeoutStopSec=20` kept as the outer bound.
- ✅ `docs/DESIGN.md` records what leaves on SIGTERM: the tunnel and the trays do, the agent and the
  Electron children need the SIGKILL, so the sweep is SIGTERM-then-SIGKILL rather than SIGKILL-only.

## Exit criteria

- ⬜ A stop on the live container with the tunnel up costs ≲2 s. Measured on copies of the published
  image with the client family up: `podman stop` 1.5 s, `podman rm -f` (what the Quadlet unit runs)
  1.9 s, the daemon's own sweep 1.27 s; in a synthetic `ONLINE` state the daemon leaves in 1.58 s.
  The live run is what is left: the running container still carries the published image, so this
  closes when the new image is published and the container restarted in a maintenance window.
- ✅ No `aTrust*` process remains on the host after the stop (13 host PIDs recorded before, 0
  survivors after).
- ✅ The refresh path is unchanged (see the third deliverable).

## Progress log

* 2026-10-10 — written as backlog from the AUR review with the two baseline measurements (a copy of
  the published image, throwaway, no effect on the live container).
* 2026-10-10 — promoted to step 08 and implemented. Verification was done in throwaway containers
  created from the published image with the changed `atrustd/` copied in (the image rebuild is CI's):
  * before the tuning (3 s SIGTERM grace): `podman stop` 4.4 s and `podman rm -f` 4.4 s, the daemon
    logging `signal 15` in both cases - so the Quadlet `ExecStop` does send SIGTERM, not SIGKILL.
  * after (`timeout=1.0`, `settle=0.5`): `podman stop` 1.5 s, `podman rm -f` 1.9 s, journal
    `3 of 12 client process(es) ignored SIGTERM, SIGKILLing [90, 1413, 91]` and `client stop took
    1.27s`, 0 survivors of the 13 recorded host PIDs.
  * steady state (probe patched to `ONLINE`, daemon waiting out the 90 s interval): exit 1.58 s
    after SIGTERM, 6 of 12 processes needing the SIGKILL.
  * tray-only refresh path: `tokens.stop_client()` left `aTrustAgent` and `aTrustXtunnel-64` alive
    and the loop brought the trays back.
  * `python3 -m unittest discover -s tests`: 12 tests, including the new
    `tests/test_stop_family.py` (SIGTERM first, SIGKILL for the survivor, nothing outside the
    family touched).
