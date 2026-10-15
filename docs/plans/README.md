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
| B — evidence | 03, 10 | the screen geometry is pinned by tests instead of by memory |
| C — waiting on conditions | 05, 06, 07 | each unknown is either closed live or recorded with the exact recipe that would close it |
| D — the client's edges | 08, 09, 11 | a stop costs ≲2 s, the client family leaves by signal rather than by the cgroup's SIGKILL, every session shape the client's helpers ask resolves, and the client's own store carries the portal address into the next start |
| E — the client's own interface | 12, 13, 14, 15, 16, 17, 18, 19 | the supervisor reads the state the client publishes and wakes on its events, a dead session is recovered through the calls the client's own workbench makes, the waits its measurements priced out are cut, the interface can be switched off with its refusals visible, and the same interface is reachable from the host |
| F — the data plane's own witnesses | 20 | the probe finds its own target, and a witness that cannot answer no longer decides alone |
| G — the lessons two ports of this protocol teach | 21, 22, 23, 24, 25 | every accepted lesson of the survey lands with its measurement, or is declined in the survey's record |

| # | Step | Status | Depends on | Exit, in one line |
|---|---|---|---|---|
| 01 | [GNOME notifications for state changes](01-gnome-notifications.md) | ✅ done | — | every transition fires exactly one `notify-send`, captured offline and live |
| 03 | [uiauto screen-probing regression tests](03-uiauto-screen-regression-tests.md) | ✅ done | — | saved screens decide `classify()`/geometry; moving a constant by 20 px fails a test |
| 04 | [NEED_VNC hand-over re-verification](04-need-vnc-reverification.md) | ✅ done | — | the hand-over is seen on the own base and the attempts it cost are recorded |
| 05 | [Second factor (OTP)](05-second-factor-otp.md) | ⛔ blocked | a session on a deployment with a second factor | the offline half is landed (RFC 6238 `--totp`, vectors green, design table, capture recipe); the factor itself always goes to VNC |
| 06 | [arm64 on real hardware](06-arm64-real-hardware.md) | ⛔ blocked | an arm64 host | `ONLINE` with routes on that host, image digest recorded |
| 07 | [Registry orphan-version pruning](07-package-version-pruning.md) | ✅ done | — | a run deletes ≥1 orphan and every tag still resolves afterwards |
| 08 | [Client process family on container stop](08-client-shutdown-sweep.md) | ✅ done | — | a stop returns in ≲2 s and the client family is swept by name |
| 09 | [loginctl shim argument shapes](09-loginctl-session-shapes.md) | ✅ done | — | every invocation shape the client's helpers use resolves |
| 10 | [The real captcha and error-row screens](10-captcha-and-error-row-screens.md) | ✅ done | — | the captcha and error-row screens pinned from a real login, not derived |
| 11 | [The client's own memory of the address](11-client-address-memory.md) | ✅ done | — | a recreated container's client knows the address, so `atrustd` never types it |
| 12 | [The client's own state as a supervisor input](12-client-api-state-read.md) | ✅ done | — | the client's own view sits beside the data plane, and a measurement decides what may act on it |
| 13 | [Event-driven supervision](13-event-driven-supervision.md) | ✅ done | 12 | a client-side transition wakes the cycle in seconds instead of at the next interval |
| 14 | [The API login path](14-api-login-path.md) | ✅ done | — | a dead session recovers through the calls the client's own workbench makes, the window as the fallback |
| 15 | [The client's own SDK as the login path](15-client-sdk-login-path.md) | ✅ done | — | the SDK's ABI is measured and the login either lands on it or is recorded with the reason |
| 16 | [The agent's API reachable from the host](16-agent-api-on-the-host.md) | ⬜ not-started | — | the host reaches the agent's 54631 through the image's own relay, or the step closes with the reason |
| 17 | [Skip the client restart when the client itself says it is logged out](17-skip-restart-on-a-client-side-logout.md) | ✅ done | 12, 14 | the branch the drill priced at 2.2 minutes is skipped on the client's own view, and a logged-out session recovers in 5.4 s (`DEGRADED` to `ONLINE`, measured live) with no restart in the journal |
| 18 | [A cold start pays no wait for a guid the client cannot publish yet](18-a-cold-start-pays-no-guid-wait.md) | ✅ done | — | the ten-second bounds in the ticket path's way in are paid only where a restart is the likely cause: 4.7 s of way in and 18.3 s end to end on a recreation, against 54.4 s before |
| 19 | [The client's local API can be switched off, and its refusals are visible](19-the-client-api-can-be-switched-off-and-seen.md) | ✅ done | — | an undocumented interface can be turned off with one variable and its refusals reach `state.json` and the desktop, and the bump ritual asks for its acceptance |
| 20 | [The probe target is found by the supervisor itself](20-probe-target-discovery.md) | ✅ done | — | an empty `ATRUST_PROBE_TARGET` is discovered from the tunnel's own routes, and a witness that cannot answer no longer decides alone |
| 21 | [The portal's and the agent's answers, classified](21-typed-login-answers.md) | ⛔ blocked | the live half: a portal whose password check is not gated behind the captcha | the supervisor decides on classes (the `graphCheckCodeEnable` field before the message text), and a wrong password cannot burn the account's attempts |
| 22 | [A client bump's own evidence](22-bump-evidence.md) | ✅ done | — | one `--bundle` tarball carries a bump's own evidence (a log tail, not the directory), and the portal's certificate leaves a fingerprint line |
| 23 | [The state directory, and a changed portal](23-state-directory-and-a-changed-portal.md) | ✅ done | — | every file the engine writes is 0600, and a changed `ATRUST_PORTAL_URL` cannot leave the client on the old address (the store loses: the measurement is in the file) |
| 24 | [What the human is told](24-what-the-human-is-told.md) | ✅ done | — | every hand-over names the page the client's own log published (seen live on a local build), and the README carries the host-proxy and device-identity paragraphs |
| 25 | [The engine's own portal session, kept warm](25-session-keepalive.md) | ✅ done | — | the engine's session is a ~10-minute one and no cheap read extends it (three live runs), so the cold path keeps its 31 s and the ticket path its 5.3 s inside the window |
| B02 | [Log retention](B02-log-retention.md) | ⏸ backlog | — | the mounted profile stops growing ~0.2 GB/day |
| B03 | [Long-run observation](B03-long-run-observation.md) | ⏸ backlog | an unattended run | a week of transitions answers captcha frequency and recovery time |
| B04 | [PID 1 reaps what the sweep leaves behind](B04-pid1-reaping.md) | ✅ done | — | no reparented zombie survives a client sweep, so the container's pids limit cannot fill with dead entries |
| B05 | [A clean session end on stop](B05-clean-logout-on-stop.md) | ⏸ backlog | — | the stop still costs ≲2 s and the portal records a logout instead of a terminal that stopped talking |
| B06 | [A start waits ~90 s on `network-online.target`](B06-quadlet-start-delay.md) | ✅ done — 2026-10-15, the implicit wait is off and a `restart` reaches `ONLINE` in 15.8 s | — | a `restart` reaches `ONLINE` without the 90 s the user-side network-online wait costs |
| B07 | [A container started with no usable route comes up dark](B07-no-route-at-start.md) | ✅ done — 2026-10-15, the unit holds a start the host cannot support and starts by itself once a route exists | — | a start on a host whose address appears later reaches `ONLINE` by itself, or the reason it needs a restart |
