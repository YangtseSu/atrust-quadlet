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

Measured 2026-10-09 on a clean container (busy loop fixed, no external traffic): the portal expires
the client's session ~21 minutes after a login and logs everything out at once - the tray log has
`statusEvent|logout` with `"type":"timeout"`, `"details":"会话已过期，请刷新后重试"`,
`"allLoggedOut":true` (05:17:43Z, 21 min after the 04:56:45Z login). The supervisor recovers by
itself, but 130 s pass before `ONLINE` returns: ~95 s of that is `ATRUST_WATCH_INTERVAL` detection
latency, ~35 s the re-login (tokens + the client's own window).

* **Arm A (running).** External keepalive: one request through the container's HTTP proxy to the
  intranet target every 30 s, on top of the supervisor's own 90 s probe. If the drop interval stays
  at ~21 min, the portal's timeout is absolute and the data plane is not what it counts.
* **Arm B (needs a code change).** Portal keepalive: touch the portal once per cycle on the ONLINE
  path (`is_logged_in()`, the same `onlineInfo` call) instead of only on failures, then re-measure.
  Worth it only if the timeout turns out to be idle-based; the client's own heartbeats did not
  prevent the expiry, so this is a bet.
* **If the timeout is absolute.** Make the forced re-login a planned one: log in again before the
  deadline (a ~35 s interruption) instead of waiting for the unplanned 130 s one, and lower
  `ATRUST_WATCH_INTERVAL` to shrink the detection latency. Both need the interval to be predictable
  first, which is what the arms measure.

Done when: two consecutive drop intervals per arm, each with the client-log evidence, and the
chosen behaviour (keepalive, planned re-login, or nothing) written down here.

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
