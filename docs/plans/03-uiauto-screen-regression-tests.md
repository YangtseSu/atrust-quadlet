<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 03 — uiauto screen-probing regression tests

Status: ⬜ not-started
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

- ⬜ Screens in `tests/data/screens/`, gzipped XWD dumps of the root window (the format
  `uiauto.Screen` already parses; gzip keeps a 921x570 dump at a few hundred KB): the connection page
  (fresh profile, portal address not set), the login page (fresh profile, address seeded so the client
  renders the password form — **no credentials are submitted**), the workspace of an `ONLINE`
  container, and a captcha dialog if one can be produced without spending a portal login attempt.
- ⬜ `tests/test_uiauto_geometry.py` (stdlib `unittest`, no X server, no container):
  `classify()` returns `connection`/`login`/`other` for its dump; the account, password and button
  rectangles equal the constants in `uiauto`; `_agreement_checked()` is false on the untouched page;
  the captcha dump is **not** classified `login` (the negative case that matters).
- ⬜ A mutation check recorded in the `## Progress log`: shifting `USERNAME_BOX` by 20 px in a scratch
  copy makes the suite fail (the property S10 of `cirrocast`'s plan set taught the sibling project).
- ⬜ `REUSE.toml` (or an adjacent `.license` file) declares the dumps as screenshots of the vendor's
  client, with the licence note `AGENTS.md`'s private-data rule implies; `reuse lint` stays green.
- ⬜ `docs/DESIGN.md`'s window-driving section says the table is what the tests pin.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` runs the new file offline; the existing 11 tests stay green.
- ⬜ The mutation check has been seen to fail and the run is recorded here.
- ⬜ `reuse lint` green.

## Progress log

* 2026-10-10 — written as the first step of the plan; nothing captured yet. The dumps must come from
  the *current* client (2.5.16.30), because a dump from an older one would pin the wrong geometry.
