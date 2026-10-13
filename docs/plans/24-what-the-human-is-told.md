<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 24 — What the human is told

Status: ⬜ not-started
Depends on: — (the live half repeats step 04's hand-over drill; the rest is offline)
Touches: `atrustd/uiauto.py`, `atrustd/__main__.py`, `atrustd/vnc.py`,
`tests/test_page_naming.py`, `tests/test_cycle_pacing.py`, `README.md`
(each `- ⬜` item below is one commit)

## Goal

The hand-over says one thing: the client window is not showing the password form. The client's own log
carries the SPA's console - the `checkCode` request `uiauto` already reads for its captcha marker,
`getHistoryAddr`, `final route:login` (`docs/DESIGN.md`) - and the second-factor pages have names of
their own (`totpAuth`, `smsAuth`, `page_auth_trust_terminal`, step 05). `EZ4Connect` classifies the
analogous line stream into typed events precisely so the human is told which prompt it is
([`coreoutputparser.cpp#L5-L81`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/coreoutputparser.cpp#L5-L81)).
The hint can name the page for the same cost it already pays to read the file.

Two README paragraphs are the other half of what a human reads:

* a host-side TUN proxy (Clash and friends) must send the portal host and the intranet ranges
  **direct**: the container's own traffic leaves through the host stack, so a proxy that captures it
  and loops it back into the same tunnel breaks both sides - `EZ4Connect` documents the same rules for
  its own host
  ([`docs/ADVANCED_USAGE.md`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/docs/ADVANCED_USAGE.md)),
  `zju-connect` for its own
  ([`docs/service.md`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/docs/service.md));
* the client's `sdpcguid` is one per image and host (measured 2026-10-11, `docs/DESIGN.md`), so a
  portal that binds a "trust this terminal" grant to it sees every container built from the image on
  that host as the same terminal. The grant's own binding is an inference - no portal here grants one -
  and the paragraph must say so rather than assert it.

And one thing the deployment should be told before it is surprised:
`ATRUST_PROBE_DISCOVER=0` with no `ATRUST_PROBE_TARGET` sends no traffic at all, and a tunnel that
carries only `CONNECT`s expires in ~10.3 minutes against over an hour with real requests (measured
2026-10-09). The combination is a session that expires by configuration, and today neither the README
row nor the daemon says a word about it.

## Deliverables

- ✅ The `NEED_VNC` reason and the state detail carry the last page/route token the client's own log
  published, best-effort beside the captcha marker, and `log_since` re-reads a tail that does not end
  on a newline with a small overlap, so a marker split by the writer is not lost.
- ✅ Tests: the page-token picker over recorded tails (a token, a marker split across the read
  boundary, a tail with neither - which degrades to today's text).
- ✅ `run_daemon` warns once when `ATRUST_PROBE_DISCOVER=0` and no target is configured, naming the
  expiry measurement; the README row for the switch says the same.
- ✅ `README.md`: the host-proxy paragraph beside the Zero Omega one (the portal host and the intranet
  ranges on the host proxy's direct list, and why a capture loops).
- ✅ `README.md`: the device-identity paragraph (the guid measurement, the inference marked as one).
- ⬜ Live: one hand-over whose hint names the page, with the token in the journal - step 04's drill
  repeats it; if a second-factor page is what the portal asks for, the same day step 05 unblocks.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ The live hand-over is recorded in `## Progress log` with the hint's own text.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened by the split of the survey archived at
  `docs/archive/2026-10-13-atrust-reimplementation-lessons.md` (then `B07`): the page-name candidate
  and the two documentation notes are its review's.
* 2026-10-13 — a pointer from step 21: the `NEED_VNC` reason is no longer built in one place.
  `__main__.py` now hands over from two shapes - `_refused_reason()` (a credential the portal
  refused, with `wrong-password`/`rate-limited` stopping the engine's logins; the window never
  submitted there, so there is no page to name) beside the captcha/window reasons this step extends -
  and `vnc.py` is untouched by that (the reason is still just a string into `vnc.hint`). The
  page-name work has to compose with both and keep both shapes in the tests.
