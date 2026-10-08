<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Status

Milestones from the plan, with what has actually been verified.

| # | Milestone | State | Evidence |
|---|---|---|---|
| M0 | Protocol capture (no browser needed?) | **done** | Full login flow captured from the portal SPA: `authConfig` (pubKey/pubKeyExp/antiReplayRand/csrfToken), `auth/psw` body and required headers, `reportEnv`, `authCheck`, `onlineInfo`, `checkCode`; the client's cookie store is plain SQLite |
| M1 | `atrustd` HTTP login | **done** | `code=0 密码认证成功` (ticket 73 chars), `authCheck code=0 isOnline=True user=... clientIp=...`, `tid`/`tid.sig` in the session jar |
| M2 | Write `tid`/`tid.sig` into the client profile | **done** | live run: tray stopped, DB row updated (`last_access_utc` moved), values match the session, client back after 4 s |
| M3 | Watchdog + re-login | **done** | `atrustd/probe.py` (tun/routes/proxy CONNECT), `atrustd/state.py`, supervisor loop in `atrustd/__main__.py`; live run: `STARTING -> DEGRADED -> LOGGED_OUT -> ONLINE`, tunnel grace period seen (`tunnel interface is up but routes are not installed yet; waiting up to 30s`) |
| M4 | VNC handover | **done** | live run with a deliberately wrong password: `NEED_VNC` + `captcha.jpg` in `ATRUST_STATE_DIR`, the VNC instructions logged (`journalctl --user -u atrust.service`), and after a human solved the captcha in the desktop: `NEED_VNC -> ONLINE (tunnel up after human action)` |
| M5 | Quadlet + GHCR packaging | **done** | `quadlet/atrust.container` installed to `~/.config/containers/systemd/`, `systemctl --user start atrust.service` -> container `atrust` up (5901/8888/1080 published on loopback), `ONLINE` with 30 routes on `utun7`, proxies answering from the host (`host->8888: 200`, `host->1080: 200`) |
| M6 | Unattended re-login through the client's own window | **done** | `atrustd/uiauto.py`; live run on a profile that carried only the tokens: `reusing tid,tid.sig from the client profile` -> `password auth ok` -> `wrote tid,tid.sig into .../Cookies` -> `submitted the login form of the client window` -> `LOGGED_OUT -> ONLINE (tunnel up after the client login)` (5 s later, 30 routes) |
| M7 | The account's apps, with their launch URLs | **done** | every login publishes them: `1 app(s) from the portal:` / `Example App \| url=https://app.intranet.example/ \| launch=default-browser \| server=tcp app.intranet.example:80 \| group=Default category` and `app list written to /run/atrustd/apps.json`; `atrustd --apps` prints the same from the cache, `--apps --refresh` re-fetches it |

## How the 400 was solved (M1)

`POST /passport/v1/auth/psw` answered `HTTP 400 {"code":10000001,"message":"非法的请求"}` until the
request looked like the SPA's:

* `x-csrf-token` must carry `authConfig.data.security.csrfToken` (POSTs only),
* `x-sdp-rid` = base64(`host:port`), `x-sdp-traceid` = random hex, `x-sdp-env` = base64 device id,
* `Content-Type: application/json;charset=utf-8` on every call,
* password = RSA PKCS#1 v1.5 over `"<password>_<antiReplayRand>"` (hex), i.e. `--padding pkcs1`.

## How the protocol was captured

Run a throwaway container from the base image (client running, `DISPLAY=:1`), attach a Chromium
with Selenium, install a `fetch`/`XMLHttpRequest` hook through
`Page.addScriptToEvaluateOnNewDocument`, log in through the SPA once and read back
`window.__cap`. That yields request bodies, response bodies and (with the XHR
`setRequestHeader` wrapper) the headers the portal insists on. The same run also shows the
local-client detection calls (`POST https://localhost.sangfor.com.cn:54631/v1/detect`).

## Client login: what does NOT work (all verified in a container)

The client (`aTrustAgent` + `aTrustTray`) is the only thing that can bring the tunnel up, and it
does not accept a session that was obtained elsewhere:

| Attempt | Result |
|---|---|
| Browser login through the portal SPA, then its hand-off call | SPA posts `POST https://localhost.sangfor.com.cn:54631/v1/detect` with `{"addr":"<portal>","type":"web","guid":"<authConfig.guid>","lang":...,"sdpTraceId":"<hex>","token":"","data":{}}` - `token` stays empty, and `ip route show dev utun7` remains empty afterwards. The SPA does not hand a session to the client |
| Writing fresh `tid`/`tid.sig` into the client profile + restarting the client | client still reports `logout` (`/v1/service/status`), no routes appear |
| Driving the client's Electron UI over CDP | the tray does **not start at all** when `vpn_ui()` adds `--remote-debugging-port=9222` (checked twice, real and fresh volumes) |
| Calling the client API directly (`/v1/service/status`, `/v1/aUem/statusV2`, `/v1/service/init`) | `HTTP 503` for bare GET/POST. The tray uses an envelope: `{"type":"cs","lang":"...","guid":"...","addr":"...","token":"...","sdpTraceId":"...","data":...}` posted over HTTPS to the agent (see `aTrustTray*.log`: `Agent request https get, url: /v1/aUem/statusV2 post_data: {...}`) |

Conclusion: the client logs in **inside its own UI**. Headless auto-login therefore has to inject
input into that window (X level, e.g. `xdotool`), with a VNC hand-over whenever the portal asks for
the graphical captcha - which is exactly the behaviour requested (VNC on first login / stale
tokens).

## Verification commands

```bash
# M1: portal login only (no client involved)
podman exec -e PYTHONPATH=/opt -e ATRUST_PORTAL_URL=... -e ATRUST_USERNAME=... -e ATRUST_PASSWORD=... \
  atrust python3 -m atrustd --login-probe -v

# M2 + supervisor: token write, client restart, state transitions
podman exec atrust python3 -m atrustd --once -v
podman exec atrust python3 -m atrustd --status
podman exec atrust ip route show dev utun7     # routes == client is online
```

## A/B: the client's own tokens are what suppress the captcha

Same portal, same account, same minute, only the client profile differs:

```bash
# without the client profile (no tid/tid.sig available)
$ podman run --rm --env-file ~/.config/atrust.env --entrypoint python3 <image> -m atrustd --login-probe
WARNING atrustd.portal: portal requires the graphical captcha: 图形验证码已超时，请重试
INFO    atrustd: login: ok=False code=75500000 message=图形验证码已超时，请重试

# with the client profile mounted (tid/tid.sig reused)
$ podman run --rm --env-file ~/.config/atrust.env -v ~/.atrust-data:/root:ro --entrypoint python3 <image> -m atrustd --login-probe
INFO    atrustd.portal: reusing tid,tid.sig from the client profile
INFO    atrustd.portal: password auth ok (next=auth/authCheck)
INFO    atrustd: login: ok=True code=0 message=密码认证成功 ticket=73 chars
INFO    atrustd: session: authCheck code=0 isOnline=True user=... clientIp=...
```

So: tokens present -> silent login; tokens missing/stale -> the portal asks for the captcha and the
engine reports `captcha_required`, which is the state that must end in the VNC hand-over.

## How the client's own window is driven (M6)

`atrustd/uiauto.py`, verified against the real client in a container. The window is an Electron
window (class `aTrustTray`, name `aTrust`, 921x570 at the base image's VNC geometry); its content
re-lays out on resize, so `uiauto` pins it to that size first and everything below is relative to
the window origin.

Measured layout (`x`, `y`, `w`, `h`):

| Element | Position | Notes |
|---|---|---|
| account field | 536, 177, 340x40 | found by its outline: continuous borders, white inside |
| password field | 536, 237, 340x40 | always exactly 60 px below the account field |
| agreement box | 536, 303, 16x16 | ticked = filled with the primary colour, tick mark is white in the middle |
| submit button | 536, 336, 340x40 | grey `#f4f4f4` while the form is empty, primary colour `#1c6eff` once complete |
| (first run) address field | 124, 170, 360x32 | on the "Connection Options" page, submit button at its centre +(-105, +62) |

Page detection uses the *fields*, not the button: the button is greyed out while the form is empty,
and labels are never read (the client's UI language follows the container locale). The button, once
it is coloured, is the anchor for the agreement box and the click target, because the client inserts
error and captcha rows *between* the password field and the button - measured: with the inline
"You still have 8 attempts left" error the account field stays at 177 while the button moves from
336 to ~357, so field-relative offsets alone would miss both the box and the button.

Observed states:

| Window shows | `uiauto` does |
|---|---|
| "Connection Options" | types `scheme://host:port` (no path, no trailing slash) and clicks OK, then continues on the login page |
| password form | ticks the agreement when needed, fills account + password, clicks the button |
| login form with a captcha/QR row | reports the page as manual (no blind clicking), the supervisor hands over to VNC |
| workspace (already online) | nothing - the supervisor decided with the data plane before calling |

The window is mapped before its page is rendered (right after a client start the SPA still fetches
its manifest), so an unknown page is re-read for up to 20 s before the attempt is given up - an
early look used to classify a starting client as "not a login page" and cost the whole cycle.

The portal address is written into the client's own config (`/usr/share/sangfor/.aTrust/var/conf/addr.conf`,
plain text `scheme://host:port`) before the client starts: without it the window opens on "Connection
Options" even when the profile has tokens, with it a freshly created container opens on the login
page.

## The account's apps (launch URLs, M7)

The client's own "App Details" panel is rendered from the portal's resource API, so the same facts
are reachable without a desktop:

```
POST /controller/v1/user/clientResource
     body {"resourceType":{"sdpPolicy":{},"appList":{},"favoriteAppList":{},
                          "featureCenter":{},"uemSpace":{"params":{"action":"login"}}}}
     -> data.appList.data.appInfo[].apps[]
        name           the app name
        accessAddress  the launch URL   ("App Launch Method -> URL", e.g. https://app.intranet.example/)
        openModel.model the launch method ("default-browser", ...)
        addressList[]  the resource, protocol/host/port ("Server Address", e.g. tcp app.intranet.example:80)
```

Notes from getting there:

* the endpoint is a POST and rejects a body without `resourceType` (HTTP 400); the SPA tries five
  shapes and retries with a smaller one when the portal answers `ERR_SERVER_SAFE_CHECK_FAILED`,
* it needs a real *portal session*: the client profile's `tid`/`tid.sig` alone are enough for
  `/passport/v1/user/onlineInfo` but the controller answers
  `code 10000004 ERR_PERMISSION_DENIED: session not found` for them,
* so it is fetched right after the supervisor's own login (the session is there anyway) and by
  `atrustd --apps --refresh`; the result goes to the log and to `apps.json`.

## Supervisor: a restart is not always enough (found live)

Observed on a running service: the client's session was gone while the engine's session was alive
(`web session is alive but the tunnel is not; restarting the client`), the client came back logged
out, and the old code counted attempts until it escalated to `NEED_VNC` - a human was needed for
something the supervisor can do itself. A login rotates the device token and drops the client's
session, so the client's own window is the only way back; the cycle now falls through to the full
pipeline (engine login -> tokens -> client window) whenever a restart did not restore the tunnel,
and only the pipeline's outcome decides about `NEED_VNC`.

## Next

1. **Regression tests for the screen probing.** The geometry `uiauto` depends on (input boxes, the
   primary button, the agreement box) is currently only covered by live runs against a portal - and
   a detector rewrite that looked fine already moved a rectangle by 20 px before a manual check
   caught it. A handful of offline assertions over saved screenshots would pin `classify()`,
   `find_box()`, `find_button()`, `_agreement_checked()` and `apps.summarize()` without touching a
   portal: the login page (empty form, greyed-out button), the same page with the inline
   `N attempts left` error row (everything below the fields shifts down), the connection page, the
   workspace (nothing to do there), and a captcha dialog as a negative case (`classify()` must not
   call it a login page). The screenshots have to be kept as test data, with a license note, since
   they are screenshots of the vendor's client.
2. **Long-run observation.** How often the portal asks for a captcha, and whether a web login ever
   kicks the client's own session (single-session policies). Seen once: after a few engine logins
   from a second container the client's tunnel dropped while its tokens stayed valid - the engine
   logged in again without a captcha and the client's window brought the tunnel back. Note the
   portal's own counter: a failed login answers `The username or password is incorrect. You still
   have N attempts left`, so retries must stay rare - the supervisor tries once per cycle and hands
   over to VNC after `ATRUST_LOGINS_BEFORE_VNC` (2) or as soon as a captcha shows up.
3. **Launching the apps.** The published URLs are plain HTTP(S) to intranet hosts, so the host can
   already open them through the container's proxies; generating one proxy alias (or a small landing
   page) per app would make that a one-click thing. Wanted only if the app list turns out to be used
   interactively.

### Closed - done, no action needed

* **GHCR packaging.** Done: the repository is public (`github.com/YangtseSu/atrust-quadlet`) and
  `.github/workflows/publish.yml` builds `Containerfile` on every push to `main`, publishing
  `ghcr.io/yangtsesu/atrust-quadlet:latest` (plus `:main`, `:<sha>`; a `v*` tag adds the version
  tags and moves `:latest`) for `linux/amd64` and `linux/arm64` - first run `37831907328`, 3m43s.
  The package is public: an anonymous `podman pull` (empty auth file) succeeds, and `uiauto.py`,
  `__main__.py` and `apps.py` in the pulled image hash-match the working tree. `v1.0.0` is tagged
  and released (tag run `37834192138`); `:1.0.0` and `:1.0` share the index digest
  `sha256:e62748eed417e73a347adbfe4964fb9165cb59788943b1e75eef4451eff26c44`.
* **Authoritative status signal.** Decided: the data plane (tunnel interface, routes, an intranet
  probe through the proxy) is the signal. The client's own API (`/v1/service/status` ->
  `data.status`) would need a replay of the tray's envelope (`{"type":"cs","lang":...,"guid":...,
  "addr":...,"token":"","sdpTraceId":...,"data":...}`, `token` observed empty), i.e. an internal
  protocol copied by hand for no extra certainty.
* **App list freshness.** By design: `apps.json` is as old as the last login, and
  `atrustd --apps --refresh` updates it on demand. A login-free source means the same tray envelope
  as above, so it is not worth it.
* **Token rotation.** `tid`/`tid.sig` are rotated by every successful login, so a profile copied to
  another container carries *stale* tokens: the engine then gets `图形验证码已超时` and the run ends
  in the captcha hand-over. Only a profile that has not been reused keeps a silent login.
* **Captcha timing.** The client's captcha dialog expires after roughly a minute (the portal answers
  `Authentication timed out. Please log in again.`), so the VNC hand-over is only useful when the
  human acts immediately; `ATRUST_VNC_WAIT` (900 s) is not the constraint.
* **External captcha solving (deferred, not planned).** The container side was designed and built -
  a request/answer file protocol plus randomized clicking - and verified up to the click loop, then
  reverted: the portal's puzzle expires in under a minute and the round trips through a solver
  outside the container were too slow (the SPA had already replaced the challenge by the time the
  clicks came). Revisit only with a solver that answers in well under 30 s; the design notes and the
  measured numbers are kept outside this repository.
