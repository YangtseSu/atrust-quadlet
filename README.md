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
| The client's own window is driven for you | portal address, account, password and agreement are filled and submitted with X level input (the address only when the client does not already know it - a recreated container seeds it back), so the client accepts the session |
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

Old versions of the package are pruned by hand from `.github/workflows/prune-packages.yml`, the only
consumer of the repository's `PACKAGES_TOKEN` secret (a PAT with `read:packages` + `delete:packages`).

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
| `ATRUST_PROBE_TARGET` | empty | comma separated `host:port` inside the VPN used to prove the tunnel carries traffic - give it an HTTP endpoint: the probe sends a real request, which is also what keeps the portal's session from expiring (an `https` target is probed with `CONNECT` and does not count as activity). It is a *witness*: with `ATRUST_PROBE_DISCOVER` on, the addresses the tunnel itself routes are asked beside it, and the tunnel is `ONLINE` as long as one witness answers - the state detail names the one that did |
| `ATRUST_PROBE_DISCOVER` | `1` | with `ATRUST_PROBE_TARGET` empty: find the witness yourself, from the addresses the tunnel's own route table carries one by one (each asked once on a short leash, the first that answers becomes the witness). `0` asks nothing at all and leaves the interface and its routes as the proof - for a deployment whose routed hosts come and go, or one that wants no traffic sent through the tunnel. With `0` *and* no target nothing keeps the portal's session alive either: a session whose tunnel only carried bare `CONNECT`s was measured expired after ~10.3 minutes, against over an hour with real requests - so the daemon warns about that combination once at start |
| `ATRUST_WATCH_INTERVAL` | `90` | seconds between supervision cycles; a client-side transition (the session ending, the tunnel coming back) wakes the next cycle earlier |
| `ATRUST_VNC_WAIT` | `900` | how long to wait for a human in VNC before retrying |
| `ATRUST_STATE_DIR` | `/run/atrustd` | where `state.json`, `NEED_VNC`, the captcha image and `device-id` are written |
| `ATRUST_CLIENT_COOKIE_DB` | `/root/.aTrust/AppCache/Cookies` | the client's own cookie store |
| `ATRUST_CLIENT_ADDR_CONF` | `/usr/share/sangfor/.aTrust/var/conf/addr.conf` | the client's own portal address (seeded before it starts) |
| `ATRUST_CLIENT_LOG_DIR` | `/root/.aTrust/logs` | the client's log, read to tell a captcha request from a failed login |
| `ATRUST_CLIENT_API_PORT_FILE` | `/usr/share/sangfor/.aTrust/var/run/httpserver` | the client's own run file holding the port of its loopback API, where the client's state is read |
| `ATRUST_CLIENT_API` | `1` | the client's own loopback interface: the state read beside every transition, the event channel that can wake a cycle early, and the login by ticket. `0` turns all three off and leaves the data-plane supervisor (the interface is measured, not documented, so a client bump can move it) |
| `ATRUST_DISPLAY` | `:1` | X display of the client's window (the image runs tigervnc on `:1`) |
| `ATRUST_PROXY` | `127.0.0.1:8888` | HTTP proxy used by the data-plane probe |
| `ATRUST_TUN` | `utun7` | tunnel interface created by the client |
| `ATRUST_DEVICE_ID` | empty | device id sent as `x-sdp-env`; empty keeps the one `atrustd` generates in `$ATRUST_STATE_DIR/device-id`, see below |
| `ATRUST_TOTP_KEY` | empty | the base32 secret behind the portal's TOTP second factor, if the deployment asks for one: `atrustd --totp` prints codes from it for the human to type into the VNC session, and the `NEED_VNC` hint then names the command without `-e`; nothing is submitted automatically |
| `PASSWORD` | `password` | VNC password of the container's desktop |
| `VNC_SIZE` | `1110x620` | desktop geometry of the VNC session; the client's own window is pinned by the supervisor, so this only changes the space around it |

The container runs under the host's hostname (`HostName=%H` in the Quadlet unit): the client reports
the system hostname to the portal and the portal's terminal list shows it, while podman's default -
the container ID - would add another hex name to that list on every recreation; the names earlier
logins left there stay until they are removed in the portal. Give the container a
name of its own with a `[Container]` override in
`~/.config/containers/systemd/atrust.container.d/10-hostname.conf` (`HostName=<name>`) plus a
`systemctl --user daemon-reload`.

A changed `ATRUST_PORTAL_URL` needs `systemctl --user restart atrust`, and nothing else: the unit's
stop removes the container (Quadlet generates `ExecStop=podman rm -f`), the next start builds a fresh
one, and `atrustd` seeds the new address into the client's own config before the client starts, so
the window opens on the new portal (measured 2026-10-13: a container created after its predecessor
had written the old address loaded the client's saved-address store with 0 entries, the window's own
`defaultSdpcAddr` and its store then carried the seeded address, and the tunnel stayed down against
the address nothing answers). What the restart keeps is the mounted profile in `~/.atrust-data` -
the client's cookies and logs, and the supervisor's state directory - which is what lets a restart
skip the captcha. `podman restart atrust` by hand is *not* that: it keeps the container, and with it
the layer the client's saved address lives in and the engine's own environment as it was at creation,
so the address only moves with a `systemctl --user restart atrust` (or a `podman rm -f` first).

The device id the supervisor reports as `x-sdp-env` is the deployment's own: `ATRUST_DEVICE_ID` if
set, otherwise one it generates on first use and keeps in `$ATRUST_STATE_DIR/device-id`. Setting
your own is the recommendation - the image ships a single `/etc/machine-id` that every container
built from it shares (and every rebuild replaces), so an id derived from it is neither unique per
deployment nor stable, and `quadlet/atrust.env.example` carries a command that generates one.

That is the *supervisor's* identity. The *client's* own - the `sdpcguid` it reports, which the
portal's terminal list is built from - is derived by the client at runtime (a container with nothing
running has no guid anywhere in its filesystem) and, measured 2026-10-11, **every container of the
image on one host reports the same one**: two containers of the image on the same host, different
accounts, different state directories, different `x-sdp-env` values, one guid. What it derives it
from is not pinned; the containers share the image's machine id and the host's hardware address.
So a portal that binds a "trust this terminal" grant to that guid would see a container rebuilt
from the same image on the same host as the terminal it was granted to - that binding is an
inference, not measured here (no portal on this deployment grants one). The sharing itself is
measured, and it is the part to expect.

## Operating it

```bash
podman exec atrust python3 -m atrustd --status      # JSON: last state, attempts, detail
podman exec atrust python3 -m atrustd --once        # one supervision cycle
podman exec atrust python3 -m atrustd --login-probe # only test the portal login
podman exec atrust python3 -m atrustd --apps        # the apps this account may launch
podman exec atrust python3 -m atrustd --bundle      # one tarball of evidence, into the state dir
podman exec atrust ls /run/atrustd                  # NEED_VNC hint + captcha image, if any
podman exec -e ATRUST_TOTP_KEY=<secret> atrust python3 -m atrustd --totp   # a second-factor code
```

A second factor (TOTP, SMS, a QR enrolment, a terminal approval) is never driven by this project: the
session is handed over to the VNC desktop and the hint says why. When that factor is TOTP, `--totp`
prints the current code from the shared secret the portal showed at enrolment - `ATRUST_TOTP_KEY`,
which belongs in `~/.config/atrust.env` beside the password, and the hint then names the command
without `-e`. Nothing is submitted for you, and `--totp` needs no other configuration.

`--apps` prints what the client's own "App Details" panel shows - the launch method and the URL of
every app the portal grants this account (e.g. a "Default Browser" app is reachable from the host
through the container's proxies). It reads the copy the last login published; `--apps --refresh`
logs in again to update it (that creates a new session, so the supervisor logs the client back in
right after).

`--bundle` is what a client bump or a bug report should be read with: one timestamped tarball (0600)
it writes into `ATRUST_STATE_DIR` - on the host `~/.atrust-data/run` - holding the state file, the
`NEED_VNC` hint and its captcha when one is pending, the tunnel's own route table, the client's own
status answer, the address the client carries, the tail of the client's own log (256 KiB of the
newest `aTrustTray*.log`, not the directory: the profile grows ~0.2 GB/day), and the versions - the
client image's `/etc/atrust-version`, the version the running client reports, and the base image the
app image was built from (the image records it; an older image says "not recorded"). It carries no
credential by construction: `device-id`, the client's cookie store and every token stay out, and the
manifest inside the tarball names which member was not there and why - a bundle from a healthy
container has no hint and no captcha in it. With `ATRUST_CLIENT_API=0` the client's own read is
skipped too, as that switch promises.

Open that URL in the browser through `127.0.0.1:8888` (HTTP) or `127.0.0.1:1080` (SOCKS5); an
extension such as Zero Omega can send that URL alone through the container, everything else direct.

If the *host* runs a proxy of its own in TUN mode (Clash, Mihomo and friends), it captures this
container's traffic too, because that traffic leaves through the host's own stack. The portal host
and the intranet ranges then belong on that proxy's **direct** list: the client's own login and the
stream it tunnels through (the gateway, often one of those ranges) are ordinary traffic on that
stack, and a rule that hands them to a proxy node breaks the login - or, when the node is this
container's own proxy (`127.0.0.1:8888`/`1080`), sends the packet back into the client, which
encapsulates it and sends it again, a loop. Pointing the ranges at the container's proxies instead
works too, if host apps should reach the intranet without a per-app proxy setting, but then the
client's own peers must stay off that rule: [`EZ4Connect`](https://github.com/chenx-dust/EZ4Connect/blob/c56e1673efa1c3c41f18c51092a05d9e7d8298a0/docs/ADVANCED_USAGE.md)
does exactly that on its own host (auth and aTrust domains direct, its own process excluded from the
TUN), and [`zju-connect`](https://github.com/Mythologyli/zju-connect/blob/c19eb4ed34b9cf6e8e8ea3315fe9973c8411eb63/docs/service.md)
keeps the RVPN servers direct and the campus range in its own proxy - a container has no process for
the TUN to exclude, so *direct* is the shape to start from.

`systemctl --user stop atrust` (and `restart`) is quick and clean: `atrustd` sweeps the client on
SIGTERM - the agent, the tunnel, the trays - SIGKILLs what does not leave on its own, and then
exits, so the container is down in about two seconds instead of waiting out podman's stop timeout.
`podman exec atrust kill -TERM 1` does the same thing by hand.

A `start` does not wait for the network: the unit drops Quadlet's implicit
`podman-user-wait-network-online.service` dependency, whose poll of the *system*
`network-online.target` burns its full 90 s on a host where nothing pulls that target in - saying
nothing about the link either way. The supervisor carries a start that finds no network, and a start
that cannot succeed yet (a first run with no image, a pull with no registry) keeps retrying every
15 s instead of ending `failed`. One case stays yours: if the host has no usable address when the
container starts - a login before the link is up - the container comes up without a route out, and
`systemctl --user restart atrust` once the network is there rebuilds the sandbox.

When the state is `NEED_VNC`, `ATRUST_STATE_DIR` holds the hint (`NEED_VNC`) and the captcha image
the portal is serving (`captcha.png`, or `captcha.jpg` - the portal picks the format), and the same
instructions are in the journal. Finish the login in the VNC desktop; the supervisor notices the
tunnel coming up and goes back to `ONLINE` on its own.

One `NEED_VNC` needs no VNC: a hint that names a refused password (`wrong-password`) or a lockout
(`rate-limited`). The portal counts the login attempts it checks and prints how many are left, so the
supervisor stops trying - no login, no window submit - until the tunnel is up or the service
restarts. Correct `ATRUST_PASSWORD` in `~/.config/atrust.env` and restart the service (a restart
re-reads the file and clears the hold); `podman exec atrust python3 -m atrustd --login-probe` tests
the credential once by hand, and costs one of the account's attempts, which is why nothing runs it
for you.

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
