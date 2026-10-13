<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 23 — The state directory, and a changed portal

Status: ✅ done
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

- ✅ `state.py` writes every file it owns (the atomic temp file included) 0600, with a test that pins
  the mode of `state.json`, the `NEED_VNC` hint and the captcha image.
- ✅ Measure the changed-URL case on a live container: change `ATRUST_PORTAL_URL`, `restart`, and read
  which address the client's window opens on and which portal the tunnel ends on - recorded in
  `## Progress log` either way, because the answer decides the next item.
- ✅ If the store wins: the portal the container was configured for is recorded in `ATRUST_STATE_DIR`,
  and a mismatch at daemon start runs the documented reset (stop the client family, remove
  `database/SdpcHistory`, `SdpcHistory.crc` and `addr.conf`) before the client's own start loop
  brings it back, so the seeded address is the one the window uses; `docs/DESIGN.md` and the
  quick start carry the rule. — Declined: **the store does not win** (see `## Progress log`), so
  there is no mismatch to detect and nothing to reset.
- ✅ `README.md`: the changed-portal note (what a `restart` does and does not reset) beside the
  configuration table.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` (157) and `reuse lint` (102/102) stay green; the mode
  test fails on the old writer (checked with the change stashed: three of its four tests fail).
- ✅ `ls -l ~/.atrust-data/run` on the live mount shows 0600 for every file the engine writes - the
  four files that mount holds (`state.json`, `apps.json`, `device-id`, the step-22 bundle). The
  hand-over pair has no file there because the deployment is healthy; its writer is the same one and
  `tests/test_state.py` pins it.
- ✅ The changed-URL case is answered by a live measurement (the store loses: `## Progress log`), and
  the deployment's own restart afterwards shows the new-then-real address and `LOGGED_OUT -> ONLINE`.
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened by the split of the survey archived at
  `docs/archive/2026-10-13-atrust-reimplementation-lessons.md` (then `B07`): the file-mode
  measurement is its review's, the portal-change candidate is its EZ4Connect invalidation lesson.
* 2026-10-13 — the mode half landed first, one commit (`feat(atrustd): the state directory holds no
  world-readable file`): `state.write_private()` is now the one writer - `os.open` at 0600, whose
  mode applies only to a file it creates itself, plus an `fchmod` beside it, so a file an older
  version left 0644 comes back private and the atomic temp file is never readable - and `StateFile`
  (`state.json`, the `NEED_VNC` hint, the captcha image) and `apps.save` both go through it
  (`atrustd/apps.py` is one path beyond the `Touches:` line: `apps.json` is written there, and it sits
  in the same mounted directory).
  `tests/test_state.py` pins the modes under the umask the old writer was measured under (`022`):
  every file in the directory, the temp file at the moment it is renamed, and a readable file being
  corrected. All three fail with the change stashed, i.e. on the old writer.
* 2026-10-13 — the changed-URL measurement (item 2). The ordering was the unit's own:
  `systemctl --user stop atrust` first (its `ExecStop=podman rm -v -f` removes the container), then
  `podman run` with the unit's own flags, the deployment's own mounts (`~/.atrust-data:/root` and
  `~/.atrust-data/run:/run/atrustd`) and the dev image built from this tree, `ATRUST_PORTAL_URL`
  overridden through `-e` so the deployment's env file was never edited; the deployment was started
  again on the same image at the end. **The store does not win**, and the reason is structural:
  * where the store lives: `/usr/share/sangfor/.aTrust` is the container's own layer (device 71,
    inode 31427510) while `/root` is the host mount (device 51, inode 27717281), so
    `database/SdpcHistory` cannot survive the container that the unit's stop removes.
  * a container created 23:01:37 loaded `[SdpcHistory] with 0 key-values` (its own stdout) while the
    container it replaced had written the portal address into its store at 22:48; the address it
    used was the one `run_daemon` seeded into `addr.conf` before the client started, and it reached
    `LOGGED_OUT -> ONLINE (tunnel up after the client login)` in 18 s.
  * with the URL changed to a second address nothing answers (the reserved documentation range): the
    engine read it back from its own environment, `addr.conf` was seeded with it before the client
    started, the fresh container's store loaded empty again (`[queryHistory] end, the result is []`)
    and then carried the *new* address (`[addHistoryAddr]` and the window's own `defaultSdpcAddr`),
    and the tunnel stayed down - `DEGRADED -> LOGGED_OUT (the client has to log in again)` with `the
    fresh portal login did not land: ... failed`. Nothing of the old portal survived.
  * the reverse: the deployment restarted on its own URL loaded its store with 0 key-values again,
    took the real address from `addr.conf`, and reached `LOGGED_OUT -> ONLINE` 13 s later.
* 2026-10-13 — item 3 declined, from that measurement and one more: a changed URL cannot leave the
  client on the old address while the engine talks to the new one, because the engine's URL is fixed
  at container creation and the store is in the created container's own layer. A start that keeps the
  container (`podman restart atrust` by hand) keeps both - measured on a throwaway of the same image:
  a marker file written into the layer survived the restart and `printenv ATRUST_PORTAL_URL` was
  still the creation-time value - so the mismatch this item guards against has no path to exist, and
  neither the record in `ATRUST_STATE_DIR` nor the reset code is added.
* 2026-10-13 — item 4: the README's changed-portal note beside the configuration table (a
  `systemctl --user restart atrust` is the whole procedure; what the restart keeps - the mounted
  profile - and what `podman restart` would keep against it) and DESIGN.md's two paragraphs: the
  state directory's 0600 rule with the measured before, and the store section's changed-URL
  measurement above.
* 2026-10-13 — live, the other half of item 1, on the deployment whose mounts the measurement above
  had already used: `ls -l ~/.atrust-data/run` shows `state.json` 0600, `apps.json` 0600, `device-id`
  0600 and the step-22 bundle 0600, where the same directory held `state.json` (380 bytes) and
  `apps.json` (387 bytes) at 0644 that evening. The hand-over pair (`NEED_VNC` + the captcha image)
  has no file on this mount because the deployment is healthy and writing a fake hint into the live
  mount would ring the notifier; their writer is the same one, pinned by `tests/test_state.py`.
  The deployment now runs the image built from this tree (retagged to the unit's own image name; the
  published tags still resolve to the published image) - the fix's whole point is the live mount, so
  it is the live mount that has to write it.
