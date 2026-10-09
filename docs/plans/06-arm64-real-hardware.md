<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 06 — arm64 on real hardware

Status: ⛔ blocked — no arm64 host here
Depends on: an arm64 machine (a router, a small server, or any board that runs podman)
Touches: `docs/plans/README.md` (this row), nothing in the tree unless a defect turns up

## Goal

`linux/arm64` is built and published on every base change (`ghcr.io/yangtsesu/atrust-quadlet`, the
`base-…-arm64` client image and the manifest list), but no arm64 machine has ever run it. The Debian
package set and the vendor package are per-architecture, so "it builds" is not "it runs": the client's
own libraries, the userspace netstack and the tray's rendering are what this step checks.

## Deliverables

- ⬜ Run the published image (not a local build) on an arm64 host with the Quadlet unit or the plain
  `podman run` line from `README.md`: record the image digest, the client version
  (`podman exec atrust cat /usr/share/sangfor/aTrust/version`), the kernel and the container runtime
  version.
- ⬜ The offline checks repeated there: `ldd` over `/usr/share/sangfor` reports no missing library, the
  VNC port answers with an `RFB` banner, both proxies accept a connection.
- ⬜ The live path on that host, or the reason it cannot run there (for example: the portal is reached
  through a route the router does not have).
- ⬜ Any defect found becomes a `fix:` commit, and the finding is recorded here with the arch and the
  package versions.

## Exit criteria

- ⬜ `atrustd --status` reads `ONLINE` with routes on `utun7` on the arm64 host, and the record above
  is in the `## Progress log`.
- ⬜ If the host cannot run the full path, the record says what was verified instead — a partial answer
  closes nothing while a `- ⬜` item above is open.

## Progress log

* 2026-10-10 — written as step 06, blocked on hardware.
