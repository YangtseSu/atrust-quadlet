<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 23 — The state directory, and a changed portal

Status: ⬜ not-started
Depends on: — (the changed-URL measurement needs one live container and a restart; the rest is
offline)
Touches: `atrustd/state.py`, `atrustd/__main__.py`, `atrustd/config.py`, `atrustd/tokens.py`,
`tests/test_state.py` (new), `README.md`, `docs/DESIGN.md`
(each `- ⬜` item below is one commit)

## Goal

Two of the container's own marks are wrong or absent.

**The state directory is world-readable.** `device-id` is written 0600 (`portal.py::_keep_device_id`)
while `state.json` - which carries the account name and the client's own view of the session - and
`apps.json` and the `NEED_VNC` hint are 0644, on the host mount: every local user of the host reads
them (measured 2026-10-13, `ls -l ~/.atrust-data/run`). The repository's own rule is that a
deployment's private data does not leak; the engine writes these files, so it is the engine's to fix.

**A changed `ATRUST_PORTAL_URL` has no path of its own.** A recreated container starts clean, but a
plain `systemctl --user restart atrust` with a changed URL keeps the client's `SdpcHistory` store -
it lives in the container layer, outside the mounted profile - on the *old* address while the engine
talks to the new portal. Which side the client's window uses is unmeasured; `EZ4Connect` answers the
same question by clearing its stored client data whenever server, port, protocol, auth type or login
URL changes
([`mainwindow.cpp#L826-L838`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/presentation/main/mainwindow.cpp#L826-L838)),
and this project's own recipe for that reset is already written down (`docs/DESIGN.md`, "The client's
own store, and what it takes to fix it") - it is just manual, and nothing records which portal the
container is configured for.

## Deliverables

- ⬜ `state.py` writes every file it owns (the atomic temp file included) 0600, with a test that pins
  the mode of `state.json`, the `NEED_VNC` hint and the captcha image.
- ⬜ Measure the changed-URL case on a live container: change `ATRUST_PORTAL_URL`, `restart`, and read
  which address the client's window opens on and which portal the tunnel ends on - recorded in
  `## Progress log` either way, because the answer decides the next item.
- ⬜ If the store wins: the portal the container was configured for is recorded in `ATRUST_STATE_DIR`,
  and a mismatch at daemon start runs the documented reset (stop the client family, remove
  `database/SdpcHistory`, `SdpcHistory.crc` and `addr.conf`) before the client's own start loop
  brings it back, so the seeded address is the one the window uses; `docs/DESIGN.md` and the
  quick start carry the rule.
- ⬜ `README.md`: the changed-portal note (what a `restart` does and does not reset) beside the
  configuration table.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green; the mode test fails on the
  old writer.
- ⬜ `ls -l ~/.atrust-data/run` on the live mount shows 0600 for every file the engine writes.
- ⬜ The changed-URL case is answered by a live measurement (and, if the store won, a second one
  showing the new address in the window and `LOGGED_OUT -> ONLINE`).
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened by the split of the survey archived at
  `docs/archive/2026-10-13-atrust-reimplementation-lessons.md` (then `B07`): the file-mode
  measurement is its review's, the portal-change candidate is its EZ4Connect invalidation lesson.
