<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Archive

Records that a later decision replaced, kept because they are how the current constraints were
arrived at. **These are records, not instructions.**

| File | Holds |
|---|---|
| [2026-10-10-STATUS.md](2026-10-10-STATUS.md) | the milestone record of the first two releases: every verified behaviour with its measurements (protocol capture, `uiauto` geometry, the session-lifetime experiments, the base-image acceptance) and the closed decisions |
| [2026-10-10-ROADMAP.md](2026-10-10-ROADMAP.md) | the item-numbered roadmap those milestones were built from, including the session-lifetime measurements in full |
| [2026-10-10-B01-app-launch-page.md](2026-10-10-B01-app-launch-page.md) | the app launch page, retired before it was started: the apps are opened from a bookmark through the browser's per-URL proxy rule, so a page serving them would only replace the bookmark, and a second host-facing UI is what [`../ROADMAP.md`](../ROADMAP.md) rules out |

The first two were retired on 2026-10-10 in favour of [`../plans/`](../plans/) (one file per step,
progress in the file) and the direction in [`../ROADMAP.md`](../ROADMAP.md). A record written from now
on lives in the `## Progress log` of the step that produced it; the one thing that still lands here is
a step the plan drops - it moves in with its `⏹ retired` status and the reason appended to its own log.
