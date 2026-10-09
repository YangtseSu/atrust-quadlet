<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Plans

The live plan: one file per step, `NN-<slug>.md` (backlog: `B<NN>-<slug>.md`). The convention is
borrowed from [`YangtseSu/cirrocast`](https://github.com/YangtseSu/cirrocast) `docs/plans/`, which has
carried a project of this shape for months:

* a step is worked top to bottom; every `- ⬜` item in it is one committable unit;
* progress lives **inside the step file** — a `Status:` line (`⬜ not-started`, `🚧 in-progress`,
  `⛔ blocked`, `✅ done`, `⏸ backlog`), the `- ⬜`/`- ✅` markers, and a `## Progress log` that is
  appended to and never rewritten;
* closing a step means its `Status:` line, its `## Progress log` entry and its row in the table below
  change in the same commit — never mark a step done while a `- ⬜` is open;
* the rules themselves are `AGENTS.md`, "Plan discipline";
* work discovered later becomes a new numbered step (the number is the execution order); a step may
  start ahead of its number only when its `Depends on:` line is done, and that deviation is recorded
  in its `## Progress log`;
* a one-off task — a CI fix, a document edit, a bumped constant, a bug fixed on the spot — is **not**
  a step: it is a `docs:`/`chore:`/`fix:` commit and creates no file here;
* **never cite `docs/plans/` from code.** The plan is the process record and is retired when it
  closes; the code carries the reason and the measured number inline.

| Phase | Steps | Milestone |
|---|---|---|
| A — the operator's loop | 01, 04 | the states that need a human reach the desktop, and the hand-over they announce is verified on the own base |
| B — evidence | 02, 03 | the long-run questions are answered by data, and the screen geometry is pinned by tests instead of by memory |
| C — waiting on conditions | 05, 06, 07 | each unknown is either closed live or recorded with the exact recipe that would close it |

| # | Step | Status | Depends on | Exit, in one line |
|---|---|---|---|---|
| 01 | [GNOME notifications for state changes](01-gnome-notifications.md) | ⬜ not-started | — | every transition fires exactly one `notify-send`, captured offline and live |
| 02 | [Long-run observation](02-long-run-observation.md) | ⬜ not-started | — | `atrustd --history` answers captcha frequency and recovery time from a week of real data |
| 03 | [uiauto screen-probing regression tests](03-uiauto-screen-regression-tests.md) | ⬜ not-started | — | saved screens decide `classify()`/geometry; moving a constant by 20 px fails a test |
| 04 | [NEED_VNC hand-over re-verification](04-need-vnc-reverification.md) | ⬜ not-started | a maintenance window | the hand-over is seen on the own base and the attempts it cost are recorded |
| 05 | [Second factor (OTP)](05-second-factor-otp.md) | ⛔ blocked | a portal with OTP enabled | TOTP codes are offline-verified and the portal capture recipe is written |
| 06 | [arm64 on real hardware](06-arm64-real-hardware.md) | ⛔ blocked | an arm64 host | `ONLINE` with routes on that host, image digest recorded |
| 07 | [Registry orphan-version pruning](07-package-version-pruning.md) | ⬜ not-started | the `PACKAGES_TOKEN` secret | a run deletes ≥1 orphan and every tag still resolves afterwards |
| B01 | [App launch page](B01-app-launch-page.md) | ⏸ backlog | 02 | one click opens a published app through the tunnel |
| B02 | [Log retention](B02-log-retention.md) | ⏸ backlog | — | the mounted profile stops growing ~0.2 GB/day |
