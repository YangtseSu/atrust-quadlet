<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# The client's local API (loopback 54630 / 54631)

The aTrust client runs a private HTTPS service on loopback - the channel its own web workbench and
the vendor's CSSDK use to drive the client. It is not the SDPC controller's OpenAPI, Sangfor
publishes no route list for it, and it is an internal interface: every statement below was read out
of the client itself or exercised live, on client 2.5.16.30 inside this project's container
(2026-10-11). Treat it as evidence, not contract.

Re-verified on client 2.5.16.41 (2026-10-13, same container): the port file still reads `54630`,
`/v1/service/status` answered `online`/`tunnelAvailable`, `/v1/service/init` the same shape with
`clientVersion` now `2.5.16.41`, and `/v1/detect`, `/v1/getServicePort` (`httpserver` -> 54630) and
the event channel (login emitted on it) were unchanged. That is a spot check of the routes the
supervisor uses, not a re-measurement of the table above.

The two consumers in the image are the client's own web workbench
(`/usr/share/sangfor/aTrust/resources/app/web/`, with the older JavaScript SDK it grew from under
`old/jssdk/`) and the native SDK `/usr/share/sangfor/aTrust/resources/bin/libaTrustSDK.so` - the
"CSSDK" Sangfor documents - whose `atrust_*` C symbols drive the same service. The route set is
registered by `aTrustAgent` and its plugins (`resources/bin/plugins/aTrustCore/lib*.so`).

## What the service is

| | |
|---|---|
| listeners | `127.0.0.1:54630` and `localhost.sangfor.com.cn:54631` (the name resolves to 127.0.0.1; both expose the same routes - the domain form exists so browsers accept the self-signed certificate) |
| TLS | the client's own self-signed certificate, one year; every request must skip verification |
| current port | `/usr/share/sangfor/.aTrust/var/run/httpserver` holds the port in use (read back as `54630` inside the container) |
| drift | a taken port moves +11: `54630 → 54641 → 54652`, `54631 → 54642 → 54653` (`DEFAULT_PORT`/`BACKUP_PORT1..4`, `USEABLE_PORTS`/`DOMAIN_USEABLE_PORTS` in the client's web assets) |
| reachability | loopback inside the container only; not published to the host (measured 2026-10-11, see below) |

Request envelope - what the client's own workbench sends and the service expects:

```json
{"addr": "<portal>", "type": "web", "guid": "<sdpcguid>", "lang": "zh-CN",
 "token": "", "sdpTraceId": "<hex>", "data": { ... }}
```

`POST` with `Content-Type: application/json`. `type` is one of `web`, `cs`, `sdk`. Responses are
`{"code": 0, "message": "...", "data": { ... }}` - `code` 0 means success; seen beside it:
`11119003` invalid request, `11112002` query database failed, `11119064` proxy forwarding failed.
Those refusals are read as classes beside their codes (`atrustd.clientapi.classify`, carried
on `ClientStatus`/`StartResult`): the three above as `invalid-request`, `query-failed`,
`proxy-failed`, and the login path's own - `11119054` `already-logged-in`, `75500304`
`stale-ticket`, `10000001` `invalid-parameter`, measured 2026-10-11. Every other code is carried
without a class, and a route that answers no `code` at all - the schema refusal, `Invalid schema:
#/properties/guid` - is not a code: it stays the string it is. (Not `msg` - the field is
`message`.)

Two gates sit in front of the routes:

* **The method is part of the route.** `GET /v1/detect` answers `404 {"code":0,"message":"Unsupport
  url"}` while the same path over POST works; `GET /v1/service/status` and `GET /v1/service/events`
  answer `503`.
* **The portal-origin `Referer`.** A request without it gets
  `403 {"code":11119003,"message":"Invalid request."}` on the gated routes (`/v1/service/online`,
  `/v1/aUem/queryUemConfig`, ...), and `/v1/service/status` answers with the identity fields
  blanked: without the header `username`/`clientIp` are empty, with `Referer: <portal>/` they are
  filled (measured 2026-10-11, both ways). The workbench sends its own origin, which is the portal.

## Verified live (2026-10-11, client 2.5.16.30)

All of these were called from inside the container against `https://127.0.0.1:54630` with the
envelope above; `<portal>` is the address the client is configured with.

| Route | `data` sent | Observed |
|---|---|---|
| `POST /v1/detect` | `{}` | `{"code":0,"message":"detect successfully","data":{"pubkey":""}}` |
| `POST /v1/service/status` | `{}` | `{"code":0,"data":{"status":"online","data":{...}}}` - see below |
| `POST /v1/service/init` | `{"pubKey":"","verifyCode":""}` | `{"code":0,"data":{"status":"otherSdpCLogin","sidTicket":"","addr":"<portal>","tunnelStatus":"tunnelAvailable","guid":"<sdpcguid>","capacities":{...},"clientVersion":"2.5.16.30"}}` |
| `POST /v1/service/events` | `{"fromId":24,"timeout":2000}` | long-poll, see the event channel below |
| `POST /v1/service/online` | `{}`, `Referer: <portal>/` | `{"code":0,"message":"Succeeded","data":{"sidTicket":"<uuid>_<uuid>","authorLevel":0}}` |
| `POST /v1/getServicePort` | `{"serviceName":"httpserver"}` | `{"code":0,"data":{"addr":"127.0.0.1","port":54630}}`; `eventbus` → 55630, `/plugin-daemon/thrift` → 56630, `debugserver` → 54677, an unknown name → port 0 |
| `POST /v1/base/setter` | `{"key":"<key>","value":"aGVsbG8="}` | `{"code":0,"message":"Operator successful"}` |
| `POST /v1/base/getter` | `{"key":"<key>"}` | `{"code":0,"data":{"value":"aGVsbG8="}}` (round-trip verified; an unknown key answers `11112002` with an empty value) |
| `POST /v1/service/queryAppModuleInfo` | `{}` | `{"code":0,"data":{"resourceReady":1}}` |
| `POST /v1/update/status` | `{}` | `{"code":0,"data":{"status":"idle","waitUpdate":{"type":"","tips":"","version":""}}}` |
| `POST /v1/service/reportEnv` | `{}` | `{"code":0,"message":"Operator successful"}` |
| `POST /v1/base/setinfo` | `{}` | `{"code":0,"message":""}` (accepted; what the workbench sends is the identity/resource payload from the portal) |
| `POST /v1/aUem/status` | `{}` | uem status object (`workModeStatus`, `installStatus`, ...) |
| `POST /v1/aUem/uemInfo` | `{}` | `{"currentProcessWorkspace":"","resourceReady":1,"supportMultiWorkspace":1,...}` |
| `POST /v1/aUem/queryUemConfig` | `{}`, `Referer: <portal>/` | `{"networkInterceptLogSwitch":false}` (403 without the Referer) |
| `POST /v1/aUem/queryWorkspaceInfo` | `{}`, `Referer: <portal>/` | `{"data":[]}` (403 without the Referer) |
| `POST /v1/eaio/status` | `{}` | module list (`EDR`, `AC`, each with `status`/`installStatus`) |
| `POST /v1/service/immediatelyRepair` | `{}` | `{"code":0,"data":{"context":{"traceID":"","sdpcURL":"","items":[]},"items":[]}}` |
| `POST /v1/service/logout` | `{"type":"force","guid":"<sdpcguid>","addr":"<portal>"}`, `Referer: <portal>/` | `{"code":0,"message":"OK"}`; the client goes `logout`/`tunnelUnavailable`, the routes on `utun7` drop to 0 within two seconds |
| `POST /v1/service/start` | `{"sidTicket": "<73-char ticket>"}` (from the portal's `ticketExchange` or the agent's `online`), envelope `guid` non-empty | `{"code":0,"message":""}` and the tunnel is up three to five seconds later (see below); an already-online client answers `{"code":11119054,"message":"已经登录成功"}` whatever the ticket (`already-logged-in`); a stale ticket answers `75500304 当前票据已失效` (`stale-ticket`), an empty one `10000001 invalid_param in body` (`invalid-parameter`), and an empty envelope `guid` `Invalid schema: #/properties/guid` (no code, no class) - all measured 2026-10-11 |

`/v1/service/status` in full (the interesting half; `<user>`/`<client-ip>` need the Referer):

```json
{"code":0,"message":"","data":{"status":"online","data":{
  "addr":"<portal>","username":"<user>","trustlevel":0,"tunnelStatus":"tunnelAvailable",
  "sdpcguid":"<sdpcguid>","passportTokenEnable":false,"loginTime":"2026-10-11 13:00:18",
  "clientIp":"<client-ip>","uemStatus":{...},"displayName":"","userOrg":"/"}}}
```

`status` is the client's own user state; the values the workbench knows are `online`, `offline`,
`disconnect`, `logout`, `firstLogin`, `reLogin`, `otherSdpCLogin`, `otherSessionLogin`,
`otherSdpCOffline` (the `Gs`/`Fp`/`Hp` enums in the web assets), and `tunnelStatus` is
`tunnelAvailable`/`tunnelUnavailable`/`tunnelPreparing` - the same vocabulary the official CSSDK
documents (see below).

`/v1/getServicePort` wants `{"serviceName": "httpserver" | "eventbus" | "/plugin-daemon/thrift" |
...}` - the only schema that says so in as many words, since the plugin binary embeds it with
`serviceName` required - and answers the port the agent handed that service.

### The login path, verified

Measured 2026-10-11 on the live container, in this order, with no window and no X11 involved:

1. `POST /v1/service/logout` `{"type":"force","guid":"<sdpcguid>","addr":"<portal>"}` →
   `{"code":0,"message":"OK"}`. Two seconds later the client reads `logout`/`tunnelUnavailable` and
   `ip route show dev utun7` is empty.
2. The engine's own portal session (this project's `portal.py` login) is used to mint the ticket the
   workbench hands over: `POST /passport/v1/public/ticketExchange` (the engine's cookies, empty
   body) → `{"code":0,"data":{"sidTicket":"<73 chars>"}}`. The agent's own
   `POST /v1/service/online` mints an equivalent ticket from the client's side, so either session
   can produce one.
3. `POST /v1/service/start` `{"sidTicket": "<ticket>"}` → `{"code":0,"message":""}`. Three seconds
   later the client reads `online`/`tunnelAvailable` and the routes are back.

The event channel saw the same transition, which is what makes it usable as a trigger: at logout it
emitted `leaveOnlineRun`, `leaveOnline`, `logout` (with `allLoggedOut`, the logout type and the
origin), `enterInitial`, `resourceReady: 0`; at the start, two seconds later, `leaveInitial`,
`login`, `enterOnline`, `enterOnlineRun`, `resourceReady: 1`, `tunnelStatus` (`tunnelAvailable`
with the user name) and the full `status` object.

Nothing on this path touches the client's window: the supervisor's `uiauto` step and the X11
geometry it depends on are not involved. That is the vendor's own flow - the workbench's SPA does
exactly these calls - and it is the reason this document exists.

**The limits of that path, measured 2026-10-11 in the same container** (a forced logout of a client
that held a live portal session, then the supervisor's own recovery attempts):

* after the logout the portal keeps the account "online" and refuses a fresh password login with
  `code=75500006 当前账号已在线，无需重复上线`; two attempts were refused and the next one was accepted
  ~24 minutes later (in line with the portal's ~20 min session expiry). The client's own window login,
  submitted with the right credentials, did not bring the tunnel up either. The re-attach path above
  is for a session that *exists* - it does not replace logging in again, and a recovery on this path
  is bounded by the portal's own session expiry.
* `POST /v1/service/online` answers `code=75500307 非法的随机校验码` while the client is logged out, so
  the ticket has to come from a live session (the engine's, above), not from the logged-out agent.

### Reaching it from the host

The service binds `127.0.0.1` only, so a published port does not reach it by itself. Measured
2026-10-11 with throwaway containers from this image (`pasta` networking, the same mode the Quadlet
unit uses):

* a server bound to the container's `127.0.0.1` and published as `-p 127.0.0.1:PORT:PORT` is
  **unreachable from the host**; the same server bound to `0.0.0.0` (or to the container's
  mirrored host address) is reachable. `pasta` delivers a published port to the container's
  non-loopback address, not to its loopback.
* a relay inside the container bound to `0.0.0.0` that forwards to `127.0.0.1:<port>` makes the
  loopback service reachable from the host through its published port - verified with a plain
  `socat tcp-listen:PORT,reuseaddr,fork tcp4:127.0.0.1:<port>` and with the real client: a fresh
  container from `localhost/atrust-base:latest` published as `-p 127.0.0.1:15436:20000` answers
  `POST https://127.0.0.1:15436/v1/detect` from the host with
  `{"code":0,"message":"detect successfully","data":{"pubkey":""}}` about nine seconds after the
  client starts.
* the image already runs such a relay for **54631**: `force_open_ports()` in
  `base/overlay/start.sh` starts `socat tcp-listen:20000,... tcp4:127.0.0.1:54631`. Its companion
  iptables `REDIRECT 54631 -> 20000` is dead under `pasta` - the instrumented rule counted 0
  packets while the published port was being exercised, because the forwarded connection is
  generated inside the container's namespace and never traverses `PREROUTING`. Publishing
  `54631` itself therefore still fails; publishing **`20000`** is what reaches the agent.
* nothing is published for `54630`, so the IP-form port would need a relay of its own.

Two consequences: a host-side caller can use the service with
`PublishPort=127.0.0.1:54631:20000` in the unit (plus the self-signed certificate and, for the
gated routes, `Referer: <portal>/`), and exposing it hands the host whatever the service offers -
`logout`, `offline`, the status and the event channel - so the publish should stay on `127.0.0.1`.

## The event channel

`/v1/service/events` is the state-change push channel, in two flavours over the same port.

**Long poll.** `POST /v1/service/events` with `data: {"fromId": <last id you have>, "timeout": <ms>}`
blocks for up to `timeout` and answers:

* nothing new: `{"code":0,"message":"OK","data":{"id":25}}` after exactly the timeout (2.00 s for
  `timeout: 2000`, measured);
* new events: immediately, `{"code":0,"message":"OK","data":{"events":[{"event":"endConsult",
  "data":{"addr":"<portal>","needUpdate":false}}],"id":25}}`.

`fromId: 0` behaves like "from now" on this transport (it waits out the timeout and returns only the
id), while the WebSocket flavour with `fromId: 0` replays the backlog.

**WebSocket.** `wss://127.0.0.1:54630/` (no path) is the same service upgraded. The handshake is
accepted with `Origin`/`Referer` set to the portal origin and refused otherwise - without them the
server completes the upgrade and then closes with code `1008` reason `Insecurity connection`
(measured). After the upgrade, JSON messages:

```json
{"mode":"request-response","type":"request","path":"/v1/service/events",
 "sdpTraceId":"<hex>","seq":0,"version":1,"from":"web","data":{"fromId":0,"pid":0}}
```

is the subscription; the server answers with events as
`{"mode":"event","type":"notify","path":"/v1/service/events","from":"aTrustAgent",
  "data":{"events":[{"event":"ready","data":{"channel":"websocket"}}],"id":25,"pid":237},"seq":0,"version":1}`
and expects a heartbeat every few seconds
(`{"mode":"heartbeat","type":"ping","path":"ping",...}` → `{"mode":"heartbeat","type":"pong",
"path":"ping","from":"HttpServer",...}`). A `seq` gap makes the client's own code reconnect, so a
subscriber has to count messages the same way. Verified live with a throwaway subscriber: handshake,
subscription, the `ready` event, ping/pong over 30 s, and `endConsult` through the long-poll.

Event names seen or read out of the client: `ready`, `endConsult` (both captured live) and, in the
workbench's subscription table and the plugins' topic strings, `online`, `offline`, `logout`,
`status`, `uemStatus`/`uemStatusV2`, `uemInfo`, `resourceReady`, `enterInitial`, `enterOffline`,
`enterOnlineRun`, `enterOnlineNetworkAnomaly`; the core plugin also publishes
`statusEvent|logout`, `statusEvent|offline`, `statusEvent|networkReset`, and the SDK maps its own
enum onto them (`USER_LOGOUT` 10001, `TUNNEL_STATUS` 10002, upgrade and diagnosis events).

A client-family restart with a live session (measured 2026-10-11, the supervisor's own restart path)
shows what the channel carries when the client comes back: the subscriber is dropped when the agent
dies and reconnects, then receives, within the same second, `ready`, `resourceReady`,
`tunnelStatus` (with the type, the portal address, the guid and the user name), the full `status`
object, `supportWorkspace`, `uemStatus`, `uemStatusV2`, and `beginConsult`/`endConsult` around the
client's own portal consult. The event ids restart per connection, so a subscriber that reconnects
must reset its `fromId` (the client's own workbench does the same and reconnects on a `seq` gap).

The client's own components speak this channel too, and its HTTP server keeps a request/response log
at `/home/sangfor/.aTrust/logs/aTrustHttpServer.log` - method, URL, user agent, request and response
body for every call the tray, the workbench and anything else makes. It is the cheapest way to learn
a route's real shape: the tray's own calls (for example `/v1/datebase-kv/getter` with `type: "cs"`
and its own user agent) sit in there beside the probes.

The vendor's own guidance for the same channel (CSSDK docs, 6.5): on a logout or tunnel event do
not set your state from the event - call the status query to confirm. The tunnel event may arrive
twice with the same content, and a forced login can emit a logout for the user it displaced.

## The official documentation, and the SDK in the image

Sangfor documents this channel indirectly, as the "CSSDK":

* `https://bbs.sangfor.com.cn/atrustdeveloper/pcsdk/docs/` - the integration guide; 6.4 状态查询
  (status query), 6.5 事件监听 (event listener), 6.6 注销 (logout), 6.1/6.2 (init, password login).
  It describes the C API, not the HTTP routes, but the vocabulary maps 1:1 (`atrust_sync_query_status`
  → user status + tunnel status + online username/sdpc addr/sdpc guid; `atrust_regist_listener` →
  `USER_LOGOUT`/`TUNNEL_STATUS`/update/diagnosis; `atrust_sync_login_by_pwd`/`_by_totp`/`_by_sms`/
  `_by_radius` → the login flows).
* `https://bbs.sangfor.com.cn/atrustdeveloper/aTrustClient/docs/` - the client troubleshooting
  guide, the only official page that names the ports and `localhost.sangfor.com.cn`.

The image already ships that SDK: `/usr/share/sangfor/aTrust/resources/bin/libaTrustSDK.so` exports
the documented C API (`atrust_initial`, `atrust_sync_login_by_pwd`, `atrust_sync_login_by_totp`,
`atrust_sync_login_by_sms`, `atrust_sync_login_by_radius`, `atrust_sync_query_status`,
`atrust_regist_listener`, `atrust_clear_listener`, `atrust_sync_logout`, `atrust_start_update`,
`atrust_start_diagnosis`, ...) and links only against libraries the image already has (its own
bundled `libssl.so.1.1`/`libcrypto.so.1.1`/`libboost_filesystem.so.1.70.0`, the system libc).
It has not been called from this project yet.

## Routes that exist but were not exercised

Deliberately left alone: they change the session or the tunnel, or need a state this project is not
willing to create. Everything in this table was reached at least once, so "route exists" is
measured; the shape of `data` comes from the schema embedded in the plugin binaries.

| Route | What it needs (`data`) | Why not tested |
|---|---|---|
| `POST /v1/service/offline` | `{}` or `{"type": ...}`, per the tray's own code | **attempted, rejected**: every shape tried answers `422 {"code":10000001,"message":"invalid_param in body"}` - `{}`, `{"type":"offline"}`, `{"type":"offlineExit"}`, `{"type":"clientexit"}`, `{"type":"noOperationOffline"}`/`"timeoutOffline"`/`"nativeOffline"`/`"passportTokenOffline"`, `{"dataType": ...}`, `{"type": 1}`, `{"quickLogout": true, "type": "force"}`, envelope `type` `web`/`cs`/`sdk`, `Referer` `<portal>/` and `<portal>/portal/`, the tray's own user agent - while the tray's code (`tray_controller.js`, `Protocal.EVENT_OFFLINE = "offline"`) says it sends `{"type":"offline"}`. What the handler wants was not found; the string is in neither the agent nor the plugins |
| `POST /v1/service/logout` | `{"type":"clientexit"\|"passportTokenLogout"\|"force", "guid":"...", "addr":"..."}` | ends the session on the portal |
| `POST /v1/update/start`, `/v1/update/skip`, `/v1/update/check` | - | would upgrade the client |
| `POST /v1/update/version` | `{}` | answers `403 Invalid request.` with and without the portal Referer on this build; purpose unknown |
| `POST /v1/service/deviceauth` | `{"verifyCode": "..."}` | needs the portal's device-auth challenge |
| `POST /v1/service/getCertInfo` | `{"pubKey": "...", "verifyCode": "..."}` | as above |
| `POST /v1/service/checkMITMAttack` | `{"antiMITMAttackData":{"enable":..,"challenge":..,"encryptedChallenge":..,"ticket":..},"csrfToken":".."}` | the workbench calls it with the portal's own challenge |
| `POST /v1/service/startDiagnosis` | required fields unknown (schema rejects `{}`) | diagnosis tool |
| `POST /v1/service/immediatelyDiagnosis` | - | diagnosis tool (the sibling `immediatelyRepair` was called with `{}` and answered an empty context) |
| `POST /v1/service/proxy` | `{"origin": "...", "target": "..."}` | forwards through the client; `{}` answered `11119064` (`proxy-failed`) |
| `POST /v1/service/PopupPhishingRiskConfirm`, `/v1/service/reportEnvBeforeLogin` | - | workbench-side UI/probing calls |
| `POST /v1/base/updateConfig` | required fields unknown (schema rejects `{}`) | - |
| `POST /v1/base/printLog` | `{"log": "..."}` | writes into the client's log |
| `POST /v1/public/timestamp` | - | the route string is in the plugin but POST answers `404 Unsupport url` on this build |
| `POST /v1/auth/*` (`psw`, `totp`, `sms`, `radius`, `sangforId`, `fetchSmsCode`, `onlineConfig`, `logout`, `common`) | per-route fields; `common` answered `{"code":11019,"message":"请输入服务器地址"}` | this is the client's own authentication path (the native SDK's login entry points call it); a wrong call is a login attempt against the account, and a successful one rotates the device token |
| `POST /v1/auem/queryuemconfig`, `/v1/auem/queryworkspaceinfo` | - | not routes: the real paths are `/v1/aUem/queryUemConfig`, `/v1/aUem/queryWorkspaceInfo` (both tested) |

Also from the client's own code, not exercised: `/v1/tray/start`, `/v1/tray/exit` (the SDK's tray
control), `/v1/burydata/querydata`, `/v1/burydata/update` (log collection), `/v1/service/gm/*`
(GM/TLCP certificate auth), `/v1/user/task`, `/v1/datebase-kv/getter`/`setter`, and the `aUem`
approval/file routes (`/v1/aUem/approvalList`, `fileDownload`, ...).

## For this project

Measured, not proposed:

* the supervisor's checks are its own: `probe.check()` forks `ip -brief addr show utun7` and
  `ip route show dev utun7` and sends a real request through the container proxy to an intranet
  target; the web-session check is this project's own portal call (`portal.py`). The client's local
  API is additionally what `atrustd/clientapi.py` drives - the client's own view beside every
  transition, the event channel as a wake, and the ticket handover when a session is gone - and the
  decisions still come from the data plane.
* measured 2026-10-11: stopping the client family the way the supervisor does, and letting the
  vendor's own restart loop bring it back, restores the tunnel **without any window login** - the
  agent's port reopened six seconds after the kill and `ip route show dev utun7` was back to its 30
  routes at the same moment, with the client's own `/v1/service/status` reading
  `online/tunnelAvailable` (the session survived in the client's profile). The supervisor's "web
  session is alive but the tunnel is not" branch restarts the client and waits; it needs no
  `uiauto` on this path, and the window login is what the *other* branch (session gone) exists for.
* the keepalive is the same probe: the real request every `ATRUST_WATCH_INTERVAL` is what the
  portal's session survives on (measured 2026-10-09: `CONNECT`-only traffic died in 10.3 minutes,
  real requests held it for hours). `/v1/service/online` is not that keepalive - it answers with a
  one-time `sidTicket`, i.e. it is the login handshake's first half, not a heartbeat.
* measured 2026-10-11: the engine's own portal session can mint the ticket the workbench hands to
  the client - `POST /passport/v1/public/ticketExchange` with the engine's cookies and an empty body
  answers `code 0` with a 73-character `sidTicket` (the same value `/v1/service/online` mints from
  the client's side), and `/v1/service/start` takes that shape and brings a *logged-out* client up:
  the supervisor's own recovery measured `LOGGED_OUT` 23:51:50.8 → mint 23:51:50.9 → `start`
  23:51:51.1 → `ONLINE` 23:51:56.2, the client's own events showing `leaveInitial`, `login` and
  `enterOnline` on the way. The answer codes and the envelope's requirements are in the route table
  above.
* the notify path is host-side on purpose: `notify-send` needs the user's session bus and the
  container has none. The agent's port is not published, and a published port would not reach it
  without a relay inside the container ("Reaching it from the host" above) - feeding
  `quadlet/atrust-notify.sh` from the event channel would mean publishing the client's control API
  to the host and running a subscriber there, against a host side that is deliberately `sh` plus
  systemd units only.

How this project uses the interface, and what is still open:

1. **A cheap state read - landed.** `POST /v1/service/status` is one loopback request and returns
   the client's own view (user state, tunnel state, username, login time, and the `sdpcguid` the
   ticket handover's envelope needs). Every transition records it beside the probe's detail
   (`state.json`'s `client` object, the journal line), and nothing acts on it yet: in the controlled
   downs it never disagreed with the probe, it cannot replace it (the client can report
   `tunnelAvailable` while the netstack drops traffic), and the one vocabulary only it can express
   (`otherSdpCLogin`/`otherSdpCOffline`) does not occur on a deployment that talks to a single
   portal.
2. **Event-driven wake-up - landed.** `atrustd.clientapi.EventPoller` long-polls
   `/v1/service/events` from a background thread and turns the session and tunnel vocabulary into a
   `threading.Event` the daemon's waits watch, so a client-side transition starts the next cycle in
   seconds instead of at the next `ATRUST_WATCH_INTERVAL` (measured 2026-10-11: wake +5.3 s after a
   provoked down). The woken cycle is unchanged and the probe still decides - the vendor's own
   advice for the channel.
3. **The API login path - landed.** The supervisor's dead-session branch walks the sequence under
   "The login path, verified" above before the window: mint (`portal.sid_ticket`), hand over
   (`clientapi.start`), wait for the tunnel on a 60 s bound; the window path stays the fallback and
   every failure carries its reason into the journal and the state detail. Measured live 2026-10-11:
   `LOGGED_OUT` 23:51:50.8 → mint 23:51:50.9 → `start` 23:51:51.1 → `ONLINE` 23:51:56.2 (five
   seconds, no window opened), and with a cold engine session, a fresh login first: `LOGGED_OUT`
   23:53:46.6 → `ONLINE` 23:54:17.7 (31 s; 20 of them the client's own stop). Two measured limits:
   a fresh container's client publishes no `sdpcguid` for its first ~40 s (the attempt is skipped
   then), and the `web session is alive` restart branch runs before the ticket path - 2.2 minutes in
   the drill, before the ticket path recovered the same session in five seconds. What the path does
   **not** cross is a cold login on a portal that demands the graphical captcha: measured 2026-10-11
   with a second account in a throwaway container, the captcha stopped both the engine's portal
   login (so no ticket could be minted) and the client's own window login, and it is a click-in-order
   image - the human in the window is what finishes that login. The API path pays off for a session
   that exists and has to be re-established, not for one that has to be created.
4. **The SDK login path - measured, not landed** (2026-10-12, client 2.5.16.30, a throwaway
   container with the account). `libaTrustSDK.so` is the vendor-documented version of the same
   thing (`atrust_sync_login_by_pwd`, plus `_by_totp`/`_by_sms`/`_by_radius` for the second factors
   this project hands to VNC), and its status query is a thin client of the route above: loaded
   through `ctypes` it answers 20100/0 in the logout state, agreeing with `/v1/service/status`.
   The login, however, does not work here: `atrust_sync_login_by_pwd(user, pwd, 0, &nextAuth,
   &data, domain)` returns `10403` in 0.3 s, twice, and the client's own logs show the call
   reaching `/v1/auth/psw` and failing in its local auth setup
   (`init server config failed.; Reason: fail code: 10403`) before any portal request - no
   `utun7` route, no window. The portal would demand the graphical captcha anyway
   (`graphCheckCodeEnable: 1` on this deployment's account), so a password-only call has nothing
   to win even with the local setup satisfied. The ticket path above stays the way in; the full
   numbers are in step 15's plan file.
5. **Port discovery - landed.** `atrustd.clientapi` reads the port from
   `/usr/share/sangfor/.aTrust/var/run/httpserver` and falls back to the `+11` candidates
   (`54641`, `54652`) for a drifted or stale file; nothing assumes 54630.
6. **A clean shutdown** (B05). `POST /v1/service/logout` ends the session on the portal instead of
   leaving it to expire after the container's process sweep; it is measured to work
   (`{"code":0,"message":"OK"}`, the client goes `logout` within two seconds), but the stop path is
   deliberately fast (≲2 s) and adding a call to it needs its own measurement.
