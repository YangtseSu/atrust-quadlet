<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# atrust-quadlet

[![publish](https://github.com/YangtseSu/atrust-quadlet/actions/workflows/publish.yml/badge.svg)](https://github.com/YangtseSu/atrust-quadlet/actions/workflows/publish.yml)

Run the Sangfor aTrust client in a podman container with supervised auto-login, for headless
hosts (routers, workstations, CI boxes): you get the VPN tunnel plus the SOCKS5/HTTP proxies the
image provides, and you do **not** have to pass portal cookies around as parameters.

*Not affiliated with, or endorsed by, Sangfor. The aTrust client itself is not part of this
project's source: the image builds it in from Sangfor's own package (see [`base/`](base/README.md)),
which is downloaded from their public CDN at build time and pinned by sha256.*

## What you get

| Capability | What it means |
|---|---|
| Automatic login | the engine logs in to the portal for you and keeps the client's own tokens fresh, so the client side stops asking for the captcha - there is no cookie option to pass |
| Automatic re-login | the supervisor watches the tunnel and logs in again on its own when the session goes away; a portal-forced logout costs roughly two minutes, without a human |
| The client's own window is driven for you | portal address, account, password and agreement are filled and submitted with X level input, so the client accepts the session |
| Captcha or first login | the supervisor writes a `NEED_VNC` hint plus the captcha image and waits: open VNC, finish the login in the desktop, and supervision continues by itself |
| The apps behind the tunnel | every login publishes what the portal grants this account (name, launch URL, launch method, server address); `atrustd --apps` prints it |
| podman, not docker | everything is podman and Quadlet; the image builds the client, the VNC X server and the proxies itself (`base/`, from Sangfor's own package) with the rootless-podman plumbing the client expects |
| Loopback-only ports | VNC `5901`, HTTP proxy `8888`, SOCKS5 `1080` - published on `127.0.0.1`, nothing is exposed to the network |

## Quick start

```bash
podman pull ghcr.io/yangtsesu/atrust-quadlet:latest
install -d ~/.config/containers/systemd
install -d ~/.atrust-data ~/.atrust-data/run   # mounted at /root and /run/atrustd; podman wants
                                               # the bind sources to exist
cp quadlet/atrust.container ~/.config/containers/systemd/
install -m600 quadlet/atrust.env.example ~/.config/atrust.env   # edit it first
systemctl --user daemon-reload
systemctl --user start atrust.service
journalctl --user -u atrust.service -f
```

The image is public, built for `linux/amd64` and `linux/arm64`: `:latest`, `:main` and `:<git sha>`
are published; a `v*` tag adds the version tags (e.g. `:1.0.0`, `:1.0`) and moves `:latest` to the
release. To build it yourself instead, the client image first (it downloads Sangfor's package,
~200 MB) and then this repository's image:

```bash
podman build -f base/Containerfile --build-arg-file base/build-args/amd64.args \
  -t localhost/atrust-base:latest base/
podman build --build-arg BASE_IMAGE=localhost/atrust-base:latest \
  -t ghcr.io/yangtsesu/atrust-quadlet:latest .
```

The client image is also published, content-addressed
(`ghcr.io/yangtsesu/atrust-quadlet:base-$(bash base/ref.sh amd64)`), so a hand build can skip the
Sangfor download and use it as the `BASE_IMAGE`.

Container state lives in `~/.atrust-data`: the client's own profile (mounted at `/root`) and the
`atrustd` state file (mounted at `/run/atrustd`, on the host `~/.atrust-data/run`), so a restart
normally needs no login at all - the client resumes its session and the supervisor keeps its last
state.

## Configuration

All configuration is environment-only (Quadlet `Environment=` / `EnvironmentFile=`):

| Variable | Default | Meaning |
|---|---|---|
| `ATRUST_PORTAL_URL` | – (required) | portal, e.g. `https://vpn.example.com/` |
| `ATRUST_USERNAME` | – (required) | account name (the `@<domain>` suffix is added automatically) |
| `ATRUST_PASSWORD` / `ATRUST_PASSWORD_FILE` | – (required) | password, or a file containing it |
| `ATRUST_PROBE_TARGET` | empty | comma separated `host:port` inside the VPN used to prove the tunnel carries traffic - give it an HTTP endpoint: the probe sends a real request, which is also what keeps the portal's session from expiring (an `https` target is probed with `CONNECT` and does not count as activity) |
| `ATRUST_WATCH_INTERVAL` | `90` | seconds between supervision cycles |
| `ATRUST_VNC_WAIT` | `900` | how long to wait for a human in VNC before retrying |
| `ATRUST_STATE_DIR` | `/run/atrustd` | where `state.json`, `NEED_VNC` and the captcha image are written |
| `ATRUST_CLIENT_COOKIE_DB` | `/root/.aTrust/AppCache/Cookies` | the client's own cookie store |
| `ATRUST_CLIENT_ADDR_CONF` | `/usr/share/sangfor/.aTrust/var/conf/addr.conf` | the client's own portal address (seeded before it starts) |
| `ATRUST_CLIENT_LOG_DIR` | `/root/.aTrust/logs` | the client's log, read to tell a captcha request from a failed login |
| `ATRUST_DISPLAY` | `:1` | X display of the client's window (the image runs tigervnc on `:1`) |
| `ATRUST_PROXY` | `127.0.0.1:8888` | HTTP proxy used by the data-plane probe |
| `ATRUST_TUN` | `utun7` | tunnel interface created by the client |
| `ATRUST_DEVICE_ID` | empty | optional device id sent as `x-sdp-env`, keep it stable per container |
| `PASSWORD` | `password` | VNC password of the container's desktop |
| `VNC_SIZE` | `1110x620` | desktop geometry of the VNC session; the client's own window is pinned by the supervisor, so this only changes the space around it |

## Operating it

```bash
podman exec atrust python3 -m atrustd --status      # JSON: last state, attempts, detail
podman exec atrust python3 -m atrustd --once        # one supervision cycle
podman exec atrust python3 -m atrustd --login-probe # only test the portal login
podman exec atrust python3 -m atrustd --apps        # the apps this account may launch
podman exec atrust ls /run/atrustd                  # NEED_VNC hint + captcha image, if any
```

`--apps` prints what the client's own "App Details" panel shows - the launch method and the URL of
every app the portal grants this account (e.g. a "Default Browser" app is reachable from the host
through the container's proxies). It reads the copy the last login published; `--apps --refresh`
logs in again to update it (that creates a new session, so the supervisor logs the client back in
right after).

Open that URL in the browser through `127.0.0.1:8888` (HTTP) or `127.0.0.1:1080` (SOCKS5); an
extension such as Zero Omega can send that URL alone through the container, everything else direct.

`systemctl --user stop atrust` (and `restart`) is quick and clean: `atrustd` sweeps the client on
SIGTERM - the agent, the tunnel, the trays - SIGKILLs what does not leave on its own, and then
exits, so the container is down in about two seconds instead of waiting out podman's stop timeout.
`podman exec atrust kill -TERM 1` does the same thing by hand.

When the state is `NEED_VNC`, `ATRUST_STATE_DIR` holds the hint (`NEED_VNC`) and the captcha image
the portal is serving (`captcha.png`, or `captcha.jpg` - the portal picks the format), and the same
instructions are in the journal. Finish the login in the VNC desktop; the supervisor notices the
tunnel coming up and goes back to `ONLINE` on its own.

## Desktop notifications (optional)

`quadlet/atrust-notify.sh` mirrors the supervisor's states to the desktop: `NEED_VNC` as a critical
notification carrying the hint and the captcha image, `DEGRADED` / `LOGGED_OUT` with the probe
detail, and the recovery to `ONLINE` - exactly one notification per transition. It reads the state
directory that `quadlet/atrust.container` mounts at `~/.atrust-data/run` (falling back to
`podman cp` when the mount is missing, i.e. on an older container unit) and writes only its own
marker and temporaries - never into the container's state. Skip it and nothing changes, and the
container, the supervisor and the client never learn it exists. Install (Quadlet ignores `.timer`
files, so these two go into the systemd user directory, not `~/.config/containers/systemd/`; the
container unit has to be the current one - re-copy it, `install -d ~/.atrust-data/run` and restart
`atrust.service` if you installed it earlier):

```bash
install -m755 quadlet/atrust-notify.sh ~/.local/bin/
install -m644 quadlet/atrust-notify.service quadlet/atrust-notify.timer ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now atrust-notify.timer
```

The timer polls every 15 s and the marker keeps that to one notification per transition; the first
run after install seeds it silently, except when the tunnel is already waiting for a human.
`NEED_VNC` is critical and the tunnel changes are normal; classes can be muted in a drop-in
(`systemctl --user edit atrust-notify.service`):

```ini
[Service]
Environment=ATRUST_NOTIFY_MUTE=ONLINE,DEGRADED
```

`ATRUST_NOTIFY_MUTE` takes `NEED_VNC`, `DEGRADED`, `LOGGED_OUT` and `ONLINE` in any case; a muted
class still moves the marker, so it neither rings nor delays a later unmuted class.

Complete removal - nothing else depends on it:

```bash
systemctl --user disable --now atrust-notify.timer
rm -f ~/.local/bin/atrust-notify.sh ~/.config/systemd/user/atrust-notify.service \
      ~/.config/systemd/user/atrust-notify.timer "$XDG_RUNTIME_DIR/atrust-notify.last"
systemctl --user daemon-reload
```

## Documentation

| | |
|---|---|
| [`docs/DESIGN.md`](docs/DESIGN.md) | how it works: the portal protocol, the client's own window, the supervisor |
| [`docs/plans/`](docs/plans/) | the live plan: one file per step, its progress inside the file |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | the direction and what the project deliberately does not do |
| [`docs/archive/`](docs/archive/) | the retired records: the milestone log to 2026-10-10 and the item roadmap it came from |

## License

GPL-3.0-or-later, see `LICENSES/GPL-3.0-or-later.txt`. This project is [REUSE](https://reuse.software/)
compliant: every file carries `SPDX-FileCopyrightText` / `SPDX-License-Identifier` tags
(`reuse lint`).
