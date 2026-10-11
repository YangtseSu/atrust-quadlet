# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The portal calls this project makes outside the login itself.

`PortalClient.sid_ticket` is the `ticketExchange` half of the client's own login handshake
(`docs/CLIENT-LOCAL-API.md`, "The login path, verified"): the engine's session cookies are the
whole request and `data.sidTicket` is the answer. The tests pin the request shape the live
measurement found and the three ways it fails - a non-zero code, no `data`, and a transport
that never answers - because the supervisor reads every one of them as "fall back to the
window".

Run: python3 -m unittest tests.test_portal
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import portal  # noqa: E402
from atrustd.config import Config  # noqa: E402

TICKET = 't' * 73


def answer(body, status: int = 200) -> bytes:
    raw = json.dumps(body).encode('utf-8')
    return (b'HTTP/1.1 %d X\r\nContent-Type: application/json\r\n'
            b'Content-Length: %d\r\nConnection: close\r\n\r\n%s' % (status, len(raw), raw))


class StubPortal:
    """The portal's own TCP endpoint, reduced to a plain socket.

    One `reply` for every request, or a `script` list consumed per request (its last entry for
    everything after). Requests are kept whole - method, path, headers and body - so a test can
    assert what the engine actually sent, and bytes go back verbatim so a test can send what no
    client would.
    """

    def __init__(self, reply: bytes | list[bytes]):
        self._script = reply if isinstance(reply, list) else None
        self.reply = None if self._script else reply
        self.requests: list[dict] = []
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(('127.0.0.1', 0))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True, name='StubPortal')
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
                    if self._script:
                        outcome = self._script[min(len(self.requests) - 1, len(self._script) - 1)]
                    else:
                        outcome = self.reply
                    if outcome:
                        conn.sendall(outcome)
            except OSError:
                pass
            conn.close()

    @staticmethod
    def _read(conn: socket.socket) -> dict | None:
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
        self._closed.set()
        self._srv.close()
        self._thread.join(2.0)

    def url(self) -> str:
        return 'http://127.0.0.1:%d/' % self.port


class SidTicketTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_dir = Path(tmp.name)

    def stub(self, reply) -> StubPortal:
        stub = StubPortal(reply)
        self.addCleanup(stub.close)
        return stub

    def client(self, stub: StubPortal) -> portal.PortalClient:
        cfg = Config(portal_url=stub.url(), username='alice', password='pw',
                     state_dir=self.state_dir)
        return portal.PortalClient(cfg)

    def test_sid_ticket_reads_the_answer_and_sends_the_measured_request(self) -> None:
        stub = self.stub(answer({'code': 0, 'message': '', 'data': {'sidTicket': TICKET}}))
        ticket = self.client(stub).sid_ticket()
        self.assertEqual(TICKET, ticket)
        request = stub.requests[-1]
        self.assertEqual('POST', request['method'])
        path, _, query = request['path'].partition('?')
        self.assertEqual('/passport/v1/public/ticketExchange', path)
        self.assertIn('clientType=SDPBrowserClient', query)
        self.assertIn('platform=Linux', query)
        self.assertIn('lang=zh-CN', query)
        self.assertEqual(stub.url(), request['headers']['referer'])
        self.assertTrue(request['headers']['x-sdp-rid'], 'the SPA rid header is missing')
        self.assertEqual({}, json.loads(request['body'] or b'{}'))

    def test_a_non_zero_code_is_unreachable(self) -> None:
        stub = self.stub(answer({'code': 75500002, 'message': '会话无效'}))
        with self.assertRaises(portal.PortalUnreachable) as caught:
            self.client(stub).sid_ticket()
        self.assertIn('75500002', str(caught.exception))

    def test_an_answer_without_a_ticket_is_unreachable(self) -> None:
        for payload in ({'code': 0, 'message': ''},
                        {'code': 0, 'message': '', 'data': {}},
                        {'code': 0, 'message': '', 'data': {'sidTicket': ''}},
                        {'code': 0, 'message': '', 'data': ['not', 'an', 'object']}):
            with self.subTest(payload=payload):
                stub = self.stub(answer(payload))
                with self.assertRaises(portal.PortalUnreachable):
                    self.client(stub).sid_ticket()

    def test_a_transport_failure_is_unreachable(self) -> None:
        stub = self.stub(answer({'code': 0, 'data': {'sidTicket': TICKET}}))
        client = self.client(stub)
        stub.close()

        with self.assertRaises(portal.PortalUnreachable):
            client.sid_ticket()

    def test_a_non_json_answer_is_unreachable(self) -> None:
        stub = self.stub(b'HTTP/1.1 200 X\r\nContent-Type: text/html\r\nContent-Length: 15\r\n'
                         b'Connection: close\r\n\r\nnot json at all')
        with self.assertRaises(portal.PortalUnreachable):
            self.client(stub).sid_ticket()


if __name__ == '__main__':
    unittest.main()
