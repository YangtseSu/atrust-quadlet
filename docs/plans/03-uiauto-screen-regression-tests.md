<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 03 — uiauto screen-probing regression tests

Status: ✅ done
Depends on: —
Touches: `tests/test_uiauto_geometry.py` (new), `tests/data/screens/*.xwd.gz` (new), `REUSE.toml`,
`docs/DESIGN.md`

## Goal

`atrustd.uiauto` decides everything from pixels: the account field at `(536, 177)`, the password field
60 px below it, the submit button found by its fill colour, the agreement box 33 px above that button,
and the whole thing only inside a window pinned to `921x570`. Those numbers are today only covered by
live runs against a portal, and a detector rewrite that looked fine already moved a rectangle by 20 px
before a human caught it. This step makes the dumps the authority: a saved screenshot per page, and a
test that fails when a constant, a tolerance or a border/colour rule moves.

## Deliverables

- ✅ Two screens in `tests/data/screens/`, gzipped XWD dumps of the root window (the format
  `uiauto.Screen` already parses) taken on a one-off container of the published image (client
  2.5.16.30, fresh profile, window pinned at 921x570): the connection page (address not set) and the
  login page (the address box driven with the portal address, **no credentials are submitted**). The
  workspace dump was dropped in review — that screen is where an account name, a portal or a node
  address would end up in a public repository — and a captcha dialog cannot be produced without
  spending a portal login attempt; the manual-page case is derived offline instead (next item).
- ✅ `tests/test_uiauto_geometry.py` (stdlib `unittest`, no X server, no container):
  `classify()` returns `connection`/`login` for the dumps; the account, password and button
  rectangles equal the constants in `uiauto`; `_agreement_checked()` is true on the captured page —
  2.5.16.30 renders the box pre-ticked — and flips to false when its pixels are blanked; blanking
  the password row classifies `manual`, the negative case that matters.
- ✅ A mutation check recorded in the `## Progress log`: shifting `USERNAME_BOX` by 20 px in a scratch
  copy makes the suite fail (the property S10 of `cirrocast`'s plan set taught the sibling project).
- ✅ `REUSE.toml` (or an adjacent `.license` file) declares the dumps as screenshots of the vendor's
  client, with the licence note `AGENTS.md`'s private-data rule implies; `reuse lint` stays green.
- ✅ `docs/DESIGN.md`'s window-driving section says the table is what the tests pin.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` runs the new file offline; the rest of the suite stays
  green.
- ✅ The mutation check has been seen to fail and the run is recorded here.
- ✅ `reuse lint` green.

## Progress log

* 2026-10-10 — written as the first step of the plan; nothing captured yet. The dumps must come from
  the *current* client (2.5.16.30), because a dump from an older one would pin the wrong geometry.
* 2026-10-10 — scope reduced in review to the two safe screens (see the deliverables; the workspace
  and captcha dumps are out, with their reasons). Captured on a one-off container of the published
  image: fresh profile, `uiauto.normalize` pinned the window at 921x570 (parked at 95,25), the
  connection page dumped as it renders with no address, then the address box driven with the portal
  address via `uiauto._set_address` (**no credentials, no submit**) until `classify()` reported
  `login`. Both dumps are `xwd -silent -root -nobdrs` of the 1112x620 screen, gzipped (connection
  85 KB, login 124 KB), and both were reviewed as PNGs before entering the tree — no credentials,
  account name, portal or node address in either. Note: with the profile already created, seeding
  `addr.conf` and restarting the client family did not move the window off the connection page (seen
  with an unreachable and with the real address), so the capture drives the box instead, which is
  the production path for that page anyway; a seeded address before the very first start was not
  retested.
* 2026-10-10 — the login page of 2.5.16.30 renders the agreement box pre-ticked and its submit
  button already in the primary colour on an empty form; the test pins that truth (blanking the box
  flips the read to false), and the manual negative case is the login dump with its password row
  blanked.
* 2026-10-10 — mutation check (a scratch copy of HEAD, `USERNAME_BOX` shifted 20 px: `(536, 177)` ->
  `(556, 197)`): `python3 -m unittest discover -s tests` fails, `Ran 43 tests ... FAILED
  (failures=4)` — the account, password, button and manual tests, each showing the found pixel rect
  against the moved expectation (`Rect(x=631, y=202, w=340, h=40) != Rect(x=651, y=222, w=340,
  h=40)`); the other 39 tests, the connection page and the agreement read included, pass as they
  should. The scratch copy is deleted.
* 2026-10-10 — done. Closing runs on this tree: `python3 -m unittest discover -s tests` — 43 tests,
  OK (36 before, 7 new); `reuse lint` — 65/65 files, green. `docs/DESIGN.md`'s window-driving
  section now says the dumps are what the tests pin, and the index marks this step done.
