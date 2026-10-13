# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The portal's own answers this project reads: the class table, and the `ticketExchange` half of
the login handshake.

`PortalClient.sid_ticket` is the `ticketExchange` half of the client's own login handshake
(`docs/CLIENT-LOCAL-API.md`, "The login path, verified"): the engine's session cookies are the
whole request and `data.sidTicket` is the answer. The tests pin the request shape the live
measurement found and the three ways it fails - a non-zero code, no `data`, and a transport
that never answers - because the supervisor reads every one of them as "fall back to the
window".

`portal.classify` reads a non-zero answer as its class, and every row replayed through it was
read off something real (below). `PortalClient` keeps the class, code and row of the last
refusal - the supervisor decides with them in the cycles after the one that got them.

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
from unittest import mock

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


class AnswerClassTest(unittest.TestCase):
    """Every row a class is decided by, replayed: the recorded answers through the table.

    The sources, per case below: this engine's own portal calls, the client's own log, the
    vendor's SPA code tables, and the sibling reimplementations of this protocol family. A row
    carries what it really carried; where a pairing is not a measurement (the wrong-password
    row's code is not pinned yet) the comment says so.
    """

    RECORDED = (
        # This engine's own probe once the session was gone, and the session's timeout sibling
        # (the SPA's own enum names both, `SESSION_TIMEOUT`/`SESSION_INVALID` in `errcode.js`).
        (75500002, '会话无效', None, portal.SESSION_INVALID),
        (75500001, '', None, portal.SESSION_INVALID),
        # zju-connect's list (`client/atrust/auth/request.go`): authConfig reads it as session
        # death while every other code is retried.
        (10000004, '', None, portal.SESSION_INVALID),
        # This engine's own login ~24 minutes after a client-side logout (measured 2026-10-11):
        # the portal still holds the account online.
        (75500006, '当前账号已在线，无需重复上线', None, portal.ALREADY_ONLINE),
        # The stale attempt's captcha demand, read out of the client's own log (2026-10-08) -
        # English there, Chinese for this engine's own `lang=zh-CN` login.
        (75500000, 'The characters has expired. Please try again', {'graphCheckCodeEnable': 1},
         portal.CAPTCHA),
        (75500000, '图形验证码已超时，请重试', {'graphCheckCodeEnable': 1}, portal.CAPTCHA),
        # The field and the code each carry the demand on their own.
        (75500000, 'request refused', {'graphCheckCodeEnable': 1}, portal.CAPTCHA),
        (75500000, 'request refused', None, portal.CAPTCHA),
        # The wrong-password row of the 2026-10-10 drill. Its code is not pinned yet - the
        # pairing here is the one a captcha portal is expected to produce (the field is attached
        # to every refused `auth/psw` there), and it must not read as a captcha demand: the
        # captcha it would invite is answered by an attempt of the account's.
        (75500000, 'The username or password is incorrect. You still have 9 attempts left',
         {'graphCheckCodeEnable': 1}, portal.WRONG_PASSWORD),
        # The family's brute-force answer, which EZ4Connect classifies out of the same core.
        (75500000, 'You are trying brute-force login on this IP address.', None,
         portal.RATE_LIMITED),
        # Success, and a row the table knows nothing about: the SPA's own enum names this code
        # (`PASSWORD_TOKEN_INVALID`), this project's table does not class it.
        (0, '', None, ''),
        (75500200, 'PASSWORD_TOKEN_INVALID', None, ''),
    )

    def test_every_recorded_answer_replays_through_the_table(self) -> None:
        for code, message, data, want in self.RECORDED:
            with self.subTest(code=code, message=message, data=data):
                self.assertEqual(want, portal.classify(code, message, data))

    def test_answer_text_carries_the_class_beside_the_code(self) -> None:
        self.assertEqual(
            'code=75500006 class=already-online message=当前账号已在线，无需重复上线',
            portal.answer_text(75500006, '当前账号已在线，无需重复上线', portal.ALREADY_ONLINE))
        self.assertEqual('code=75500307 message=非法的随机校验码',
                         portal.answer_text(75500307, '非法的随机校验码'))

    def test_attempts_left_parses_the_portals_own_counter(self) -> None:
        self.assertEqual(9, portal.attempts_left(
            'The username or password is incorrect. You still have 9 attempts left'))
        self.assertEqual(1, portal.attempts_left('You still have 1 attempt left'))
        for row in ('', 'no counter in this row', '密码错误，请重新输入'):
            with self.subTest(row=row):
                self.assertIsNone(portal.attempts_left(row))


class LoginRefusalTest(unittest.TestCase):
    """`PortalClient` keeps the last refusal's class, code and row for the supervisor.

    The supervisor reads them in the cycles after the one that got them (`client.refused_class`),
    so the answer that stops the engine's login attempts has to outlive the call that produced
    it. The portal answers here are the recorded psw rows, handed back through a patched
    `_request` - the RSA material is only there to build the request body.
    """

    AUTH = {'pubKey': 'ab' * 256, 'pubKeyExp': '65537', 'antiReplayRand': 'r',
            'defaultDomain': 'local'}

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = Config(portal_url='https://portal.example/', username='alice', password='pw',
                          state_dir=Path(tmp.name))

    def client(self) -> portal.PortalClient:
        return portal.PortalClient(self.cfg)

    def test_a_refusal_leaves_its_class_code_and_row_on_the_client(self) -> None:
        for answer, want in (({'code': 75500006, 'message': '当前账号已在线，无需重复上线',
                               'data': {}}, portal.ALREADY_ONLINE),
                             ({'code': 75500200, 'message': 'PASSWORD_TOKEN_INVALID'}, '')):
            with self.subTest(answer=answer):
                client = self.client()
                with mock.patch.object(client, '_request', return_value=answer), \
                        self.assertLogs(portal.log, level='WARNING'):
                    result = client.login(self.AUTH)
                self.assertFalse(result.ok)
                self.assertEqual(want, result.answer_class)
                self.assertEqual(want, client.refused_class)
                self.assertEqual(answer['code'], client.refused_code)
                self.assertEqual(answer['message'], client.refused_message)

    def test_the_refusal_line_carries_the_class_beside_the_code(self) -> None:
        client = self.client()
        answer = {'code': 75500006, 'message': '当前账号已在线，无需重复上线'}
        with mock.patch.object(client, '_request', return_value=answer), \
                self.assertLogs(portal.log, level='ERROR') as logs:
            client.login(self.AUTH)
        self.assertIn('code=75500006 class=already-online', '\n'.join(logs.output))

    def test_a_login_the_portal_took_clears_the_record(self) -> None:
        client = self.client()
        client.refused_class, client.refused_code, client.refused_message = \
            portal.WRONG_PASSWORD, 75500000, 'The username or password is incorrect.'
        answer = {'code': 0, 'message': '', 'data': {'ticket': 't' * 73,
                                                     'nextService': 'auth/authCheck'}}
        with mock.patch.object(client, '_request', return_value=answer):
            result = client.login(self.AUTH)
        self.assertTrue(result.ok, result.message)
        self.assertEqual('', result.answer_class)
        self.assertEqual(('', 0, ''), (client.refused_class, client.refused_code,
                                       client.refused_message))


if __name__ == '__main__':
    unittest.main()
