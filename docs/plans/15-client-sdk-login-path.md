<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 15 — The client's own SDK as the login path

Status: ⬜ not-started
Depends on: — (a throwaway container and the account's credentials, both in hand)
Touches: `docs/DESIGN.md`, `docs/plans/README.md`, and - only if the measurement lands -
`atrustd/` (`clientapi.py` or a new module), `atrustd/__main__.py`, `tests/`
(each `- ⬜` item below is one commit)

## Goal

The image ships the vendor's own SDK: `/usr/share/sangfor/aTrust/resources/bin/libaTrustSDK.so`
exports the documented C API - `atrust_initial`, `atrust_sync_login_by_pwd`,
`atrust_sync_login_by_totp`, `atrust_sync_login_by_sms`, `atrust_sync_login_by_radius`,
`atrust_sync_query_status`, `atrust_regist_listener`, `atrust_clear_listener`, `atrust_sync_logout` -
and links only against libraries the image already has (`ldd` measured: its own bundled
`libssl.so.1.1`/`libcrypto.so.1.1`/`libboost_filesystem.so.1.70.0`, the system libc). The vendor
documents it (CSSDK 6.1/6.2/6.4/6.5/6.6), including the status struct and the event enum.

If a `ctypes` binding works, the *login* - today the one thing that needs the client's own window and
X11 driving (`uiauto`) plus the portal half of `portal.py` - becomes a library call that the client
itself performs, and the second factors this project hands to VNC get entry points of their own
(`_by_totp`, `_by_sms`, `_by_radius`). That is a large enough change that it is measured first and
landed only if the measurement is clean.

## Deliverables

- ⬜ The read-only measurement, in a throwaway container: load the library with `ctypes`, build the
  `atrust_status` struct from the documented layout, call `atrust_initial(<portal>)` and
  `atrust_sync_query_status()` and compare the answer with `/v1/service/status` (the HTTP route is
  already measured, so it is the reference). Recorded here: the struct's field sizes, the enum
  values seen, and whether the SDK agrees with the HTTP view in the same state.
- ⬜ The login measurement, in a throwaway container with the account: `atrust_sync_login_by_pwd`
  with `user@domain` (the domain rule is in CSSDK 6.2.1) and the account's password, `force = 0`.
  Recorded either way: did the tunnel come up with no window and no X11 (routes on `utun7`, no
  `uiauto` run), what did `nextAuth`/`data` say, how long it took, and what it cost (the attempt
  count the portal reports, the way step 04 recorded it). If the portal demands a captcha or a
  second factor, what the SDK returns *is* the finding - it decides whether the VNC hand-over can be
  narrowed to those cases.
- ⬜ The decision, in this file: land it (and with what fallback - `uiauto` stays until the SDK path
  has survived a client bump) or leave it, with the reason the measurement gives.
- ⬜ If it lands: the login path in `atrustd`, `atrust_sync_logout` considered for the stop path
  (a clean session end instead of the process sweep), the tests, and the live acceptance.
- ⬜ `docs/DESIGN.md`: "How the client logs in" gains the SDK path or the recorded reason it is not
  one.

## Exit criteria

- ⬜ Both measurements are in this file with their numbers, and the decision follows from them.
- ⬜ If code lands: `python3 -m unittest discover -s tests` and `reuse lint` green, plus a live
  recovery cycle that shows which path logged in.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-11 — written after the reference doc landed. The read-only half is deliberately first: it
  needs no credentials and no session change, and if the ABI cannot be spoken from `ctypes` at all,
  that is known before the account is touched. Note that this is the *vendor-documented* path, unlike
  the HTTP routes: if the two disagree some day, the SDK is the one that is supposed to keep working.
