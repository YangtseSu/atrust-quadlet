# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The proxy probe retries before it calls the tunnel down.

The client's userspace netstack drops an occasional connection of its own accord
(its lookup of the source socket fails and xtunnel logs ``find pid err``), so one
hung CONNECT atrustd's probe timed out on - while the tunnel carried traffic -
must not become a DEGRADED that restarts the client.

Run: python3 -m unittest tests.test_probe_retry
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import probe  # noqa: E402


class StubProxy:
    """A CONNECT proxy: the first `hang_first` connections are accepted and never
    answered (what a netstack-dropped connection looks like from the proxy),
    the rest get `200 Connection established`."""

    def __init__(self, hang_first: int = 0, always_hang: bool = False,
                 reply: bytes = b'HTTP/1.1 200 Connection established\r\n\r\n'):
        self._always_hang = always_hang
        self._hang_first = hang_first
        self._reply = reply
        self._open: list[socket.socket] = []      # keep the hung sockets alive
        self._hits = 0
        self.requests: list[bytes] = []           # what the client actually sent
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(('127.0.0.1', 0))
        self._srv.listen(8)
        self.address = '127.0.0.1:%d' % self._srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def hits(self) -> int:
        return self._hits

    def _serve(self) -> None:
        self._srv.settimeout(0.05)
        while True:
            try:
                conn, _ = self._srv.accept()
            except (socket.timeout, OSError):
                continue
            self._hits += 1
            try:
                self.requests.append(conn.recv(4096))
            except OSError:
                pass
            if self._always_hang or self._hits <= self._hang_first:
                self._open.append(conn)
            else:
                try:
                    conn.sendall(self._reply)
                except OSError:
                    pass
                conn.close()

    def close(self) -> None:
        for conn in self._open:
            conn.close()
        self._srv.close()


class ProbeRetryTest(unittest.TestCase):
    TARGET = ('10.0.0.10', 80)
    TIMEOUT = 0.2                 # per attempt; the stub hangs, not the network

    def setUp(self) -> None:
        self._delay = probe.PROBE_RETRY_DELAY
        probe.PROBE_RETRY_DELAY = 0.05
        self.addCleanup(setattr, probe, 'PROBE_RETRY_DELAY', self._delay)

    def stub(self, **kwargs) -> StubProxy:
        proxy = StubProxy(**kwargs)
        self.addCleanup(proxy.close)
        return proxy

    def test_one_attempt_on_a_hung_connection_is_down(self) -> None:
        """The behaviour before the fix: one attempt, one verdict."""
        proxy = self.stub(hang_first=1)
        ok, msg = probe.proxy_probe(proxy.address, *self.TARGET,
                                    timeout=self.TIMEOUT, attempts=1)
        self.assertFalse(ok)
        self.assertIn('timed out', msg)

    def test_retry_recovers_from_a_hung_connection(self) -> None:
        proxy = self.stub(hang_first=1)
        ok, msg = probe.proxy_probe(proxy.address, *self.TARGET,
                                    timeout=self.TIMEOUT, attempts=3)
        self.assertTrue(ok, msg)
        self.assertGreaterEqual(proxy.hits, 2, 'the retry did not happen')

    def test_every_attempt_failing_is_down(self) -> None:
        proxy = self.stub(always_hang=True)
        ok, msg = probe.proxy_probe(proxy.address, *self.TARGET,
                                    timeout=self.TIMEOUT, attempts=3)
        self.assertFalse(ok)
        self.assertIn('failed all 3 attempts', msg)
        self.assertEqual(proxy.hits, 3)

    def test_a_healthy_proxy_is_not_slowed_down(self) -> None:
        proxy = self.stub()
        started = time.time()
        ok, msg = probe.proxy_probe(proxy.address, *self.TARGET,
                                    timeout=self.TIMEOUT, attempts=3)
        self.assertTrue(ok, msg)
        self.assertEqual(proxy.hits, 1)
        self.assertLess(time.time() - started, self.TIMEOUT)

    def test_the_probe_sends_a_real_request(self) -> None:
        """A bare CONNECT does not count as activity for the portal, so the probe
        sends a real request: the supervision itself keeps the session alive."""
        proxy = self.stub()
        ok, _ = probe.proxy_probe(proxy.address, *self.TARGET, timeout=self.TIMEOUT, attempts=1)
        self.assertTrue(ok)
        self.assertEqual(len(proxy.requests), 1)
        self.assertTrue(proxy.requests[0].startswith(b'GET http://10.0.0.10:80/'),
                        proxy.requests[0][:60])

    def test_a_proxy_error_is_not_an_answer_from_the_far_side(self) -> None:
        """tinyproxy answers 502 itself when it cannot reach the target; that must
        not look like the tunnel carrying traffic."""
        proxy = self.stub(reply=b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
        ok, msg = probe.proxy_probe(proxy.address, *self.TARGET, timeout=self.TIMEOUT, attempts=1)
        self.assertFalse(ok)
        self.assertIn('502', msg)

    def test_check_skips_the_probe_without_a_datapath(self) -> None:
        """A tunnel that is already down must not pay the retry budget."""
        started = time.time()
        result = probe.check('ndef0', '127.0.0.1:9', [self.TARGET])
        self.assertFalse(result.online)
        self.assertIn('not probed', result.detail)
        self.assertLess(time.time() - started, self.TIMEOUT)


if __name__ == '__main__':
    unittest.main()
