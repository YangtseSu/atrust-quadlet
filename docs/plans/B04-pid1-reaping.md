<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B04 — PID 1 reaps what the sweep leaves behind

Status: ⏸ backlog
Depends on: —
Touches: `atrustd/__main__.py`, `tests/test_reap.py`, `docs/DESIGN.md`

## Goal

`atrustd` is PID 1 inside the container, so every process whose parent dies is reparented to it. The
client family it sweeps on every recovery (`tokens.stop_client_family()`, and the Electron children
that go with the trays) leaves a handful of `[aTrustTray] <defunct>` / `[aTrustAgent] <defunct>`
entries behind, and a PID 1 that never calls `waitpid` keeps them forever. Measured 2026-10-11 on the
live container: 2 zombies with `PPID 1` (`aTrustAgent`, `tinyproxy`) at a quiet moment, ~15 in a `ps`
listing taken while a sweep was running.

They cost nothing by themselves (no CPU, no memory beyond the task struct), which is why nothing has
noticed them - but they are not free in the container: podman's default `--pids-limit` is 2048 and a
zombie still counts as a task, measured in a throwaway container with `--pids-limit 30`, where the
30th unreaped `fork()` failed with `EAGAIN` while 29 zombies were held. A container left running long
enough fills its limit with dead entries, and then nothing new can start: the client family would not
come back up and the supervisor would report a client that never restarts, with nothing in the journal
saying why.

## Deliverables

- ⏸ `atrustd/__main__.py` reaps: a small `reap_orphans()` (`os.waitpid(-1, os.WNOHANG)` in a loop
  until it returns 0 or raises `ChildProcessError`), called once per supervision cycle and right after
  `tokens.stop_client_family()` on the way out. Deliberately not a `SIGCHLD` handler: that would
  steal the exit statuses of the module's own `subprocess.run` calls (`ip`, `xdotool`, `xwd`), which
  wait for them directly.
- ⏸ `tests/test_reap.py`: a forked child that exits is collected by the reaper (a second
  `waitpid(pid, WNOHANG)` raises `ChildProcessError`), and the call is harmless with no children.
- ⏸ Live verification, recorded in the `## Progress log` with before/after counts: force a
  client-family sweep in the container (`pkill -x aTrustTray` and friends; the restart loop brings the
  family back) and show `ps` with no `<defunct>` entry whose parent is PID 1.
- ⏸ `docs/DESIGN.md`'s "Stopping the container" section mentions the reaping beside the sweep.

## Exit criteria

- ⏸ The live container shows no reparented zombies after a sweep, the suite stays green, and the
  reaper never interferes with a `subprocess.run` status (the suite's own callers cover that).

## Progress log

* 2026-10-11 — recorded while closing step 11, from the `ps` output of the live container and the
  `--pids-limit` measurement above.
