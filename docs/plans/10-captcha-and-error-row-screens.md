<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 10 — the real captcha and error-row screens

Status: 🚧 in-progress
Depends on: —
Touches: `tests/data/screens/*.xwd.gz`, `tests/test_uiauto_geometry.py`, `docs/plans/README.md`

## Goal

Step 03 closed with the captcha case *derived* (the login dump with its password row painted out)
and the error-row state unpinned, because producing either for real spends one of the portal's login
attempts. A test account provided for exactly this now allows both, and the login it produces is
kept as that account's session — a profile with tokens, so the next capture is captcha-free.

## Deliverables

- ✅ Both real screens captured on a one-off container of the published image (client 2.5.16.30):
  the captcha after the first submit (a modal, click-in-order dialog — its characters answered
  within the minute the portal allows), the error row after the captcha was answered with the wrong
  password (`The username or password is incorrect. You still have 9 attempts left`). One
  wrong-password attempt spent, as planned.
- ✅ Both masked where the typed account and password pixels were, reviewed as PNGs, committed to
  `tests/data/screens/` and pinned in `tests/test_uiauto_geometry.py` (`classify()` unchanged for
  the error row — the button moves from `BUTTON_DY` 159 to 177 when the row is inserted, and the
  agreement read follows the *found* button, not the no-error fallback; the captcha dialog makes
  `classify()` report `other`, so the hand-over rides on the client's `checkCode` log signal).
- ⬜ The account's login state saved for reuse at `~/.atrust-test-data/root/` (the client profile,
  `tid`/`tid.sig` in its `Cookies`), with the address beside it in
  `~/.atrust-test-data/addr.conf`. The live container's state was copied aside first
  (`~/.atrust-test-data/live-backup/`) and was never touched — still `ONLINE` after the run; the
  one-off container is destroyed.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` green (47 tests; the geometry file counts 11).
- ⬜ `reuse lint` green (69/69 files).

## Progress log

* 2026-10-10 — created when the test account arrived; live `Cookies`/`addr.conf`/`state.json`
  copied to `~/.atrust-test-data/live-backup/` before anything else. The account name and password
  stay out of this repository; one wrong-password attempt is the planned cost of the error row.
* 2026-10-10 — the capture run. Seeding `addr.conf` *before* the client's first start still leaves
  2.5.16.30 on "Connection Options", so the address is driven with `uiauto._set_address`, the
  production path. The first submit (wrong password) raised the captcha dialog instead of an error;
  the error row only appears once the captcha is answered and the portal evaluates the password —
  hence the order: wrong password → captcha → answer → error row; right password → captcha →
  answer → `utun7` up with 30 routes (the live fingerprint). Captcha challenges expire quickly:
  rounds answered too slowly were silently replaced.
