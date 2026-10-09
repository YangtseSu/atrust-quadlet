<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Roadmap

What is planned, why, and what "done" means. `docs/STATUS.md` stays the record of what has been
built, measured and closed; this file is the plan, ordered by what unblocks the most rather than by
size.

## Now

### 1. Session lifetime: can the portal's forced re-login be avoided?

Measured 2026-10-09 on a clean container (busy loop fixed): the portal expires the client's session
when the tunnel goes quiet - the tray log has `statusEvent|logout` with `"type":"timeout"`,
`"details":"会话已过期，请刷新后重试"`, `"allLoggedOut":true` 21 minutes after a login in which
nothing crossed the tunnel. The supervisor recovers by itself, but 130 s pass before `ONLINE`
returns: ~95 s of that is `ATRUST_WATCH_INTERVAL` detection latency, ~35 s the re-login.

* **Arm A - done, positive.** One request through the container's HTTP proxy to the intranet target
  every 30 s (an external helper, on the host): the session stayed `ONLINE` for **over an hour**
  with zero transitions (`ka_ok=101`, `ka_fail=0`; 11 five-minute heartbeats, container
  `restarts=0`, 30 routes throughout) against a 21-minute baseline. The timeout is therefore not
  absolute - it counts recent tunnel traffic.
* **Arm A' - done, positive: it is the request, not the cadence.** The same helper at the probe's own
  90 s interval held the session for a **full hour** with zero transitions, and the drop that
  followed the helper being stopped came 10.3 minutes later (`statusEvent|logout`, `type=timeout`) -
  while the supervisor's own `CONNECT` probe kept running every 90 s and did not prevent it. So a
  bare `CONNECT` is not counted as activity; a real request is, at any sane cadence.
* **Shipped.** `atrustd/probe.py` sends a real HTTP request (`GET http://<target>/`, absolute-URI
  form, through the proxy) for a plain HTTP target and keeps the `CONNECT` form for `:443`; the
  flows in `tcpAccess.log` show 121 bytes out and 663 bytes back where the old probe moved zero.
  An `https` probe target therefore still proves the data plane but does not keep the session alive.
* **Left to confirm.** A full hour with the shipped image and *nothing else* touching the tunnel
  (the external helper retired), plus the same check after a portal-forced re-login.

### 2. Own aTrust base image, built with podman

Today the image is `hagb/docker-atrust` plus this project's layer. Building the client image
ourselves (from Sangfor's packages, with `podman build`/Buildah) would pin the base, drop the
dependency on a third-party image and make the whole chain podman-native.

Open questions: where the packages come from (deb/rpm, which versions), what the client needs (X11,
`/dev/net/tun`, its userspace netstack, the local API ports), and the licence: the client is not
redistributable, so the deliverable is a build recipe for people who already have the packages, not
a published image.

### 3. CI toolchain: buildx or podman?

Current: `.github/workflows/publish.yml` builds each platform on its own native runner
(`ubuntu-26.04` / `ubuntu-26.04-arm`, no QEMU) with buildx and merges the manifest list - run
`37888025381`, 47 s + 54 s + 19 s against 3m43s for the old single QEMU job. buildx brings the
GitHub Actions cache and signed provenance; the runner images ship Podman 5.7.0 / Buildah 1.42.1 /
Skopeo 1.21, so a podman-native pipeline (per-runner `podman build` + `podman push --digestfile`,
then `podman manifest create/add/push`) is feasible, at the cost of the cache, the provenance and
~40 lines of shell to maintain.

Decide together with item 2: if the image itself is built with podman, the CI should follow.

## Next

4. **Regression tests for the screen probing.** The geometry `uiauto` depends on (input boxes, the
   primary button, the agreement box) is currently only covered by live runs against a portal - and
   a detector rewrite that looked fine already moved a rectangle by 20 px before a manual check
   caught it. A handful of offline assertions over saved screenshots would pin `classify()`,
   `find_box()`, `find_button()`, `_agreement_checked()` and `apps.summarize()` without touching a
   portal: the login page (empty form, greyed-out button), the same page with the inline
   `N attempts left` error row (everything below the fields shifts down), the connection page, the
   workspace (nothing to do there), and a captcha dialog as a negative case (`classify()` must not
   call it a login page). The screenshots have to be kept as test data, with a license note, since
   they are screenshots of the vendor's client.
5. **Launching the apps.** The published URLs are plain HTTP(S) to intranet hosts, so the host can
   already open them through the container's proxies; generating one proxy alias (or a small landing
   page) per app would make that a one-click thing. Wanted only if the app list turns out to be used
   interactively.
6. **Log retention.** Deferred on 2026-10-09: the client rotates only its xtunnel streams (20 MB,
   one previous generation); the tray/agent logs are reset only when the client restarts and a fresh
   per-day file is started every day, so the mounted profile grows by roughly 0.2 GB/day. A cleanup
   script plus a user timer were written and then dropped as more machinery than the benefit
   justifies. Revisit if the profile size becomes a problem - the churn that had the logs grow
   20 MB every two minutes was this project's own busy loop, see `STATUS.md`.

## Later

7. **Long-run observation.** How often the portal asks for a captcha, and whether a web login ever
   kicks the client's own session (single-session policies). Seen once: after a few engine logins
   from a second container the client's tunnel dropped while its tokens stayed valid - the engine
   logged in again without a captcha and the client's window brought the tunnel back. Note the
   portal's own counter: a failed login answers `The username or password is incorrect. You still
   have N attempts left`, so retries must stay rare - the supervisor tries once per cycle and hands
   over to VNC after `ATRUST_LOGINS_BEFORE_VNC` (2) or as soon as a captcha shows up.
