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
* 2026-10-10 — measured on the live profile of one host: `.aTrust/logs` 145 MiB, whole profile
  154 MiB, ~124 MiB of it rotation ceilings that never grow (xtunnel 2x20 MiB + plugin-daemon
  2x20 MiB + tcpAccess 1x20 MiB + `aTrustTray.<date>.log.back` 23.7 MiB). Every absolute number in
  this entry is one host's sample, not a baseline: the same file layout yields a different total on a
  second machine with another traffic pattern, so a later pass compares the *layout* (which file
  rotates to what ceiling, which series has no ceiling) and re-measures the size where it matters.
  What the rate is made of on that host: ~60 MiB/day from the plugin daemon's own permission check —
  five paths per pass, each re-resolving the login user and logging three `getCurrentUserNameByPopen`
  lines, every 5 s, ~500 lines/min — plus ~4 MiB/day of per-day `aTrustTray.<date>.log`. The daemon's
  own files are bounded by its rotation; the tray's daily files are the one series with no ceiling,
  and whether the tray deletes old ones is unverified (that profile was two days old).
* 2026-10-10 — the error half of that churn was ours, and is fixed: `/home/sangfor/.config/aTrustTray`
  did not exist in the container (the package's postinst makes the home, not this), so the daemon's
  `repairPermission` failed with `errno=2` once per 5 s pass and kept its 2x20 MiB
  `aTrustAgent_plugin-daemon_error.log` rotation turning. Creating the directory (0777 — the mode the
  repair itself asks for) in the running container stopped the errors at once, and the durable form is
  `base/Containerfile`'s `install -d`. That is a `fix:` commit and does not open this step. The
  remaining 60 MiB/day is upstream's own logging inside `libaTrustDaemon.so` — no level, size or
  backup-count knob found (no config file in the package, no environment variable or argument in the
  binary), so the tooling decision this step carries is the tray's daily files.
