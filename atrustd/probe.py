# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Data-plane probes: is the tunnel actually up and usable?

The aTrust client is the authority on the VPN session, so atrustd never guesses
from a web session alone. It checks, from cheapest to strongest:

1. the tunnel interface exists and carries an address,
2. the client installed routes pointing at that interface,
3. traffic actually reaches an intranet target, via the container's HTTP proxy. For a plain HTTP
   target the probe sends a real request, because that is also what keeps the portal's session
   alive: a session whose tunnel only carried bare CONNECTs was expired after ~10 minutes of
   quiet (10.3 minutes, measured 2026-10-09), while the same cadence with real requests held it
   for over an hour.

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


def _run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return 255, str(exc)


@dataclass
class ProbeResult:
    tun_up: bool
    routes: bool
    proxy_ok: bool
    probes_configured: bool = False
    detail: str = ''

    @property
    def online(self) -> bool:
        """Tunnel up + routes installed is enough; with targets configured the
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


def route_state(tun: str) -> tuple[bool, str]:
    rc, out = _run(['ip', 'route', 'show', 'dev', tun])
    lines = [l for l in out.splitlines() if l.strip()] if rc == 0 else []
    return bool(lines), '%d route(s) via %s' % (len(lines), tun)


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


def proxy_probe(proxy: str, target: str, port: int, timeout: float = 8.0,
                attempts: int = PROBE_ATTEMPTS) -> tuple[bool, str]:
    """The proxy probe, retried: only a probe that fails every attempt counts."""
    last = ''
    for attempt in range(1, attempts + 1):
        ok, msg = _proxy_probe_once(proxy, target, port, timeout)
        if ok:
            if attempt > 1:
                log.warning('probe %s:%d came back on attempt %d/%d (earlier: %s)',
                            target, port, attempt, attempts, last)
            return True, msg
        last = msg
        if attempt < attempts:
            log.info('probe %s:%d attempt %d/%d failed (%s), retrying in %.0fs',
                     target, port, attempt, attempts, msg, PROBE_RETRY_DELAY)
            time.sleep(PROBE_RETRY_DELAY)
    return False, '%s (failed all %d attempts)' % (last, attempts)


def check(tun: str, proxy: str, targets: list[tuple[str, int]]) -> ProbeResult:
    tun_up, tun_detail = tun_state(tun)
    routes, route_detail = route_state(tun)
    detail = '%s; %s' % (tun_detail, route_detail)
    if not targets:
        return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=False,
                           probes_configured=False, detail=detail)
    if not (tun_up and routes):
        # A dead datapath already decides the result; probing it would only add
        # the retry budget to every cycle.
        return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=False, probes_configured=True,
                           detail='%s; not probed, no datapath yet' % detail)
    last = ''
    for host, port in targets:
        ok, msg = proxy_probe(proxy, host, port)
        if ok:
            return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=True, probes_configured=True,
                               detail='%s; probe %s:%d ok (%s)' % (detail, host, port, msg))
        last = msg
    return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=False, probes_configured=True,
                       detail='%s; %s' % (detail, last))
