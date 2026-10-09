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
* **Left to confirm - done 2026-10-09.** With the shipped image (rev `a8d057ea`), the external helper
  retired and nothing else touching the tunnel, the session stayed `ONLINE` for a full hour
  (60.8 min and counting, 11 five-minute heartbeats, zero transitions, `restarts=0`, `app_sockets=0`)
  and the state detail shows the far side answering: `probe <target>:80 ok (HTTP/1.1 200)`. Item
  closed; a portal-forced re-login is still handled the same way as before (~2 min, automatic).

### 2. Own aTrust base image, built with podman

**Done (branch `feat/own-atrust-base`, 2026-10-09).** `base/` builds the client image from Sangfor's
own package on Debian 13. The main `Containerfile` consumes it through `--build-arg BASE_IMAGE`, and
the pipeline publishes the client image itself, content-addressed, as a tag of the same package:

```
ghcr.io/yangtsesu/atrust-quadlet:base-<client version>-<recipe hash8>-<arch>
```

`base/ref.sh` derives that tag (client version + a hash over `Containerfile`/`vendor/`/`overlay/`, so
both architectures agree), the `base` job skips the build when the tag already exists, and the `image`
job builds on top of the published tag. An app-only change therefore rebuilds one layer instead of
the client install. The base is a tag, not a second package, because GHCR gives `GITHUB_TOKEN` write
access only to packages linked to the repository. What that bought, in order:

* the client version is pinned in this repository (2.5.16.30, sha256 in `base/build-args/`), so a
  client bump is an explicit commit with a live acceptance instead of something an upstream moving
  `:latest` does to us;
* no third-party image builds and runs as root with NET_ADMIN behind a floating tag;
* the inherited `VOLUME /usr/share/sangfor/EasyConnect/resources/logs` is gone - it left an
  anonymous volume on every container run (31 had accumulated here);
* the apt set is derived from the client's own `DT_NEEDED` rather than copied: `libssl1.1`,
  `libnss3`, noVNC/websockify, the self-built websocket tinyproxy, `busybox`, `chromium` and the
  rest of the EasyConnect list are gone. `dante-server` no longer exists in Debian 13, so the SOCKS5
  proxy is `microsocks` (TCP `CONNECT`; nothing here ever used `UDP ASSOCIATE`).

The live acceptance passed on the real account on 2026-10-09 (`docs/STATUS.md`, M8): the Quadlet
service running the new image reached `ONLINE` 18 s after start through the whole pipeline - engine
login reusing the profile's tokens, `tid`/`tid.sig` written into the client's store, the client's
own window driven by `uiauto`, the tunnel up - with 30 routes on `utun7`, the HTTP and SOCKS5
proxies answering from the host through the tunnel, and the app list published. Left open, in
order:

1. **`linux/arm64` base build.** Same recipe with `base/build-args/arm64.args`; the pipeline builds
   it on the arm runner, nobody has looked at the result yet.
2. **The first CI run** of the podman pipeline (item 3).
3. **The `NEED_VNC` hand-over** was not re-run (a deliberately wrong password costs the portal's
   login attempts); it is unaffected by the base apart from the VNC server, so re-check it the next
   time the portal asks for a captcha by itself.

### 3. CI toolchain: buildx or podman?

**Decided: podman.** `publish.yml` builds the client image only when its content-addressed tag is
missing and then the repository image with `podman build`, pushes each platform by digest under a
per-platform tag (`:linux-amd64`, `:linux-arm64` - kept for debugging) and assembles the manifest
list with `podman manifest`. The buildx cache, its `name=...` digest quirk and the docker daemon
dependence are gone. The client install (the 200 MB download and `dpkg -i`) now happens only when
`base/` changes; an app-only build pulls the published client image instead.

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
