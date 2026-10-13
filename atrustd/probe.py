# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Data-plane probes: is the tunnel actually up and usable?

The aTrust client is the authority on the VPN session, so atrustd never guesses
from a web session alone. It checks, from cheapest to strongest:

1. the tunnel interface exists and carries an address,
2. the client installed routes pointing at that interface,
3. traffic actually reaches an intranet address, via the container's HTTP proxy. For a plain HTTP
   target the probe sends a real request, because that is also what keeps the portal's session
   alive: a session whose tunnel only carried bare CONNECTs was expired after ~10 minutes of
   quiet (10.3 minutes, measured 2026-10-09), while the same cadence with real requests held it
   for over an hour.

The addresses of step 3 are *witnesses*: the ones a human configured (`ATRUST_PROBE_TARGET`) and,
when none is, the addresses the tunnel itself routes one by one - its own route table, which needs no
portal session and no client interface (a deployment whose portal demands the graphical captcha never
lets the engine log in, and the routes exist either way). A witness is asked once per round on a short
leash, and the first that answers decides the check: an address is a witness for the tunnel, not the
tunnel, so one that cannot answer never stops the cycle while another one answers.

Step 3 is retried: the client's userspace netstack drops the occasional
connection of its own accord (its lookup of the source socket fails and xtunnel
logs ``find pid err``), which leaves the proxy waiting for a far side that never
answers while the tunnel itself carries traffic. A single attempt is therefore
not evidence of an outage.
"""
from __future__ import annotations

import logging
import socket
import subprocess
import time
from dataclasses import dataclass

log = logging.getLogger('atrustd.probe')

# Attempts of the proxy probe (and the pause between them) before the tunnel is
# called unusable: a transient netstack drop must not restart the client.
PROBE_ATTEMPTS = 3
PROBE_RETRY_DELAY = 2.0

# What one witness is given. An address a human named keeps the 8 s the probe has
# always used - a slow-but-alive intranet server must not lose its witness because
# a search pass was impatient. A candidate off the tunnel's own routes is a search,
# so it is asked on a 3 s leash (the accept/reject budget the host-side keepalive
# script uses for its own discovery and its down-state cross-check). Measured live
# 2026-10-13 in the dev container: the resource address of that deployment answers
# through the proxy in 0.03 s, while a bare route of the client's own virtual range
# (198.18.255.1) never answers at all - it times out at the full 8 s, which is why
# the leash, and not the candidate, is what bounds a search. DISCOVERY_MAX bounds
# the number of candidates: the route table is the client's, and a check must not
# grow with it.
PROBE_TIMEOUT = 8.0
DISCOVERY_TIMEOUT = 3.0
DISCOVERY_MAX = 4


def _run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return 255, str(exc)


@dataclass(frozen=True)
class Witness:
    """One address the probe may ask, and what asking it costs.

    ``source`` is where the address came from - the target a human configured
    (``target``) or the tunnel's own route table (``route``) - and it is what the
    success detail carries, so the state file says which witness answered.
    """

    host: str
    port: int
    timeout: float = PROBE_TIMEOUT
    source: str = 'target'


@dataclass
class ProbeResult:
    tun_up: bool
    routes: bool
    proxy_ok: bool
    probes_configured: bool = False
    detail: str = ''

    @property
    def online(self) -> bool:
        """Tunnel up + routes installed is enough; with a witness to ask, the
        data plane must also carry traffic."""
        if not (self.tun_up and self.routes):
            return False
        return self.proxy_ok if self.probes_configured else True


def tun_state(tun: str) -> tuple[bool, str]:
    rc, out = _run(['ip', '-brief', 'addr', 'show', tun])
    if rc != 0:
        return False, 'no %s: %s' % (tun, out.strip()[:120])
    fields = out.split()
    addr = fields[2] if len(fields) > 2 else ''
    return bool(addr), '%s %s' % (tun, addr or '(no address)')


def route_lines(tun: str) -> tuple[list[str], str]:
    """The tunnel's own route table, one entry per line, and its summary detail."""
    rc, out = _run(['ip', 'route', 'show', 'dev', tun])
    lines = [l for l in out.splitlines() if l.strip()] if rc == 0 else []
    return lines, '%d route(s) via %s' % (len(lines), tun)


def _host_addresses(lines: list[str]) -> list[str]:
    """The host routes of `ip route show dev <tun>`: what the tunnel carries one by one.

    A bare address (or an explicit ``/32``) is a host route; everything else in that
    table is a subnet of the client's own carve-up - its virtual range is listed as
    /31 ... /24 entries, and its bare addresses never answer (measured: a request to
    one of them times out at the full probe timeout). IPv6 is left out on purpose:
    the request is built as ``http://<host>:<port>/``, which needs a literal that can
    be put there.
    """
    out: list[str] = []
    for line in lines:
        fields = line.split()
        if not fields:
            continue
        first = fields[0]
        if first.endswith('/32'):
            first = first[:-3]
        octets = first.split('.')
        if len(octets) != 4 or not all(o.isdigit() and int(o) < 256 for o in octets):
            continue
        if first not in out:
            out.append(first)
    return out


def witnesses_for(targets: list[tuple[str, int]], lines: list[str],
                  discover: bool = False) -> list[Witness]:
    """What a check asks: the targets a human named first, then the tunnel's own routes.

    The configured ones lead so that a healthy deployment asks exactly one address per
    cycle, as it always has; the discovered ones are appended for the same round, which
    is what keeps an unreachable configured target from deciding the check while the
    tunnel plainly carries traffic to something else.
    """
    out = [Witness(host, port) for host, port in targets]
    if not discover:
        return out
    seen = {(w.host, w.port) for w in out}
    for addr in _host_addresses(lines)[:DISCOVERY_MAX]:
        if (addr, 80) not in seen:
            seen.add((addr, 80))
            out.append(Witness(addr, 80, DISCOVERY_TIMEOUT, 'route'))
    return out


def _proxy_connect_once(proxy: str, target: str, port: int, timeout: float) -> tuple[bool, str]:
    """A bare CONNECT through the container proxy: touches the far side of the tunnel."""
    host, _, pport = proxy.partition(':')
    try:
        with socket.create_connection((host, int(pport)), timeout=timeout) as s:
            s.settimeout(timeout)
            req = 'CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n\r\n' % (target, port, target, port)
            s.sendall(req.encode())
            data = s.recv(128).decode('latin-1', 'replace')
            ok = data.startswith('HTTP/') and (' 200' in data.split('\r\n', 1)[0])
            return ok, data.split('\r\n', 1)[0].strip()
    except OSError as exc:
        return False, 'proxy %s -> %s:%d failed: %s' % (proxy, target, port, exc)


def _proxy_get_once(proxy: str, target: str, port: int, timeout: float) -> tuple[bool, str]:
    """A real HTTP request through the container proxy, addressed to the target.

    A bare CONNECT does not count as activity for the portal: a session whose
    tunnel only carried CONNECTs was expired after ~10 minutes of quiet, while
    the same cadence with real requests kept it alive for over an hour (measured
    2026-10-09). This is also the probe: the answer comes from the far side.
    """
    host, _, pport = proxy.partition(':')
    try:
        with socket.create_connection((host, int(pport)), timeout=timeout) as s:
            s.settimeout(timeout)
            req = ('GET http://%s:%d/ HTTP/1.1\r\nHost: %s:%d\r\nUser-Agent: atrustd\r\n'
                   'Connection: close\r\n\r\n') % (target, port, target, port)
            s.sendall(req.encode())
            data = s.recv(256).decode('latin-1', 'replace')
            status = data.split('\r\n', 1)[0].strip()
            if not data.startswith('HTTP/'):
                return False, 'proxy %s -> %s:%d: not an HTTP answer (%s)' % (proxy, target, port,
                                                                              status[:60] or 'empty')
            code = status.split(' ')[1] if len(status.split(' ')) > 1 else ''
            # 502/503/504 are the proxy's own failures, not the far side answering.
            ok = code not in ('502', '503', '504')
            return ok, status
    except OSError as exc:
        return False, 'proxy %s -> %s:%d failed: %s' % (proxy, target, port, exc)


def _proxy_probe_once(proxy: str, target: str, port: int, timeout: float) -> tuple[bool, str]:
    """One probe attempt: a real request for a plain HTTP target, CONNECT for the rest.

    An HTTPS target must not be sent a plain request, and there the probe stays a
    CONNECT - which means it does not keep the session alive either.
    """
    if port == 443:
        return _proxy_connect_once(proxy, target, port, timeout)
    return _proxy_get_once(proxy, target, port, timeout)


def _asked(failures: list[tuple[str, int, str]]) -> str:
    return ', '.join('%s:%d' % (host, port) for host, port, _ in failures)


def _answered(witness: Witness, status: str, failures: list[tuple[str, int, str]]) -> str:
    """The success detail: which witness answered, and what answered before it did not."""
    where = '' if witness.source == 'target' else ', %s' % witness.source
    if not failures:
        return 'probe %s:%d ok (%s%s)' % (witness.host, witness.port, status, where)
    return 'no answer from %s; probe %s:%d ok (%s%s)' % (_asked(failures), witness.host,
                                                         witness.port, status, where)


def probe_witnesses(proxy: str, witnesses: list[Witness],
                    attempts: int = PROBE_ATTEMPTS) -> tuple[bool, str]:
    """Ask the witnesses, each once per round, the first answer wins.

    A single witness keeps the retry budget that exists for the client's own netstack
    drops (`PROBE_ATTEMPTS` tries, `PROBE_RETRY_DELAY` apart). Several are asked
    round-robin instead, so a live one is found before a dead one has eaten the whole
    budget - and a witness that cannot answer never decides the check while another
    answers.
    """
    failures: list[tuple[str, int, str]] = []
    for attempt in range(1, attempts + 1):
        earlier, failures = failures, []
        for witness in witnesses:
            ok, msg = _proxy_probe_once(proxy, witness.host, witness.port, witness.timeout)
            if ok:
                if attempt > 1:
                    log.warning('probe %s:%d came back on attempt %d/%d (earlier: %s)',
                                witness.host, witness.port, attempt, attempts,
                                '; '.join('%s:%d %s' % f for f in (failures or earlier)))
                return True, _answered(witness, msg, failures)
            failures.append((witness.host, witness.port, msg))
        if attempt < attempts:
            log.info('probe: nothing answered in round %d/%d (%s), retrying in %.0fs',
                     attempt, attempts, '; '.join('%s:%d %s' % f for f in failures),
                     PROBE_RETRY_DELAY)
            time.sleep(PROBE_RETRY_DELAY)
    last = failures[-1][2] if failures else 'nothing to probe'
    if len(witnesses) == 1:
        return False, '%s (failed all %d attempts)' % (last, attempts)
    return False, 'no witness answered (%s); last: %s' % (_asked(failures), last)


def check(tun: str, proxy: str, targets: list[tuple[str, int]],
          discover: bool = False) -> ProbeResult:
    """The data plane's verdict: interface, routes, and a real request.

    ``targets`` are the witnesses a human configured; with ``discover`` the tunnel's
    own route table is asked for more, so a deployment needs no intranet address of
    its own. The first witness that answers decides the check; with none configured
    and none discoverable, the interface and its routes are the proof, exactly as
    they were before discovery existed.
    """
    tun_up, tun_detail = tun_state(tun)
    lines, route_detail = route_lines(tun)
    routes = bool(lines)
    detail = '%s; %s' % (tun_detail, route_detail)
    witnesses = witnesses_for(targets, lines, discover)
    if not witnesses:
        return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=False,
                           probes_configured=False, detail=detail)
    if not (tun_up and routes):
        # A dead datapath already decides the result; probing it would only add
        # the retry budget to every cycle.
        return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=False, probes_configured=True,
                           detail='%s; not probed, no datapath yet' % detail)
    ok, msg = probe_witnesses(proxy, witnesses)
    return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=ok, probes_configured=True,
                       detail='%s; %s' % (detail, msg))
