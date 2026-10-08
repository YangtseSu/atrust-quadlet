# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Data-plane probes: is the tunnel actually up and usable?

The aTrust client is the authority on the VPN session, so atrustd never guesses
from a web session alone. It checks, from cheapest to strongest:

1. the tunnel interface exists and carries an address,
2. the client installed routes pointing at that interface,
3. traffic actually reaches an intranet target, via the container's HTTP proxy.
"""
from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass


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
    detail: str = ''

    @property
    def online(self) -> bool:
        if not (self.tun_up and self.routes):
            return False
        return self.proxy_ok if self.detail else True


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


def proxy_probe(proxy: str, target: str, port: int, timeout: float = 8.0) -> tuple[bool, str]:
    """HTTP CONNECT through the container proxy: touches the far side of the tunnel."""
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


def check(tun: str, proxy: str, targets: list[tuple[str, int]]) -> ProbeResult:
    tun_up, tun_detail = tun_state(tun)
    routes, route_detail = route_state(tun)
    detail = '%s; %s' % (tun_detail, route_detail)
    if not targets:
        return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=False, detail=detail)
    last = ''
    for host, port in targets:
        ok, msg = proxy_probe(proxy, host, port)
        if ok:
            return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=True,
                               detail='%s; probe %s:%d ok (%s)' % (detail, host, port, msg))
        last = msg
    return ProbeResult(tun_up=tun_up, routes=routes, proxy_ok=False, detail='%s; %s' % (detail, last))
