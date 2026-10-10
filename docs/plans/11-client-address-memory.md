<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 11 — The client's own memory of the address

Status: 🚧 in-progress
Depends on: —
Touches: `base/Containerfile`, `base/README.md`, `docs/DESIGN.md`, `docs/plans/README.md`
(each `- ⬜` item below is one commit)

## Goal

Except for the first login of a freshly created container, the client should open on the account and
password page by itself: the portal address and the account already filled (the account already is -
the client keeps the last user name), the password the only thing left, which `atrustd` types and
submits. Today every client start lands on "Connection Options" with an empty address box and
`atrustd` types the address in, because the client's saved-address store never loads: the bundled
`resources/bin/libmmkv.so` declares an executable stack (`PT_GNU_STACK` RWE) and glibc >= 2.41
refuses to `dlopen` that - `docs/DESIGN.md`, "The client's own store".

The AUR package `sangfor-atrust-bin` carries three fixes for three independent defects, all three
needed on a normal host; in this image only the third applies, measured 2026-10-10 in a throwaway
container of the published image: the base has no system `libcurl.so.4` and no `libproxy`, and
`aTrustAgent` already maps the bundled `resources/bin/libcurl.so` through the `LD_LIBRARY_PATH`
`vpn-config.sh` sets (no daemon crash to fix); the system `libsqlite3.so.0` is mapped by nothing but
`atrustd`'s own Python, never by a client process, so the tray's SQLCipher symbol collision cannot
happen either. Clearing the one flag at runtime inside that container was enough: `[addHistory] end`
in the client's log, `database/SdpcHistory` written, `getHistoryAddr` returns the address seeded into
`addr.conf`, and the connection page's address box rendered it (dark text where the placeholder had
been) - the seeded address reaches the client and a human in VNC finds the field filled.

## Deliverables

- ✅ `base/Containerfile` clears the flag in the client-image build (`patchelf --clear-execstack` on
  the client's `resources/bin/libmmkv.so`, with the tool installed for the step and removed again, and
  the assertion that the object no longer requests an executable stack), and `base/README.md` says
  what the patch is and why the image carries it. The recipe hash moves, so `base/ref.sh` derives a
  new client-image tag and the pipeline rebuilds and republishes it.
- ✅ The changed image is verified: offline first (throwaway container, fresh profile, `addr.conf`
  seeded: the store writes `SdpcHistory` and the window renders the address), then live - one
  logout→login cycle with the live container running the changed image, the way the repository
  verifies everything that changes behaviour. The live cycle ended on the login page without
  `uiauto` touching the address (see the log entries below).
- ✅ What the live cycle shows is recorded here: the client advances to the login page on its own -
  `defaultSdpcAddr: <portal>`, the router guard's `auto connect on enter router guard`, `final
  route:login` - so `atrustd` never touches the address page and neither contingency below was
  needed. The store alone keeps the address across a client-family restart (measured in a throwaway
  container with `addr.conf` removed), so every start after the container's first reads it from there.
- ✅ The fallback from the review was not needed: the client reaches the login page by itself
  (recorded above), so `atrustd` keeps no record of the last address/account and `uiauto` sees no
  "Connection Options" page at all on this path. Its two variants stay recorded here in case the
  client's behaviour changes: the smallest `uiauto` change (a bounded wait for the client's own
  connection detect before anything is typed, never a blind "click OK without typing") and the
  second one the review supplied - deleting the address from the client's own config to force the
  entry flow, measured and written into `docs/DESIGN.md` (stop the family, remove
  `database/SdpcHistory` + `.crc` and `var/conf/addr.conf`).
- ✅ `docs/DESIGN.md`'s "The client's own store" section flips from "Not applied to the image" to
  what the image now does, with the live measurement.
- ⬜ The published image carries the change: `main` is pushed, the pipeline rebuilds and publishes the
  client image under the new recipe tag (`2.5.16.30-c08d5363-amd64`) and the app image on top of it,
  and the live container is switched off the temporary local image onto the published `:latest`, with
  one recovery cycle observed there (`[page=login]`, no address typing, `ONLINE`).

## Exit criteria

- ⬜ The live container runs the changed image through one recovery cycle: `atrustd` does not drive
  the address page (or the recorded reason why not, plus the fallback that was taken), the tunnel is
  `ONLINE` afterwards, and the journal shows no new client crash.
- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-11 — step written after the throwaway-container measurement above. The review that asked
  for it recorded the trade-off: the client remembering the address must not make a changed
  `ATRUST_PORTAL_URL` stale, and it cannot here - the store lives in the container layer
  (`/usr/share/sangfor/.aTrust/database/SdpcHistory`, outside the mounted profile), a recreated
  container starts from the image's empty copy, and `run_daemon` seeds `addr.conf` from the
  environment at every start, which the now-working import path turns into the next client start's
  address.
* 2026-10-11 — the build patch is in: `base/Containerfile` installs patchelf for the client-install
  layer, clears the flag, asserts `execstack: -` and purges the tool again; `base/README.md` carries
  what the build changes in the vendor package. The new recipe tag is
  `2.5.16.30-c08d5363-amd64`. The local base build (`localhost/atrust-base:latest`) and the app image
  on top of it (`localhost/atrust-quadlet:dev`) both succeeded.
* 2026-10-11 — offline verification of the built image, throwaway container with a fresh profile
  (`--network=none`): the library's `PT_GNU_STACK` reads `0x6` (no execute bit) and the image carries
  no `patchelf`; with `addr.conf` seeded the client imports it (`getHistoryAddr` returns it, no
  `libmmkv` error in its log) and the connection page renders it into the address box (262 dark
  pixels inside the box against 20 before the fix, where only the placeholder was). With `addr.conf`
  deleted again the store alone serves the address across a client-family restart - the second start
  of a container needs no seed and no typing.
* 2026-10-11 — live acceptance on the changed image (a `[Container] Image=` drop-in for
  `localhost/atrust-quadlet:dev`, one container recreation at 00:35 CST). The client's store loads and
  imports the seed (`loaded [SdpcHistory] with 1 key-values`, `getHistoryAddr` returns the portal),
  `WebDirManager` builds the window with the address in its URL (`defaultSdpcAddr: <portal>`), the
  SPA's router guard runs `auto connect on enter router guard` and ends on `final route:login`, and
  the supervisor's cycle reads `client window: submitted: credentials submitted [page=login]` - **no
  `the client asks for the portal address` line at all**, i.e. `atrustd` never touched the address
  page. `LOGGED_OUT -> ONLINE (tunnel up after the client login)` followed 5 s later. Note for the
  acceptance record: the recreation itself waited ~90 s in `podman-user-wait-network-online.service`
  before the container was created, which is why the first log line is 00:35 rather than 00:34 - the
  unit's own behaviour, not the image's.
* 2026-10-11 — the second fallback from the review (force the address page by deleting the address
  from the client's config) was measured in a throwaway container of the changed image. It needs both
  files and a stopped client family: deleting only `database/SdpcHistory` (+ `.crc`) is undone by the
  next start's import of `var/conf/addr.conf`, and deleting either under a running client is undone by
  its flush. With the family stopped and both removed, the store loads with 0 key-values,
  `getHistoryAddr` returns empty and `defaultSdpcAddr` is `undefined` - the client asks for the
  address again. Recorded in `docs/DESIGN.md` as the recipe for a memory that has to be dropped; a
  recreated container needs none of it.
* 2026-10-11 — the second live observation does not need to come from the portal: the tunnel stayed up
  for the 40 minutes it was watched (which is the point of the supervisor), and a token rotation alone
  does not force a cycle - `atrustd` re-logs in only when the data plane is down, so `--login-probe`
  left the supervisor `ONLINE` with `state.since` unchanged. The "start after the first" case was
  therefore measured in a throwaway container, where it is deterministic: with `addr.conf` removed,
  the store alone serves the address to the next client-family start (`getHistoryAddr` returns it and
  `WebDirManager` builds the window with it), and `initHistoryAddr` imports `addr.conf` only into an
  empty store. One note for that recipe: the client rewrites `addr.conf` itself once it has an
  address, so the file is not a marker of a cleared state.
