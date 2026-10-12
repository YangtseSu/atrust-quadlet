<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 15 — The client's own SDK as the login path

Status: ✅ done
Depends on: — (a throwaway container and the account's credentials, both in hand)
Touches: `docs/DESIGN.md`, `docs/CLIENT-LOCAL-API.md`, `docs/plans/README.md`, and - only if the
measurement lands - `atrustd/` (`clientapi.py` or a new module), `atrustd/__main__.py`, `tests/`
(each `- ⬜` item below is one commit)

## Goal

The image ships the vendor's own SDK: `/usr/share/sangfor/aTrust/resources/bin/libaTrustSDK.so`
exports the documented C API - `atrust_initial`, `atrust_sync_login_by_pwd`,
`atrust_sync_login_by_totp`, `atrust_sync_login_by_sms`, `atrust_sync_login_by_radius`,
`atrust_sync_query_status`, `atrust_regist_listener`, `atrust_clear_listener`, `atrust_sync_logout` -
and links only against libraries the image already has (`ldd` measured: its own bundled
`libssl.so.1.1`/`libcrypto.so.1.1`/`libboost_filesystem.so.1.70.0`, the system libc). The vendor
documents it (CSSDK 6.1/6.2/6.4/6.5/6.6), including the status struct and the event enum.

If a `ctypes` binding works, the *login* - today the one thing that needs the client's own window and
X11 driving (`uiauto`) plus the portal half of `portal.py` - becomes a library call that the client
itself performs, and the second factors this project hands to VNC get entry points of their own
(`_by_totp`, `_by_sms`, `_by_radius`). That is a large enough change that it is measured first and
landed only if the measurement is clean.

## Deliverables

- ✅ The read-only measurement, in a throwaway container: load the library with `ctypes`, build the
  `atrust_status` struct from the documented layout, call `atrust_initial(<portal>)` and
  `atrust_sync_query_status()` and compare the answer with `/v1/service/status` (the HTTP route is
  already measured, so it is the reference). Recorded here: the struct's field sizes, the enum
  values seen, and whether the SDK agrees with the HTTP view in the same state.
- ✅ The login measurement, in a throwaway container with the account: `atrust_sync_login_by_pwd`
  with `user@domain` (the domain rule is in CSSDK 6.2.1) and the account's password, `force = 0`.
  Recorded either way: did the tunnel come up with no window and no X11 (routes on `utun7`, no
  `uiauto` run), what did `nextAuth`/`data` say, how long it took, and what it cost (the attempt
  count the portal reports, the way step 04 recorded it). If the portal demands a captcha or a
  second factor, what the SDK returns *is* the finding - it decides whether the VNC hand-over can be
  narrowed to those cases.
- ✅ The decision, in this file: land it (and with what fallback - `uiauto` stays until the SDK path
  has survived a client bump) or leave it, with the reason the measurement gives.
- ✅ `docs/DESIGN.md`: "How the client logs in" gains the SDK path or the recorded reason it is not
  one. (`docs/CLIENT-LOCAL-API.md`'s "the SDK login path" item 4 was updated in the same pass - it
  still said "not attempted".)
- (The conditional item above this one was removed on 2026-10-12: the decision left the SDK login
  unlanded, so there is no `atrustd` code to add. See the decision section.)

## The read-only measurement (2026-10-12)

Throwaway container from `localhost/atrust-base:latest` (client 2.5.16.30, its own restart loop
running, no engine, no credentials), python3 3.13 installed into the container after the fact
because the base image has none. Library:
`/usr/share/sangfor/aTrust/resources/bin/libaTrustSDK.so`, sha256
`a4cb1e0f94845131a24d7ed4e440a10e54a0280cb7da844e26caf6a2de4a8b66`, `atrust_get_cssdk_version`
("2.0.1.0" - it takes a `char *` buffer, not a return value, and a wrong binding segfaults).
The struct layout below is from the library's own `CssdkClient::QueryStatus`
(`_ZN7sangfor5cssdk11CssdkClient11QueryStatusEPP13atrust_status`) disassembly and read back from
the live call.

| field | offset | size | JSON path it is filled from (`ATrustStatus::parse`) |
|---|---|---|---|
| `user_status` | 0x0 | 4 | `/data/status` |
| `tunnel_status` | 0x4 | 4 | `/data/data/tunnelStatus` |
| `username` | 0x8 | 0x80 | `/data/data/username` |
| `addr` | 0x88 | 0x104 | `/data/data/addr` |
| `sdpcguid` | 0x18c | 0x80 | `/data/data/sdpcguid` |
| pad | 0x20c | 4 | - |

`sizeof(atrust_status)` = 528 (`0x210`), matching the `CMMAlloc(0x210)` the call makes. The
caller passes `atrust_status **`; the library allocates the buffer and `atrust_free` releases it
(`atrust_free` was checked, not exercised - the probe's own process exits instead).

What the status call does, from the same disassembly and the trace: it posts the client's own
route - `POST /v1/service/status`, the request envelope this project already speaks - to the
agent's loopback service (`https://127.0.0.1:<httpserver port>`) and maps four fields of the
reply into the struct. It needs no SDK-side session and no portal reachability.

Measured live, and agreeing in the same state (client logged out, the container's own store):

```
atrust_initial('https://placeholder.invalid' -> rc 0, generic success
atrust_sync_query_status() -> rc 0;  user_status=20100 (0x4e84) tunnel_status=0
                                     addr="", username="", sdpcguid=""
POST /v1/service/status   -> code 0; status="logout"  tunnelStatus="tunnelUnavailable"
                                     addr="", username="", sdpcguid=""
```

The enum values seen: `user_status` `0x4e84` = 20100 = `logout` (the value the chain assigns
unless the status string is one of its two named cases), `0x4e86` = 20102 = `offline` and
`0x4e88` = 20104 = `passporttokentimeout` (both read off the comparison chain in the
disassembly; the offline string is matched from `/data/status`); `tunnel_status` `0` is the
default the chain leaves for `tunnelUnavailable`, `1` is the second named case and `2` the
`tunnelAvailable` one (the same chain; the live read only exercised `0`). A transition sample
(logout forced over the client's own route, both views read once a second for 30 s) held the
same pair the whole way - an already-logged-out client has nothing left to leave.

No field beyond the two enums could be exercised on this state: the identity strings are empty
while logged out, so their offsets are read off the disassembly and the first session-bearing
read is what confirms them (the login measurement below). `atrust_regist_listener` and the event
enum are untouched by this step; the login measurement's entry point has this shape from the
disassembly - `atrust_sync_login_by_pwd(user, password, force, atrust_auth_type *next, void
**data, domain)` -> `CssdkClient::LoginByUsrPwd(user, pwd, bool(force), next, data, domain)` -
recorded so the second measurement starts from a shape, not from a guess. (`force` is an `int`
in the C API and becomes the bool; `domain` is the sixth argument, which is what CSSDK 6.2.1's
"user@domain" rule feeds.)

## The login measurement (2026-10-12)

Attempted on the same throwaway container (client 2.5.16.30, its own store, the engine's RSA call
verified against the portal first), with the account from `~/.config/atrust.env` - the portal is
reachable from the container (`authConfig` answers `code 0`, `defaultDomain: local`).

```
atrust_sync_login_by_pwd(<user>, <password>, 0, nextAuth, data, "") -> 10403
    "unknown error, there is no coorespond error message" - after 0.3 s
    nextAuth = -1, data = NULL (nothing written)
    routes on utun7 right after and for the next 75 s: 0
```

Repeat run: identical 10403 after 0.3 s. Both runs left both views at
`logout`/`tunnelUnavailable`.

What the client itself says about the attempt (`SdkApi.log`, `aTrustHttpServer.log`, the core
plugin's log):

* SDK side: `Start login by pwd, force login=false` → `POST /v1/auth/psw` to the agent,
  `errorCode=10403, http response code=200, url=/v1/auth/psw, body={"code":10403,"message":"",
  "data":{"value":""}}` - so the call reached the client (172 ms for the whole round trip) and the
  client answered 10403;
* client side: `aTrustAuth: get auth impl by /v1/auth/psw` → `begin to psw auth.` → `select line
  result` ok → `Init line result` ok → `auth config finished. 0` → `init server config failed.;
  Reason: fail code: 10403` (the completion handler is `AuthConfigCallBackImpl::completionHandler`
  in `libaTrustAuth.so`), plus a warning `AntiMITMCore query SdpcPk failed.; Reason: Can't find
  https://<portal> key's value!` when it probes the device-key store. The auth plugin's log has no
  `passport` line at all while this happens: the attempt did not reach the portal - this is the
  client's own local auth setup refusing the login. (The warning alone does not decide it: the
  portal's `authConfig` answers `antiMITMAttackData.enable: 0`, so the anti-MITM check is not
  obviously mandatory; what the log pins is the handler and its `fail code: 10403`.)
* no window, no X11, no `uiauto` at any point in the attempt, and the tunnel never rose.

Credential half, settled separately: the same account and password on the project's own portal
login (`portal.py::PortalClient.login`) answers `code 75500000 图形验证码已超时，请重试` with
`graphCheckCodeEnable: 1`, `currentService/nextService: auth/psw` - the portal demands the
graphical captcha before it will take a password, so a bare password login cannot succeed on this
deployment (the engine's working logins get past it by reusing the client profile's stored
`tid`/`tid.sig`, which is why the captcha rarely surfaces in normal operation - the limit is
recorded in `docs/CLIENT-LOCAL-API.md`, "The API login path - landed"). The SDK's 10403 happens
before any of that: it cannot reach the login service because the client's own auth setup fails
locally first.

Not measured, for the record: what satisfies that local setup (the anti-MITM device-key store on a
profile that has completed a window login is the only candidate seen; whether a filled store is
enough, or the check is unconditional, needs the window again), and `nextAuth`/`data` in a
second-factor case - the call never gets far enough to answer a factor question.

## The decision (2026-10-12)

**Leave the SDK login path unlanded.** From the two measurements:

* it cannot log in on this deployment at all: the only login entry point the SDK has
  (`atrust_sync_login_by_pwd`) never makes a portal request - the client's local auth setup returns
  10403 before it - and where the request would go, the portal demands the graphical captcha, so a
  password-only call has nothing to win even with the local setup satisfied;
* it cannot replace the one path that does log in: the ticket path above runs on the same client
  and is already measured (`LOGGED_OUT` → `ONLINE` in five seconds); the window stays the fallback
  for the captcha and the second factors. The SDK's higher authority as the vendor-documented path
  did not translate into a call that works here;
* it would add a version-coupled ABI (the library speaks one struct and a fixed list of symbols for
  this client build) that is a thin client of the same loopback service this project already talks
  to, not a second channel: the status read lands on the same `POST /v1/service/status` the project
  already makes with `urllib` (`QueryStatus` additionally probes `/v1/detect` first), and the SDK's
  event listener reads the same `/v1/service/events` channel `EventPoller` already long-polls;
* what it would have brought - a window-free `_by_totp`/`_by_sms`/`_by_radius` - was not measured
  in its own right; each of those handlers is a sibling of the password one and the step's own
  finding is that the sibling cannot currently run, so claiming the second factors would land is
  not supported.

The fallback question the step posed (land it with `uiauto` kept until the SDK survives a client
bump) does not apply: on this deployment the landed code would never log in. Kept instead: the
ticket path, the window fallback, and this measurement. If a later deployment wants the SDK (a
portal that answers a plain password and a client whose profile carries the device keys), the
entry points are the ones measured here - `atrust_initial(portal)`,
`atrust_sync_login_by_pwd(user, pwd, force, &nextAuth, &data, domain)` - and the 10403 is the first
thing to reproduce.

## Exit criteria

- ✅ Both measurements are in this file with their numbers, and the decision follows from them.
- ✅ The index row and this file close in the same commit as the last `- ⬜`.
- (The "if code lands" criterion was removed on 2026-10-12 by the decision: no code landed, so
  there is no test run or live cycle to show.)

## Progress log

* 2026-10-11 — written after the reference doc landed. The read-only half is deliberately first: it
  needs no credentials and no session change, and if the ABI cannot be spoken from `ctypes` at all,
  that is known before the account is touched. Note that this is the *vendor-documented* path, unlike
  the HTTP routes: if the two disagree some day, the SDK is the one that is supposed to keep working.
* 2026-10-12 — the read-only measurement is in (section above): a throwaway container from
  `localhost/atrust-base:latest`, `libaTrustSDK.so` loaded through `ctypes`, the struct read back as
  528 bytes with the JSON paths the library's own `ATrustStatus::parse` fills it from, and the
  SDK's 20100/0 agreeing with `/v1/service/status`'s `logout`/`tunnelUnavailable` in the same state.
  Two things the binding has to get right, both measured: `atrust_get_cssdk_version` takes a buffer
  (assuming a returned `char *` segfaults - it cost one probe run), and `atrust_sync_query_status`
  returns an allocated `atrust_status *` that `atrust_free` releases. The identity fields are empty
  while logged out, so their live confirmation waits on the login measurement, which needs the
  account; that container stays up for it.
* 2026-10-12 — the login measurement is in too, and it decided: not landed. `atrust_sync_login_by_pwd`
  answers `10403` in 0.3 s, twice, with `nextAuth = -1` and `data = NULL`; the client's own logs show
  the call reaching `/v1/auth/psw` and the local auth setup refusing it
  (`init server config failed.; Reason: fail code: 10403`) before any portal request, and the portal
  would demand the graphical captcha anyway (`graphCheckCodeEnable: 1`, measured through this
  project's own portal login). No `utun7` route, no window, no `uiauto`. The decision section
  carries the reasoning; step 04's attempt accounting does not apply - the attempt never left the
  container. `docs/DESIGN.md`'s "How the client logs in" and `docs/CLIENT-LOCAL-API.md`'s item 4 now
  carry the same verdict (the latter had said "not attempted"). The measurement containers are
  torn down in the same commit; the engine's portal probe was refused before any session formed
  (the captcha answer carries no ticket), so the account's session on the portal was not touched.
