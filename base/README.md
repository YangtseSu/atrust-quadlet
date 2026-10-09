<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# The aTrust client image

Builds the client image this repository sits on: Debian 13, Sangfor's own aTrust package, and the
container plumbing the client expects.

```bash
# locally: the client image, then this repository's image on top of it
podman build -f base/Containerfile --build-arg-file base/build-args/amd64.args \
  -t localhost/atrust-base:latest base/
podman build --build-arg BASE_IMAGE=localhost/atrust-base:latest .

# or consume the published one (CI does this, and skips rebuilding it)
podman build \
  --build-arg BASE_IMAGE="ghcr.io/yangtsesu/atrust-quadlet:base-$(bash base/ref.sh amd64)" .
```

## The published client image

`publish.yml` publishes it as one more tag of the same package as the app image (GHCR grants
`GITHUB_TOKEN` write access only to packages linked to the repository, so a separate package would
have to be linked by hand):

| | |
|---|---|
| tag | `base-<client version>-<recipe hash8>-<arch>`, e.g. `base-2.5.16.30-8bd05f7d-amd64` |
| derived by | `base/ref.sh <arch>` - the client version from `build-args/`, the hash over `Containerfile` + `vendor/` + `overlay/` with relative paths, so both architectures agree |
| reuse | the `base` job asks the registry whether the tag exists and skips the build when it does (`podman manifest inspect` cannot read a single-architecture manifest, and the client images are per-architecture); an app-only change therefore builds one layer instead of the whole client install |
| force a rebuild | change anything in the recipe (a comment in the Containerfile is enough - it is hashed), or bump the client version in `build-args/` |
| per architecture | the base is pushed per architecture (no manifest list); the app image is the multi-arch artefact |

The client image contains Sangfor's package; publishing it is the same act as publishing the app
image, which carries it as a layer. The repository itself contains only the recipe (URLs and
sha256), never the package.

## Provenance, licence

The client comes from Sangfor's public CDN, downloaded at build time and verified by sha256
(`build-args/<arch>.args`); no vendor binary is committed here. The client itself is Sangfor's,
non-free software, and is not covered by this repository's licence.

The plumbing in `vendor/` is vendored from [Hagb/docker-easyconnect](https://github.com/Hagb/docker-easyconnect)
at commit `e8fc56a7c518d83b6817e16713f765e3c652e3bf` (2026-03-11). Upstream publishes it under the
WTFPL v2, which permits redistribution on any terms, so those files are redistributed here under
this repository's GPL-3.0-or-later, with the origin and upstream commit recorded in every file.
`fake-getlogin` and `fake-hwaddr` are upstream C sources; the Containerfile's `shims` stage compiles
them (the Makefiles carry an `.mk` suffix because they are not the top-level makefile of a tree).

## Layout

| Path | What it is |
|---|---|
| `Containerfile` | Debian 13 + the apt set + `dpkg -i` of the client + the plumbing |
| `build-args/<arch>.args` | the pinned client URL and sha256 per architecture (`--build-arg-file`) |
| `vendor/` | upstream files, body unchanged, header added (see above) |
| `overlay/` | this repository's own files; today only `start.sh` |

`overlay/start.sh` is upstream's `start.sh` reduced to the aTrust path: the detectors
(`detect-iptables.sh`, `detect-route.sh`), the client prelude (`vpn-config.sh`) and the client
restart loop (`start-sangfor.sh`) stay upstream and byte-identical, while the EasyConnect, noVNC,
chromium and ping paths are gone. `danted` is replaced by `microsocks`: `dante-server` is not in
Debian 13, and the SOCKS5 proxy only needs TCP `CONNECT` (the client's own routes decide the egress;
dante's `external.rotation: route` was doing the same). The cost is SOCKS5 `UDP ASSOCIATE`, which no
consumer of this project has used.

## The apt set

The list in `Containerfile` is derived, not copied: the client ships 106 ELF files and provides most
of its own libraries (`resources/bin`, `resources/lib`: boost, thrift, QtSolutions, OpenSSL 1.1,
nss, libprocps), so what Debian must provide is the set of `DT_NEEDED` names that the package does
not carry itself - Qt5 (Core/Gui/Widgets/DBus/Network), the Electron tray's shared-library set
(X11, GTK3, atk/atspi, asound, cairo, gbm, drm, cups, expat, dbus), `libsystemd0` (for the package's
own `libprocps.so.4`), `zlib1g`, plus the CJK font. The extraction was done once:

```bash
# every soname the client needs but does not ship
find /usr/share/sangfor -type f -exec ldd {} + 2>/dev/null | grep '=> not found'
```

Upstream's list contains packages this image does not need: `libssl1.1` (the client bundles
`libssl.so.1.1`/`libcrypto.so.1.1` in `resources/bin`, which `vpn-config.sh` puts first on
`LD_LIBRARY_PATH`, so every live process maps the bundled copies), `libnss3` (bundled the same way),
`novnc`/`websockify` and the self-built websocket `tinyproxy` (port 8080 is never published;
`probe.py` needs only a plain HTTP proxy, which `tinyproxy-bin` is), `chromium`, `qemu-user`,
`busybox`, `libssl-dev`, `libldap-2.4-2`, `libqt5x11extras5` and `fake-hwaddr`'s build chain. The
`nodejs`/`java-runtime` of other packagings (e.g. the AUR `atrust-bin`) are not needed either: the
working upstream image has neither, and no client process in a live run needs them.

## Bumping the client version

1. `curl -sI` the new `<version>/uos/<arch>/aTrustInstaller_<arch>.deb`, download it, `sha256sum` it,
   update `build-args/<arch>.args`.
2. Rebuild the base, then the image, and run the live acceptance (`docs/plans/` - step 04 covers the
   hand-over, the index lists the rest): the login window renders, `atrustd --login-probe`/`--once`
   reach `ONLINE`, both proxies answer from the host.
3. The window geometry is what a client version breaks first: re-check `uiauto`'s measured
   coordinates (`docs/DESIGN.md`) against the new window before shipping.

## Notes that cost time to find

* `dpkg -i` works in a container **only after** the runtime libraries are installed: the postinst
  runs `linuxHelper`, which refuses to start without Qt5 and makes the postinst exit 1
  (`Spa seed is out of time`). The shims (`loginctl`, `sysctl-hook`, `dmidecode -> /bin/false`) are
  installed before the package for the same reason.
* Debian 13 moved `sysctl` to `/usr/bin`; the hook keeps the upstream hard-coded
  `/usr/sbin/sysctl.real`, so the real binary is moved there and both the original path and
  `/usr/sbin/sysctl` point at the hook.
* The base carries no `VOLUME`: upstream's `/usr/share/sangfor/EasyConnect/resources/logs` volume is
  EasyConnect-only and left an anonymous volume on every container run.
