<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 22 — A client bump's own evidence

Status: ✅ done
Depends on: —
Touches: `atrustd/bundle.py` (new), `atrustd/__main__.py`, `atrustd/portal.py`,
`tests/test_bundle.py` (new), `tests/test_portal.py`, `Containerfile`, `README.md`, `docs/DESIGN.md`
(each `- ⬜` item below is one commit)

## Goal

The client version moves by hand (`base/build-args/<arch>.args` plus a live acceptance), and step 19
made the bump ritual ask for the client's own API acceptance. A bump can still move something nothing
documents, and neither upstream project debugs one without evidence: `zju-connect` ships
`-debug-pcap-file` and `-debug-tls-log-file`, both secret-bearing and both written 0600
([`internal/keylog`](https://github.com/Mythologyli/zju-connect/tree/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/internal/keylog),
[`underlay/pcap.go`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/underlay/pcap.go));
`EZ4Connect` exposes the same pair through its profile and builds the files 0600
([`corecommandbuilder.cpp#L230-L231`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/coreprocess/corecommandbuilder.cpp#L230-L231),
[`applicationpaths.cpp#L78-L95`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/infrastructure/storage/applicationpaths.cpp#L78-L95)).

We cannot pcap the client's userspace netstack, but everything a bump regression needs is already on
disk - and there is one thing the *portal* publishes about itself that this engine never looks at: the
digests of the certificates it serves. `authConfig` carries `data.antiMITMAttackData.rsaCert` /
`sm2encCert`, the digest is `SHA-256(base64(DER) + "@~*&!()-")`, and the official clients compare the
TLS peer's certificate against them and *log-and-ignore* a mismatch
([`auth/anti_mitm.go#L233-L258`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/anti_mitm.go#L233-L258),
[`auth/request.go#L130-L135`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/client/atrust/auth/request.go#L130-L135)).
This deployment's `authConfig` carries both certificates with `enable: 0` (read live 2026-10-13), so
the comparison has something to compare against, and the fingerprint line is the half that always
logs.

## Deliverables

- ✅ `atrustd --bundle` writes one timestamped tarball (0600) into `ATRUST_STATE_DIR`: `state.json`,
  the `NEED_VNC` hint and the captcha beside it, the client's own log **tail** (the profile grows
  ~0.2 GB/day, B02 - a tail, not the directory), `addr.conf`, a `/v1/service/status` read, the
  probe's route table, `/etc/atrust-version` and the client's version from the status read;
  `device-id`, the cookie store and every token stay out.
- ✅ The bundle names the app image's base reference or says that it is not recorded; today only the
  build argument `BASE_IMAGE` carries it, so the app image gains an `ENV` written from it.
- ✅ The portal's peer certificate leaves a fingerprint line: one extra `ssl` handshake with
  `CERT_NONE` beside a login, its SHA-256 at debug, compared against `authConfig`'s two digests when
  they are present - a mismatch is a warning, never a refusal (the official clients log-and-ignore; a
  hard rule here would break the internal-CA portals `insecure` exists for).
- ✅ Tests: the bundle's membership, mode and log-tail bound from a fake state directory; the digest
  comparison over a recorded pair (matching, mismatching, field absent).
- ✅ Live: one bundle on the live container, read back, with the scrub asserted - no credential, no
  token, no portal hostname beyond the deployment's own - and the fingerprint line seen in the
  journal.
- ✅ `README.md` documents `--bundle` and what it deliberately leaves out; `docs/DESIGN.md` carries
  the fingerprint line.

## Exit criteria

- ✅ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ✅ The live bundle is read back and the scrub assertion recorded in `## Progress log`, with the
  bundle's own file list.
- ✅ The index row and this file close in the same commit as the last `- ⬜`.

## Progress log

* 2026-10-13 — opened by the split of the survey archived at
  `docs/archive/2026-10-13-atrust-reimplementation-lessons.md` (then `B07`): the support bundle and
  the peer-certificate line are its candidates C and D, and the live `authConfig` reading quoted
  above is its review's.
* 2026-10-13 — a pointer from step 21 (the class table): `portal.py`'s `auth_config()` now computes
  `code`/`message`/`data` before its code check and raises with the answer's class, so the
  `data.antiMITMAttackData` this step compares is in the same `data` object as before, and the
  success path's `self.auth = data` is unchanged. `tests/test_portal.py` now carries the offline
  pattern a recorded `authConfig` pair needs (`LoginRefusalTest`: a stub `_request`, no socket; the
  socket `StubPortal` beside it for request-shape tests), and `main()`'s `--bundle` lands next to
  step 21's touched `--login-probe`/`--apps` branches without overlapping them.
* 2026-10-13 — implemented and accepted in one session, one commit per item; the tests of item 4
  landed inside items 1 and 3 (step 20's shape), so those two commits carry them:
  * `feat(atrustd): a bump's own evidence leaves in one tarball` — `atrustd/bundle.py` writes one
    timestamped tarball into `ATRUST_STATE_DIR` (0600, every member 0600): `engine/state.json`, the
    hint and the captcha when one is pending, `ip route show dev <tun>`, the client's own
    `/v1/service/status` answer, its `addr.conf`, the tail of `uiauto.tray_log`'s file (256 KiB —
    the tray's daily file is the one series with no rotation ceiling of its own, B02) and the
    image's `/etc/atrust-version`. The running client's version comes from its own
    `/v1/service/init` answer (`data.clientVersion`), because the `/v1/service/status` answer
    carries none — read live 2026-10-13; the manifest is the bundle's own explanation (the versions,
    one line per member, the reason an absent one is absent). `Config.client_version_file`
    (`/etc/atrust-version`, no environment variable: it is the image's own file) is the one path
    beyond the `Touches:` line. `--bundle` prints the tarball's path, reports an unwritable state
    directory as exit 1, and with `ATRUST_CLIENT_API=0` it records that the client's own read was
    left out instead of making it.
  * `feat(Containerfile): record the base reference the image was built from` — the stage re-declares
    `BASE_IMAGE` and writes `ENV ATRUST_BASE_REF=${BASE_IMAGE}`: a content-addressed base is
    otherwise unrecoverable from inside the built image, and this is the value the manifest's
    `base image` line reports or says is not recorded.
  * `feat(portal): the peer certificate leaves a fingerprint beside the login` — one extra `ssl`
    handshake with `CERT_NONE` beside every login, the peer's digest by the SDK's own identifier
    (`SHA-256(base64(DER) + "@~*&!()-")`; the two `antiMITMAttackData` fields are the base64 text,
    so the digest is taken over the text and not over the DER), a debug line for it and a warning
    when the portal published both certificates and neither matches — never a refusal, because the
    official clients log-and-ignore a mismatch and these portals sit behind internal CAs.
  * `docs: the evidence bundle, and the portal's certificate line` — the README's `--bundle`
    paragraph and operating command, DESIGN.md's certificate paragraph.
* 2026-10-13 — offline: 153 tests green (`python3 -m unittest discover -s tests`, up from 142;
  `tests/test_bundle.py`'s seven — the membership and the modes, the tail's bound and file choice,
  the scrub by value (device id and token), a bare state directory, a client that is down, the
  base-image line — and `tests/test_portal.py`'s `CertificateIdentityTest`, whose vector was
  computed once with `sha256sum` and pinned so a changed salt or encoding fails offline;
  `LoginRefusalTest`'s clients patch the handshake out, `portal.example` resolving nowhere) and
  `reuse lint` clean.
* 2026-10-13 — live, with step 20's ritual (the changed package copied into the container's
  `/tmp/step22` and imported from there; nothing the running daemon uses moved):
  * one bundle from the live container, read back on the host: `7 member(s), 23888 bytes`, the
    tarball 0600 and every member 0600 — `manifest.txt` 781, `engine/state.json` 376,
    `engine/routes.txt` 489 (`30 route(s) via utun7`), `client/status.json` 895 (the client's own
    answer: `online`/`tunnelAvailable`), `client/addr.conf` 27, `client/log-tail.txt` 262144 (the
    last 262144 of 589137 bytes of `aTrustTray.20261013.log`) and `system/atrust-version` 10. The
    manifest carried the two versions (`2.5.16.41`, from `/etc/atrust-version` and from the running
    client's own `/v1/service/init` answer), `base image: not recorded` — the live container still
    wears the published image, which has no `ATRUST_BASE_REF` — and `engine/NEED_VNC: not there - no
    hand-over is pending`, which is the healthy container's shape.
  * the scrub asserted over that tarball's members by value, not by name: the deployment's
    `ATRUST_PASSWORD` (16 chars), its `device-id` (43) and the client's own cookie values `tid` (36)
    and `tid.sig` (43) are all absent, there is no `device-id` member, and the only host string
    inside is the deployment's own portal.
  * the fingerprint line, from the service's own journal: `portal TLS peer certificate
    sha256=<sha256> matches authConfig (rsaCert, sm2encCert)` — this deployment's portal serves the
    certificate it publishes, so the identifier, the suffix and the comparison hold against a real
    portal (a wrong salt or a DER/base64 mix-up would have read as a mismatch). It was produced by
    `podman exec -e PYTHONPATH=… python3 -m atrustd -v --login-probe` with that output written
    through the container's PID 1: the line is debug by design and the daemon's own level is INFO,
    so a verbose run is how it is seen. The probe's login landed (`password auth ok`, `ok=True
    code=0`, a 73-character ticket) and the container stayed `ONLINE` with the client
    `online`/`tunnelAvailable` — the fresh login did not drop the client's session, either time.
  * the base reference's other half: `localhost/atrust-quadlet:dev` rebuilt from
    `localhost/atrust-base:latest` (the step's Containerfile change), `ATRUST_BASE_REF=
    [localhost/atrust-base:latest]` read back out of the image, and a bundle from a throwaway
    container of it names that value on its `base image` line.
