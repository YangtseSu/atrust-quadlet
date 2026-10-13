<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 22 — A client bump's own evidence

Status: ⬜ not-started
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

- ⬜ `atrustd --bundle` writes one timestamped tarball (0600) into `ATRUST_STATE_DIR`: `state.json`,
  the `NEED_VNC` hint and the captcha beside it, the client's own log **tail** (the profile grows
  ~0.2 GB/day, B02 - a tail, not the directory), `addr.conf`, a `/v1/service/status` read, the
  probe's route table, `/etc/atrust-version` and the client's version from the status read;
  `device-id`, the cookie store and every token stay out.
- ⬜ The bundle names the app image's base reference or says that it is not recorded; today only the
  build argument `BASE_IMAGE` carries it, so the app image gains an `ENV` written from it.
- ⬜ The portal's peer certificate leaves a fingerprint line: one extra `ssl` handshake with
  `CERT_NONE` beside a login, its SHA-256 at debug, compared against `authConfig`'s two digests when
  they are present - a mismatch is a warning, never a refusal (the official clients log-and-ignore; a
  hard rule here would break the internal-CA portals `insecure` exists for).
- ⬜ Tests: the bundle's membership, mode and log-tail bound from a fake state directory; the digest
  comparison over a recorded pair (matching, mismatching, field absent).
- ⬜ Live: one bundle on the live container, read back, with the scrub asserted - no credential, no
  token, no portal hostname beyond the deployment's own - and the fingerprint line seen in the
  journal.
- ⬜ `README.md` documents `--bundle` and what it deliberately leaves out; `docs/DESIGN.md` carries
  the fingerprint line.

## Exit criteria

- ⬜ `python3 -m unittest discover -s tests` and `reuse lint` stay green.
- ⬜ The live bundle is read back and the scrub assertion recorded in `## Progress log`, with the
  bundle's own file list.
- ⬜ The index row and this file close in the same commit as the last `- ⬜`.

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
