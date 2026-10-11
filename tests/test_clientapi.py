# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The client's local API as `atrustd` reads it.

The client's loopback service is an internal interface - the shapes here are the
ones the live measurements found (`docs/CLIENT-LOCAL-API.md`): the envelope the
client's own workbench sends, the portal-origin `Referer` the gates check, the
port file with its +11 fallbacks, and that every kind of failure is a value a
cycle survives, not an exception. The real service is TLS on the client's own
self-signed certificate, which a test cannot present; `scheme='http'` points the
same client at a plain socket the test owns, and everything else stays equal.

Run: python3 -m unittest tests.test_clientapi
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import clientapi  # noqa: E402
from atrustd.config import Config  # noqa: E402

PORTAL = 'https://portal.example/'

STATUS_BODY = {
    'code': 0,
    'message': '',
    'data': {
        'status': 'online',
        'data': {
            'addr': 'https://portal.example',
            'username': 'alice',
            'trustlevel': 0,
            'tunnelStatus': 'tunnelAvailable',
            'loginTime': '2026-10-11 13:00:18',
            'sdpcguid': 'ab' * 32,
        },
    },
}

RECORD = {'state': 'online', 'tunnel': 'tunnelAvailable', 'user': 'alice',
          'login': '2026-10-11 13:00:18'}


def answer(body, status: int = 200) -> bytes:
    raw = json.dumps(body).encode('utf-8')
    return (b'HTTP/1.1 %d X\r\nContent-Type: application/json\r\n'
            b'Content-Length: %d\r\nConnection: close\r\n\r\n%s' % (status, len(raw), raw))


class StubService:
    """The client's loopback service, reduced to a plain socket.

    One `reply` for every request, or a `handler(request, index)` that decides
    per request - ``bytes`` to send, ``b''`` to close the connection without an
    answer (what the agent's death looks like under an in-flight long poll),
    ``None`` to keep holding it (a long poll that has not timed out yet).
    ``reply=None`` reads the request and never answers, which is what a wedged
    agent looks like from `atrustd`. Requests are kept whole - method, path,
    headers and body - so a test can assert what the client actually sent.
    """

    def __init__(self, reply: bytes | None, port: int = 0, handler=None):
        self.reply = reply
        self.handler = handler
        self.requests: list[dict] = []
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._srv.bind(('127.0.0.1', port))
        except OSError:
            self._srv.close()
            raise
        self._srv.listen(8)
        self.port = self._srv.getsockname()[1]
        self._open: list[socket.socket] = []
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True, name='StubService')
        self._thread.start()

    def _serve(self) -> None:
        self._srv.settimeout(0.05)
        while not self._closed.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                request = self._read(conn)
                if request is not None:
                    self.requests.append(request)
                outcome = self.reply
                if self.handler is not None and request is not None:
                    outcome = self.handler(request, len(self.requests) - 1)
                if outcome is None:
                    self._open.append(conn)     # a wedged agent: read, never answer
                    continue
                if outcome:
                    conn.sendall(outcome)
                # b'' falls through: closed without an answer, the agent's death
            except OSError:
                pass
            conn.close()

    @staticmethod
    def _read(conn: socket.socket) -> dict | None:
        """None when the peer connected and said nothing (a port probe)."""
        conn.settimeout(2.0)
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return None
            data += chunk
        head, _, body = data.partition(b'\r\n\r\n')
        lines = head.decode('latin-1').split('\r\n')
        method, path, _ = lines[0].split(' ', 2)
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(':')
            headers[name.strip().lower()] = value.strip()
        length = int(headers.get('content-length') or 0)
        while len(body) < length:
            chunk = conn.recv(4096)
            if not chunk:
                break
            body += chunk
        return {'method': method, 'path': path, 'headers': headers, 'body': body[:length]}

    def close(self) -> None:
        """Deterministic teardown: the listener is really gone when this returns.

        Closing the listening socket while its thread sits in ``accept()`` keeps
        it in LISTEN until that call returns (the in-flight syscall holds it), so
        a test that rebinds the same port right afterwards - the port-discovery
        cases do - would race the previous stub. The thread exits on the accept
        timeout, so join it.
        """
        self._closed.set()
        for conn in self._open:
            conn.close()
        self._srv.close()
        self._thread.join(2.0)


class ClientAPITest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.port_file = Path(tmp.name) / 'httpserver'

    def cfg(self) -> Config:
        return Config(portal_url=PORTAL, username='alice', password='pw',
                      client_api_port_file=self.port_file)

    def stub(self, reply: bytes | None, port: int = 0) -> StubService:
        service = StubService(reply, port)
        self.addCleanup(service.close)
        return service

    def stub_on(self, port: int) -> StubService:
        try:
            return self.stub(answer(STATUS_BODY), port=port)
        except OSError:
            raise unittest.SkipTest('port %d is already in use on this machine' % port) from None

    def api(self, service: StubService, **kwargs) -> clientapi.ClientAPI:
        """A client pointed at the stub through the port file the client writes."""
        self.port_file.write_text('%d\n' % service.port, encoding='utf-8')
        return clientapi.ClientAPI(self.cfg(), scheme='http', **kwargs)

    def assert_free(self, port: int) -> None:
        probe_socket = socket.socket()
        probe_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe_socket.bind(('127.0.0.1', port))
        except OSError:
            raise unittest.SkipTest('port %d is already in use on this machine' % port) from None
        finally:
            probe_socket.close()

    # -- the status read -----------------------------------------------------
    def test_status_reads_the_user_state_and_sends_the_reference_envelope(self) -> None:
        service = self.stub(answer(STATUS_BODY))
        view = self.api(service).status()
        self.assertTrue(view.ok, view.detail)
        self.assertEqual('online', view.state)
        self.assertEqual('tunnelAvailable', view.tunnel)
        self.assertEqual('alice', view.username)
        self.assertEqual('2026-10-11 13:00:18', view.login_time)
        self.assertEqual(RECORD, view.as_record())
        request = service.requests[-1]
        self.assertEqual('POST', request['method'])
        self.assertEqual('/v1/service/status', request['path'])
        body = json.loads(request['body'])
        self.assertEqual('https://portal.example', body['addr'])
        self.assertEqual('web', body['type'])
        self.assertEqual('zh-CN', body['lang'])
        self.assertEqual('', body['token'])
        self.assertEqual({}, body['data'])
        self.assertRegex(body['sdpTraceId'], r'^[0-9a-f]{8}$')
        self.assertEqual({'addr', 'type', 'guid', 'lang', 'token', 'sdpTraceId', 'data'},
                         set(body))

    def test_the_gate_header_is_the_portal_origin(self) -> None:
        """The identity fields and the gated routes need `Referer: <portal>/`."""
        service = self.stub(answer(STATUS_BODY))
        self.api(service).status()
        self.assertEqual('https://portal.example/', service.requests[-1]['headers']['referer'])

    def test_session_posts_a_gated_route_with_the_envelope(self) -> None:
        service = self.stub(answer({'code': 0, 'message': 'OK', 'data': {}}))
        got = self.api(service).session('/v1/service/logout', {'type': 'force'})
        self.assertEqual(0, got['code'])
        request = service.requests[-1]
        self.assertEqual('/v1/service/logout', request['path'])
        self.assertEqual('https://portal.example/', request['headers']['referer'])
        self.assertEqual({'type': 'force'}, json.loads(request['body'])['data'])

    # -- port discovery ------------------------------------------------------
    def test_the_port_file_decides_between_candidates(self) -> None:
        chosen = self.stub(answer(STATUS_BODY))
        self.port_file.write_text('%d\n' % chosen.port, encoding='utf-8')
        fallback = self.stub_on(clientapi.PORT_CANDIDATES[0])
        view = clientapi.ClientAPI(self.cfg(), scheme='http').status()
        self.assertTrue(view.ok, view.detail)
        self.assertEqual(1, len(chosen.requests), 'the file port was not used')
        self.assertEqual([], fallback.requests, 'a candidate was used although the file answered')

    def test_a_missing_port_file_falls_back_to_the_candidates(self) -> None:
        service = self.stub_on(clientapi.PORT_CANDIDATES[0])
        view = clientapi.ClientAPI(self.cfg(), scheme='http').status()
        self.assertTrue(view.ok, view.detail)
        self.assertEqual(1, len(service.requests))

    def test_a_malformed_port_file_falls_back_to_the_candidates(self) -> None:
        self.port_file.write_text('not-a-port\n', encoding='utf-8')
        service = self.stub_on(clientapi.PORT_CANDIDATES[0])
        view = clientapi.ClientAPI(self.cfg(), scheme='http').status()
        self.assertTrue(view.ok, view.detail)
        self.assertEqual(1, len(service.requests))

    def test_a_stale_port_file_falls_through_to_the_next_candidate(self) -> None:
        stale = clientapi.PORT_CANDIDATES[2]
        self.assert_free(stale)
        self.port_file.write_text('%d\n' % stale, encoding='utf-8')
        service = self.stub_on(clientapi.PORT_CANDIDATES[0])
        view = clientapi.ClientAPI(self.cfg(), scheme='http').status()
        self.assertTrue(view.ok, view.detail)
        self.assertEqual(1, len(service.requests))

    def test_a_drifted_port_is_read_from_the_file(self) -> None:
        drifted = clientapi.PORT_CANDIDATES[1]
        service = self.stub_on(drifted)
        self.port_file.write_text('%d\n' % drifted, encoding='utf-8')
        view = clientapi.ClientAPI(self.cfg(), scheme='http').status()
        self.assertTrue(view.ok, view.detail)
        self.assertEqual(1, len(service.requests))

    def test_the_port_file_parser(self) -> None:
        for raw, want in (('54630\n', 54630), (' 54641 ', 54641), ('abc', None), ('0', None),
                          ('70000', None), ('', None)):
            with self.subTest(raw=raw):
                self.port_file.write_text(raw, encoding='utf-8')
                self.assertEqual(want, clientapi.read_port(self.port_file))
        self.port_file.unlink()
        self.assertIsNone(clientapi.read_port(self.port_file))

    def test_nothing_listening_is_a_value_not_an_exception(self) -> None:
        for port in clientapi.PORT_CANDIDATES:
            self.assert_free(port)
        view = clientapi.ClientAPI(self.cfg(), scheme='http', connect_timeout=0.2).status()
        self.assertFalse(view.ok)
        self.assertIn('not listening', view.detail)

    # -- answers that are not a status --------------------------------------
    def test_a_business_error_is_a_value(self) -> None:
        service = self.stub(answer({'code': 11119003, 'message': 'Invalid request.'}))
        view = self.api(service).status()
        self.assertFalse(view.ok)
        self.assertEqual(11119003, view.code)
        self.assertEqual('Invalid request.', view.message)
        self.assertIn('11119003', view.detail)
        self.assertIn('error', view.as_record())

    def test_a_gated_403_is_read_as_the_answer_it_carries(self) -> None:
        service = self.stub(answer({'code': 11119003, 'message': 'Invalid request.'}, status=403))
        view = self.api(service).status()
        self.assertFalse(view.ok)
        self.assertEqual(11119003, view.code)

    def test_garbage_is_a_value(self) -> None:
        service = self.stub(b'HTTP/1.1 200 X\r\nContent-Length: 15\r\nConnection: close\r\n\r\n'
                            b'not json at all')
        view = self.api(service).status()
        self.assertFalse(view.ok)
        self.assertIn('non-JSON', view.detail)

    def test_a_wedged_service_times_out_within_the_bound(self) -> None:
        service = self.stub(None)
        api = self.api(service, timeout=0.3)
        started = time.time()
        view = api.status()
        elapsed = time.time() - started
        self.assertFalse(view.ok)
        self.assertLess(elapsed, 2.0, 'the status read outlived its bound')
        self.assertTrue(service.requests, 'the request never reached the stub')


class EventPollerTest(unittest.TestCase):
    """The long poll on `/v1/service/events`, and the wake it drives.

    Everything runs against a socket the test owns; the numbers the poller uses
    (``timeout_ms``, the request bound, the backoff) are shrunk so the longest
    sleep in here is the fake's own long-poll hold.
    """

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.port_file = Path(tmp.name) / 'httpserver'

    def cfg(self) -> Config:
        return Config(portal_url=PORTAL, username='alice', password='pw',
                      client_api_port_file=self.port_file)

    def service(self, handler) -> StubService:
        stub = StubService(None, handler=handler)
        self.addCleanup(stub.close)
        return stub

    def poller(self, stub: StubService, **kwargs) -> clientapi.EventPoller:
        self.port_file.write_text('%d\n' % stub.port, encoding='utf-8')
        api = clientapi.ClientAPI(self.cfg(), scheme='http', connect_timeout=0.2)
        stop = threading.Event()
        poller = clientapi.EventPoller(api, stop, backoff_base=0.05, backoff_cap=0.1, **kwargs)
        poller.start()
        self.addCleanup(poller.join, 2.0)
        self.addCleanup(stop.set)
        return poller

    def wait_for(self, predicate, timeout: float = 3.0) -> bool:
        end = time.time() + timeout
        while not predicate() and time.time() < end:
            time.sleep(0.02)
        return predicate()

    @staticmethod
    def events(*names: str, head: int) -> bytes:
        payload = [{'event': name, 'data': {}} for name in names]
        return answer({'code': 0, 'message': 'OK', 'data': {'events': payload, 'id': head}})

    @staticmethod
    def quiet(head: int) -> bytes:
        return answer({'code': 0, 'message': 'OK', 'data': {'id': head}})

    # -- the request shape ---------------------------------------------------
    def test_the_poll_carries_the_envelope_the_timeout_and_the_last_id(self) -> None:
        """The channel's shape: POST, the envelope, `fromId` + `timeout` in data."""
        script = [self.events('endConsult', head=25), self.quiet(25)]

        def handler(request, index):
            return script[index] if index < len(script) else None

        stub = self.service(handler)
        poller = self.poller(stub, timeout_ms=200, request_timeout=1.0)
        self.assertTrue(self.wait_for(lambda: len(stub.requests) >= 2), 'the poll never repeated')
        first = stub.requests[0]
        self.assertEqual('POST', first['method'])
        self.assertEqual('/v1/service/events', first['path'])
        self.assertEqual('https://portal.example/', first['headers']['referer'])
        body = json.loads(first['body'])
        self.assertEqual({'fromId': 0, 'timeout': 200}, body['data'])
        self.assertEqual('web', body['type'])
        self.assertEqual({'addr', 'type', 'guid', 'lang', 'token', 'sdpTraceId', 'data'},
                         set(body))
        self.assertEqual({'fromId': 25, 'timeout': 200},
                         json.loads(stub.requests[1]['body'])['data'],
                         'the id the answer carried did not travel')
        self.assertFalse(poller.wake.is_set(), 'endConsult is chatter, not a wake')
        self.assertEqual('', poller.take_wake())

    def test_a_quiet_timeout_answers_the_same_id_and_does_not_wake(self) -> None:
        """Nothing new: the server holds out `timeout` and answers only the head."""

        def handler(request, index):
            time.sleep(0.2)                      # the server's own hold
            return self.quiet(7)

        stub = self.service(handler)
        poller = self.poller(stub, timeout_ms=200, request_timeout=1.0)
        self.assertTrue(self.wait_for(lambda: len(stub.requests) >= 2))
        self.assertEqual({'fromId': 7, 'timeout': 200},
                         json.loads(stub.requests[1]['body'])['data'])
        self.assertFalse(poller.wake.is_set())

    # -- the wake ------------------------------------------------------------
    def test_an_interesting_event_wakes_and_keeps_the_reason(self) -> None:
        """A session event sets the wake; the chatter beside it is ignored."""
        script = [self.events('logout', 'resourceReady', 'endConsult', head=31)]

        def handler(request, index):
            return script[index] if index < len(script) else None

        stub = self.service(handler)
        poller = self.poller(stub, timeout_ms=200, request_timeout=0.5)
        self.assertTrue(self.wait_for(poller.wake.is_set), 'the event never woke it')
        self.assertEqual('logout', poller.take_wake())
        self.assertEqual('', poller.take_wake(), 'the reason survived its take')
        self.assertTrue(self.wait_for(lambda: len(stub.requests) >= 2))
        self.assertEqual({'fromId': 31, 'timeout': 200},
                         json.loads(stub.requests[1]['body'])['data'])

    def test_a_reconnect_burst_wakes_once_with_every_name(self) -> None:
        """The agent's own restart burst: several wake events, one reason."""
        script = [self.events('tunnelStatus', 'status', 'uemStatus', head=8)]

        def handler(request, index):
            return script[index] if index < len(script) else None

        stub = self.service(handler)
        poller = self.poller(stub, timeout_ms=200, request_timeout=0.5)
        self.assertTrue(self.wait_for(poller.wake.is_set))
        self.assertEqual('tunnelStatus, status', poller.take_wake())

    # -- failures ------------------------------------------------------------
    def test_a_dropped_connection_resets_the_id_to_zero(self) -> None:
        """The agent died mid-poll; its ids restart, so ask from 0 again."""
        script = [self.quiet(12), b'', self.quiet(3)]

        def handler(request, index):
            return script[index] if index < len(script) else None

        stub = self.service(handler)
        poller = self.poller(stub, timeout_ms=200, request_timeout=0.5)
        self.assertTrue(self.wait_for(lambda: len(stub.requests) >= 3), 'no retry after the drop')
        self.assertEqual({'fromId': 0, 'timeout': 200},
                         json.loads(stub.requests[2]['body'])['data'],
                         'the stale id was kept across the reconnect')
        self.assertTrue(self.wait_for(lambda: poller.last_id == 3),
                        'the id the answer carried was not adopted')
        self.assertFalse(poller.wake.is_set())

    def test_a_business_error_is_retried_not_raised(self) -> None:
        """A channel answering an error is a lost poll, not a dead poller."""
        script = [answer({'code': 11119003, 'message': 'Invalid request.'}, status=403)] * 2

        def handler(request, index):
            return script[index] if index < len(script) else self.quiet(5)

        stub = self.service(handler)
        poller = self.poller(stub, timeout_ms=200, request_timeout=0.5)
        self.assertTrue(self.wait_for(lambda: len(stub.requests) >= 3), 'the error killed it')
        self.assertTrue(self.wait_for(lambda: poller.last_id == 5))
        self.assertFalse(poller.wake.is_set())

    def test_the_stop_event_ends_the_poller(self) -> None:
        """A stop has to end it promptly, an in-flight poll included."""
        stub = self.service(lambda request, index: None)     # every poll is held
        poller = self.poller(stub, timeout_ms=150, request_timeout=0.3)
        self.assertTrue(self.wait_for(lambda: len(stub.requests) >= 1))
        poller.stop.set()
        started = time.monotonic()
        poller.join(2.0)
        self.assertFalse(poller.running(), 'the poller outlived its stop')
        self.assertLess(time.monotonic() - started, 1.5, 'the stop was not prompt')


if __name__ == '__main__':
    unittest.main()
