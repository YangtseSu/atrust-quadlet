<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# B04 — PID 1 reaps what the sweep leaves behind

Status: ✅ done — 2026-10-11, before/after in throwaway containers and the live acceptance on the
published image (`v1.5.0`): its first cycle and the cycle after the login recovery each reclaimed
the corpse that appeared in between, recorded in the log below
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

- ✅ `atrustd/__main__.py` reaps: a small `reap_orphans()` (`os.waitpid(-1, os.WNOHANG)` in a loop
  until it returns 0 or raises `ChildProcessError`), called once per supervision cycle and right after
  `tokens.stop_client_family()` on the way out. Deliberately not a `SIGCHLD` handler: that would
  steal the exit statuses of the module's own `subprocess.run` calls (`ip`, `xdotool`, `xwd`), which
  wait for them directly.
- ✅ `tests/test_reap.py`: a forked child that exits is collected by the reaper (a second
  `waitpid(pid, WNOHANG)` raises `ChildProcessError`), and the call is harmless with no children.
  A third case pins that a live child is left alone, so a `subprocess` caller keeps its status.
- ✅ Live verification, recorded in the `## Progress log` with before/after counts: force a
  client-family sweep in the container (`pkill -x aTrustTray` and friends; the restart loop brings the
  family back) and show `ps` with no `<defunct>` entry whose parent is PID 1. Done in throwaway
  containers on both images, the real client family up (0 defunct with the reaper, 20 and growing
  without it).
- ✅ `docs/DESIGN.md`'s "Stopping the container" section mentions the reaping beside the sweep.

## Exit criteria

- ✅ The live container shows no reparented zombies after a sweep, the suite stays green (70 tests),
  and the reaper never interferes with a `subprocess.run` status (the suite's own callers cover that;
  the live run logged no failed cycle either).

## Progress log

* 2026-10-11 — recorded while closing step 11, from the `ps` output of the live container and the
  `--pids-limit` measurement above.
* 2026-10-11 — implemented: `reap_orphans()` in `atrustd/__main__.py`, called at the top of
  `cycle()` and right after `tokens.stop_client_family()` in `run_daemon`; `tests/test_reap.py`
  (exited child collected, empty reap harmless, live child keeps its status). Offline:
  `python3 -m unittest discover -s tests` 70 tests green, `reuse lint` clean.
* 2026-10-11 — live before/after, throwaway containers of both images (fresh profile,
  `ATRUST_WATCH_INTERVAL=15`, `ATRUST_VNC_WAIT=60`, `NET_ADMIN` + `/dev/net/tun` like the unit; the
  forced sweep was SIGTERM then SIGKILL over the three `CLIENT_FAMILY` patterns, `podman top` for
  the ps):
  * published image (no reaper): 2 zombies under PID 1 at the quiet baseline, 18 three seconds after
    the sweep, 20 thirty seconds later - none of them ever left, and the production container on the
    same image showed its own 2 (`tinyproxy`, `aTrustAgent`) after 18 minutes.
  * `localhost/atrust-quadlet:dev`, built from this tree: the first cycle-top reap collected the
    startup one (`reaped 1 orphan(s)`); the same sweep left 12 after three seconds and 13 at t+30 s,
    and the next cycle top took all of them (`reaped 13 orphan(s)`, 0 defunct); the restart loop had
    the family back (12 processes); the stop path logged `signal 15 received` -> `client stop took
    1.28s` -> `reaped 10 orphan(s)`; no failed cycle, so the `ip`/`xdotool`/`xwd` `subprocess.run`
    callers kept their statuses.
  The production container still runs the published image and keeps its 2 zombies until its next
  pull; the fix ships with the next push of this tree.
* 2026-10-11 — shipped as `v1.5.0`. The commits went to `main` and the signed annotated tag was
  pushed; the pipeline was green in ~1.5 min for both refs (base unchanged, its jobs skipped; runs
  38089902196 for the tag and 38089846067 for the branch), `:1.5.0`, `:1.5` and `:latest` resolve to
  the same multi-arch index
  (`sha256:2b93884af08450d795aa815afd0ca99c0cd91c2191d219c8ed73667a9c4623d6`, in the GitHub release),
  and the published image was pulled and smoked: `reap_orphans()` inside a container from `:1.5.0`
  collected a forked child (`reaped: 1`, the second `waitpid` raising `ChildProcessError`). The
  production container keeps its 2 zombies until it is recreated on the new image.
* 2026-10-11 — live acceptance on the published artefact. The live container was recreated on the
  pulled `v1.5.0` (`podman pull --policy=always`, then `systemctl --user restart atrust`, 1m32s wall
  of which ~91 s is the user unit's network-online wait before podman creates the container, the same
  behaviour step 11 recorded); the running container reports the release's manifest list
  (`sha256:2b93884a...`, labels `version=1.5.0` / `revision=ab90734`). The stop of the image it
  replaced cost 1.60 s (`signal 15 received` -> `client stop took 1.60s`). The new container's first
  journal line is `reaped 1 orphan(s)` - the startup corpse its own entrypoint left reparented - and
  the recovery took 13 s from container start (`LOGGED_OUT -> ONLINE (tunnel up after the client
  login)`, the client's own login page, no address typing). A fresh `aTrustAgent` corpse appeared
  during that recovery; `podman top` showed it for ~50 s and the next cycle top collected it too
  (`reaped 1 orphan(s)`, 0 defunct after, checked without an exec session). No family sweep was
  forced against the live tunnel - the throwaway sweep plus these two live reaps cover the path.
