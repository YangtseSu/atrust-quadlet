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

The same service publishes its own transitions on `/v1/service/events`, and
`EventPoller` long-polls it from a background thread so those transitions wake
the supervisor's waits - again a wake, never a decision. And it takes the ticket
that ends a logged-out state (`start`, the second half of the workbench's login
handshake; the portal half is `atrustd.portal.sid_ticket`), which is how a dead
session is recovered without the client's window.

Measured live on client 2.5.16.30 inside this project's container, and re-verified
unchanged on 2.5.16.41 (`docs/CLIENT-LOCAL-API.md` carries the spot check); the
route shapes, both gates and the port drift are recorded there. The answers the
agent refuses with by code are read as classes (`classify`), carried beside the
code on `ClientStatus`/`StartResult`.
"""
from __future__ import annotations

import json
import logging
import random
import socket
import ssl
import threading
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

# The client's own event channel (`/v1/service/events`): a long poll that holds
# the request for up to `timeout` ms and answers with whatever the client
# published. The request's own timeout has to outlive that hold - a request that
# gives up first reads as a dead agent and sends the poller into its backoff for
# nothing.
EVENT_TIMEOUT_MS = 2000
EVENT_REQUEST_TIMEOUT = REQUEST_TIMEOUT + EVENT_TIMEOUT_MS / 1000.0

# Reconnect after a failed poll. The agent's port reopens seconds after the
# supervisor's own restart of the client (measured ~2 s with the vendor's restart
# loop), so the first retry is quick; the cap bounds the traffic while the client
# is down for minutes.
EVENT_BACKOFF_BASE = 2.0
EVENT_BACKOFF_CAP = 30.0

# The events that can change the data plane: entering or leaving the client's
# own session and its online run, its status and tunnel views, and the core
# plugin's prefixed forms (`docs/CLIENT-LOCAL-API.md` lists the vocabulary as
# read out of the client and captured live). Everything else the channel carries
# is module chatter (`ready`, `resourceReady`, `beginConsult`/`endConsult`,
# `uemStatus*`, ...). Waking costs a probe cycle - two `ip` forks and a request
# through the proxy - so this set is the throttle: an event only moves onto it
# with a measurement that says it can change the data plane.
WAKE_EVENTS = frozenset({
    'login', 'logout', 'online', 'offline',
    'enterOnline', 'leaveOnline', 'enterOnlineRun', 'leaveOnlineRun',
    'enterInitial', 'leaveInitial', 'enterOffline', 'enterOnlineNetworkAnomaly',
    'networkReset', 'status', 'tunnelStatus',
    'statusEvent|logout', 'statusEvent|offline', 'statusEvent|networkReset',
})

USER_AGENT = 'atrustd (atrust-quadlet)'

# What `/v1/service/start` answers for a client that is already logged in: the workbench tolerates
# it as success whatever the ticket was (measured 2026-10-11, `docs/CLIENT-LOCAL-API.md`), and so
# does `start()` - the session the caller asked for is exactly the state this code reports.
CLIENT_ALREADY_LOGINED = 11119054

# The agent's answer codes, read as classes. They are a space of their own (no value is shared
# with the portal's) and the code is the stable half of an answer: the agent words the same
# refusal differently per route and language (`Query database failed` and `User not logged in`
# are both `11112002`, read out of its own HTTP-server log). The names are the vendor's own where
# it has one (`CLIENT_ALREADY_LOGINED` and `TICKET_INVALID` are enum members of its SPA), and the
# measured meanings otherwise: `10000001 invalid_param in body` for an empty `sidTicket`,
# `11119003` for the `Referer` gate's `403 {"code":11119003,"message":"Invalid request."}`, and
# `11119064`, which `/v1/service/proxy` answers for `{}`.
ALREADY_LOGGED_IN = 'already-logged-in'
CLIENT_CODE_CLASSES = {
    CLIENT_ALREADY_LOGINED: ALREADY_LOGGED_IN,
    75500304: 'stale-ticket',
    10000001: 'invalid-parameter',
    11119003: 'invalid-request',
    11112002: 'query-failed',
    11119064: 'proxy-failed',
}


def classify(code: int) -> str:
    """The class this project knows `code` by; '' for one it has not measured."""
    return CLIENT_CODE_CLASSES.get(code, '')


def answer_text(code: int, message: str = '') -> str:
    """`code=75500304 class=stale-ticket message=当前票据已失效`: the class beside the code.

    The form `detail` carries for the callers that log it or write it into the state file; an
    unmeasured code (and code 0) simply carries no class. The schema refusal - the route
    answering no `code` at all - is not one of these: it stays the string `unexpected answer`.
    """
    parts = ['code=%d' % code]
    answer_class = classify(code)
    if answer_class:
        parts.append('class=%s' % answer_class)
    return ' '.join(parts + ['message=%s' % message])


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
    ``detail`` carries the reason, because a cycle has to survive anything - and
    ``answer_class`` names a refusal the agent made by code (`invalid-request`,
    ...), '' when there was none or nobody has measured that code.
    """

    ok: bool = False
    code: int = -1
    message: str = ''
    answer_class: str = ''
    state: str = ''
    tunnel: str = ''
    username: str = ''
    login_time: str = ''
    guid: str = ''
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


@dataclass
class StartResult:
    """What ``/v1/service/start`` answered for the ticket, as a value.

    ``ok`` is the caller's question - "did the agent take the ticket and (re)establish the session?"
    - and it is True for `code 0` and for the already-logged-in answer alike (both mean the session
    the caller asked for exists). Every other answer - a business error, a missing object, a
    transport failure, a timeout - is ``ok`` False with the reason in ``detail``, so a cycle can
    fall back without exception handling around the call. ``answer_class`` names the answer's class
    beside the code (``already-logged-in`` for the tolerated one, ``stale-ticket`` for a ticket the
    agent rejected, ...), and '' for code 0 and for a code nobody has measured.
    """

    ok: bool = False
    code: int = -1
    message: str = ''
    answer_class: str = ''
    detail: str = ''


class ClientAPI:
    """The client's local API: port discovery, the envelope, a status read, a ticket handover."""

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
        # `sdpcguid`, which `status()` adopts below.
        self.guid = ''
        # Whether any read in this object's life has carried a guid. The ticket
        # path's way in waits for one only where a restart is the likely cause: a
        # tray that has published a guid before publishes it again within ~5 s of
        # its restart, while a client that has never published one - a container
        # that has just been recreated - takes 35 s+ (both measured live).
        self.seen_guid = False

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

    def session(self, path: str, data: dict | None = None,
                timeout: float | None = None) -> dict:
        """POST a gated route and return the parsed answer.

        Two gates sit in front of the routes (`docs/CLIENT-LOCAL-API.md`): the
        method (POST; GET answers 404/503) and the portal-origin `Referer` - the
        routes that change the session answer `403 {"code":11119003,...}` without
        it, and even `/v1/service/status` blanks `username`/`clientIp`. This
        helper sets the gate header, which is what the routes the client's own
        workbench drives (`/v1/service/online`, `/v1/service/logout`, ...) need;
        the tests pin the header against a socket of their own.

        ``timeout`` overrides the instance's own bound: the event channel's long
        poll holds a request for its whole ``timeout`` field, so it needs a
        request timeout that outlives that.

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
            with self.opener.open(req, timeout=self.timeout if timeout is None else timeout) as resp:
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
                                answer_class=classify(code), detail=answer_text(code, message))
        data = answer.get('data')
        if not isinstance(data, dict):
            return ClientStatus(ok=False, code=code, message=message,
                                detail='no status object: %s' % _short(answer))
        inner = data.get('data')
        inner = inner if isinstance(inner, dict) else {}
        view = ClientStatus(
            ok=True, code=code, message=message,
            state=str(data.get('status') or ''),
            tunnel=str(inner.get('tunnelStatus') or ''),
            username=str(inner.get('username') or ''),
            login_time=str(inner.get('loginTime') or ''),
            guid=str(inner.get('sdpcguid') or ''),
        )
        # One source for the envelope's guid and for the wait question above it:
        # a guid that has been published once is remembered, and an empty one
        # does not erase it - a logged-out client answers none, which is not a
        # reason to forget what the client looked like while it had a session.
        if view.guid:
            self.guid = view.guid
            self.seen_guid = True
        return view

    def start(self, ticket: str, timeout: float | None = None) -> StartResult:
        """Hand `ticket` to the agent and ask it to bring the tunnel up.

        This is the second half of the workbench's login handshake: the ticket comes from the
        portal's `ticketExchange` (`portal.PortalClient.sid_ticket`) or the agent's own
        `/v1/service/online`, and the agent answers `code 0` while a logged-out client goes
        `online`/`tunnelAvailable` about three seconds later, no window involved (measured live
        2026-10-11, `docs/CLIENT-LOCAL-API.md`, "The login path, verified"). An already-online
        client answers `CLIENT_ALREADY_LOGINED` whatever the ticket was, which is success here.

        The envelope's `guid` has to be the client's own `sdpcguid`: unlike the status read, this
        route does not accept an empty one. `status()` adopts it, so a caller reads the status
        once before calling this. A failure is a value (`StartResult`), never an exception - this
        is a recovery attempt, and the caller falls back to the window path on anything but
        success.
        """
        try:
            answer = self.session('/v1/service/start', {'sidTicket': ticket},
                                  timeout=timeout)
        except ClientAPIError as exc:
            log.debug('client start unavailable: %s', exc)
            return StartResult(ok=False, detail=str(exc))
        code = answer.get('code')
        message = str(answer.get('message') or '')
        if not isinstance(code, int):
            return StartResult(ok=False, detail='unexpected answer: %s' % _short(answer))
        if code in (0, CLIENT_ALREADY_LOGINED):
            return StartResult(ok=True, code=code, message=message,
                               answer_class=classify(code))
        return StartResult(ok=False, code=code, message=message,
                           answer_class=classify(code), detail=answer_text(code, message))


class EventPoller:
    """The client's own event channel, long-polled by a background thread.

    ``POST /v1/service/events`` with ``{"fromId": <last id>, "timeout": <ms>}``
    blocks until the client publishes something and answers with the event(s)
    and the new id (`docs/CLIENT-LOCAL-API.md`, measured live). The poller turns
    the events that can change the data plane (`WAKE_EVENTS`) into ``wake`` - a
    ``threading.Event`` the daemon's waits watch - so a transition on the
    client's side starts the next cycle in seconds instead of at the next
    ``ATRUST_WATCH_INTERVAL``.

    It never decides anything: the woken cycle runs exactly as every cycle does
    and ``probe.check()`` still decides. That is also the vendor's own guidance
    for this channel - on a logout or tunnel event, re-query the state instead of
    trusting the event - and it is why an event is only ever a wake.

    Event ids restart when the agent does (measured through the supervisor's own
    client restart: the burst comes back at a low id again), so a failed poll
    resets ``fromId`` to 0 - "from now" on this transport, which keeps the
    reconnect from being deafened by the previous process's numbering - and the
    id every answer carries is adopted whichever way it moved.

    It must never raise into the daemon: every failure is logged and retried
    with a backoff, and both the poll and the backoff wait watch the stop event.
    """

    def __init__(self, api: ClientAPI, stop: threading.Event,
                 timeout_ms: int = EVENT_TIMEOUT_MS,
                 request_timeout: float = EVENT_REQUEST_TIMEOUT,
                 backoff_base: float = EVENT_BACKOFF_BASE,
                 backoff_cap: float = EVENT_BACKOFF_CAP):
        """``request_timeout``/``backoff_base`` are what the tests move.

        The defaults hold the invariant the long poll needs - the request
        outlives the server's own ``timeout`` field - and a first retry the
        agent's ~2 s restart fits in.
        """
        self.api = api
        self.stop = stop
        self.timeout_ms = timeout_ms
        self.request_timeout = request_timeout
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.wake = threading.Event()
        self.last_id = 0
        self._reasons: list[str] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name='client-events', daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def running(self) -> bool:
        """True while the poll loop is alive."""
        return self._thread is not None and self._thread.is_alive()

    def take_wake(self) -> str:
        """The events that woke it since the last take ('' when none); clears it.

        The daemon calls this when a wait returns: the string is logged and
        carried into the cycle's first transition detail, so the journal says
        *why* a cycle ran early.
        """
        with self._lock:
            reason = ', '.join(self._reasons)
            self._reasons.clear()
        self.wake.clear()
        return reason

    def _record(self, event: dict) -> None:
        name = event['event']
        log.info('client event %s: %s', name, _short(event.get('data')))
        with self._lock:
            if name not in self._reasons:
                self._reasons.append(name)
        self.wake.set()

    def _run(self) -> None:
        delay = self.backoff_base
        down = True
        while not self.stop.is_set():
            try:
                events = self._poll()
            except Exception as exc:  # noqa: BLE001 - the thread must survive anything
                self.last_id = 0
                log.info('client events unreachable: %s; retrying in %.0fs', exc, delay)
                down = True
                if self.stop.wait(delay):
                    return
                delay = min(self.backoff_cap, delay * 2.0)
                continue
            if down:
                log.info('client event channel is up (id %s)', self.last_id)
                down = False
            delay = self.backoff_base
            for event in events:
                if event['event'] in WAKE_EVENTS:
                    self._record(event)
                else:
                    log.debug('client event %s ignored', event['event'])

    def _poll(self) -> list[dict]:
        """One long poll; the events it carried, possibly none."""
        answer = self.api.session('/v1/service/events',
                                  {'fromId': self.last_id, 'timeout': self.timeout_ms},
                                  timeout=self.request_timeout)
        code = answer.get('code')
        if code != 0:
            raise ClientAPIError('events: code %s %s' % (code, answer.get('message') or ''))
        data = answer.get('data')
        if not isinstance(data, dict):
            raise ClientAPIError('events: no data object: %s' % _short(answer))
        if isinstance(data.get('id'), int):
            self.last_id = data['id']
        events = data.get('events')
        if not isinstance(events, list):
            return []
        return [item for item in events
                if isinstance(item, dict) and isinstance(item.get('event'), str)]
