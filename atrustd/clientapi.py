# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The client's own view, read from its loopback HTTPS service.

`aTrustAgent` serves a private HTTPS API on loopback - the channel its own
workbench and the vendor's CSSDK drive it through - and `POST /v1/service/status`
answers with the client's own user state, tunnel state, user name and login time.
The supervisor's decision stays the data plane (`probe.check`): the client can
report `tunnelAvailable` while its netstack drops traffic, which is exactly why
that probe exists. What this module adds is the fields the data plane cannot see -
who is logged in, since when, and whether the client believes it is online at all.

Measured live on client 2.5.16.30 inside this project's container; the route
shapes, both gates and the port drift are recorded in `docs/CLIENT-LOCAL-API.md`.
"""
from __future__ import annotations

import json
import logging
import random
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger('atrustd.clientapi')

# The client's own listener ports: the default moves +11 when a port is taken
# (`BACKUP_PORT1..4` in the client's web assets; 54630 is the one measured live
# inside the image). Discovery never assumes one of these - it reads the client's
# run file first and falls back to the sequence.
DEFAULT_PORT = 54630
PORT_STEP = 11
PORT_CANDIDATES = tuple(DEFAULT_PORT + PORT_STEP * step for step in range(3))

# One status read is one loopback request; the bounds keep a wedged agent from
# holding a cycle, while a refused connect on loopback comes back immediately.
REQUEST_TIMEOUT = 3.0
CONNECT_TIMEOUT = 0.5

USER_AGENT = 'atrustd (atrust-quadlet)'


def read_port(path: Path) -> int | None:
    """The port the client wrote to its run file, or None when it is unusable."""
    try:
        raw = path.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    port = int(raw)
    return port if 0 < port < 65536 else None


def _listening(port: int, timeout: float) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except OSError:
        return False


def _short(payload, limit: int = 120) -> str:
    try:
        text = json.dumps(payload) if not isinstance(payload, str) else payload
    except (TypeError, ValueError):
        text = str(payload)
    return text if len(text) <= limit else text[:limit] + '...'


class ClientAPIError(Exception):
    """The client's service could not be reached, or answered nothing parseable."""


@dataclass
class ClientStatus:
    """The client's own view of its session, as `/v1/service/status` reports it.

    `state` is the client's user state (`online`, `offline`, `disconnect`,
    `logout`, `otherSdpCLogin`, ...), `tunnel` its tunnel state
    (`tunnelAvailable`/`tunnelUnavailable`/`tunnelPreparing`); the values are the
    vocabulary the client's own workbench and the official CSSDK use. ``ok`` False
    means the client could not be asked or did not answer with a status object -
    ``detail`` carries the reason, because a cycle has to survive anything.
    """

    ok: bool = False
    code: int = -1
    message: str = ''
    state: str = ''
    tunnel: str = ''
    username: str = ''
    login_time: str = ''
    detail: str = ''

    def as_record(self) -> dict[str, str]:
        """The short form ``state.json`` carries: the four fields, or the reason."""
        if not self.ok:
            return {'error': self.detail[:160]}
        return {
            'state': self.state,
            'tunnel': self.tunnel,
            'user': self.username,
            'login': self.login_time,
        }


class ClientAPI:
    """The client's local API: port discovery, the request envelope, a status read."""

    def __init__(self, cfg, timeout: float = REQUEST_TIMEOUT,
                 connect_timeout: float = CONNECT_TIMEOUT, scheme: str = 'https'):
        """``scheme`` is the test seam.

        The image's service is TLS on the client's own self-signed certificate,
        which every request skips verification for; a test can point the same
        client at a plain socket it owns instead, which is the only difference.
        """
        self.cfg = cfg
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.base = '%s://127.0.0.1' % scheme
        parts = urllib.parse.urlsplit(cfg.portal_url)
        self.addr = ('%s://%s' % (parts.scheme, parts.netloc)) if parts.netloc \
            else cfg.portal_url.rstrip('/')
        self.referer = self.addr + '/'
        if scheme == 'https':
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            self.opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),      # loopback is never proxied
                urllib.request.HTTPSHandler(context=context))
        else:
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        # Left empty for the status read - measured 2026-10-11: it answers with
        # the full state for an empty envelope guid. The routes that need a real
        # one (`/v1/service/start`) take the value the client reports as
        # `sdpcguid`; set it here when such a route is called.
        self.guid = ''

    def candidates(self) -> list[int]:
        """The ports to try, in order: the client's run file first, then the backups.

        The file is what the client itself reads back (`.../var/run/httpserver`);
        the candidates cover a file that is missing, malformed or stale. Nothing
        is assumed about 54630 being the one in use.
        """
        out: list[int] = []
        for port in ([read_port(self.cfg.client_api_port_file)] + list(PORT_CANDIDATES)):
            if port is not None and port not in out:
                out.append(port)
        return out

    def port(self) -> int | None:
        """The first candidate that answers, or None.

        Read fresh on every call: a client restart that moves its port is
        followed instead of being served from a cache.
        """
        for candidate in self.candidates():
            if _listening(candidate, self.connect_timeout):
                return candidate
        return None

    def envelope(self, data: dict | None = None) -> dict:
        """The request body the client's own workbench sends."""
        return {
            'addr': self.addr,
            'type': 'web',
            'guid': self.guid,
            'lang': self.cfg.lang,
            'token': '',
            'sdpTraceId': '%08x' % random.getrandbits(32),
            'data': data or {},
        }

    def session(self, path: str, data: dict | None = None) -> dict:
        """POST a gated route and return the parsed answer.

        Two gates sit in front of the routes (`docs/CLIENT-LOCAL-API.md`): the
        method (POST; GET answers 404/503) and the portal-origin `Referer` - the
        routes that change the session answer `403 {"code":11119003,...}` without
        it, and even `/v1/service/status` blanks `username`/`clientIp`. This
        helper sets the gate header, which is what the routes the client's own
        workbench drives (`/v1/service/online`, `/v1/service/logout`, ...) need;
        the tests pin the header against a socket of their own.

        Raises `ClientAPIError` on a transport failure or an unparseable answer;
        a business error is returned as the parsed body (the caller reads `code`).
        """
        port = self.port()
        if port is None:
            tried = ', '.join(str(candidate) for candidate in self.candidates())
            raise ClientAPIError('the client service is not listening (%s)' % tried)
        url = '%s:%d%s' % (self.base, port, path)
        body = json.dumps(self.envelope(data)).encode('utf-8')
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('User-Agent', USER_AGENT)
        req.add_header('Referer', self.referer)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                payload = resp.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as exc:
            # The gates answer with a JSON body (`403 {"code":11119003,...}`);
            # keeping it makes the failure a business error, not a lost answer.
            try:
                payload = exc.read().decode('utf-8', 'replace')
            finally:
                exc.close()
        except OSError as exc:
            raise ClientAPIError('%s failed: %s' % (path, exc)) from exc
        try:
            answer = json.loads(payload)
        except json.JSONDecodeError:
            raise ClientAPIError('%s returned non-JSON: %s' % (path, _short(payload))) from None
        if not isinstance(answer, dict):
            raise ClientAPIError('%s returned %s, not an object' % (path, type(answer).__name__))
        return answer

    def status(self) -> ClientStatus:
        """The client's own view; a failure is a value, never an exception.

        A cycle reads this beside the data plane and must survive any answer -
        including no answer at all - without the supervisor losing the cycle.
        """
        try:
            answer = self.session('/v1/service/status')
        except ClientAPIError as exc:
            log.debug('client status unavailable: %s', exc)
            return ClientStatus(ok=False, detail=str(exc))
        except Exception as exc:  # noqa: BLE001 - the cycle must survive anything
            log.debug('client status failed unexpectedly: %s', exc)
            return ClientStatus(ok=False, detail='%s: %s' % (type(exc).__name__, exc))
        code = answer.get('code')
        if not isinstance(code, int):
            return ClientStatus(ok=False, detail='unexpected answer: %s' % _short(answer))
        message = str(answer.get('message') or '')
        if code != 0:
            return ClientStatus(ok=False, code=code, message=message,
                                detail='code %d %s' % (code, message))
        data = answer.get('data')
        if not isinstance(data, dict):
            return ClientStatus(ok=False, code=code, message=message,
                                detail='no status object: %s' % _short(answer))
        inner = data.get('data')
        inner = inner if isinstance(inner, dict) else {}
        return ClientStatus(
            ok=True, code=code, message=message,
            state=str(data.get('status') or ''),
            tunnel=str(inner.get('tunnelStatus') or ''),
            username=str(inner.get('username') or ''),
            login_time=str(inner.get('loginTime') or ''),
        )
