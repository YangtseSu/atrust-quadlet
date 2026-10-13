# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The proxy probe's witnesses: retries, and who decides the check.

The client's userspace netstack drops an occasional connection of its own accord
(its lookup of the source socket fails and xtunnel logs ``find pid err``), so one
hung CONNECT atrustd's probe timed out on - while the tunnel carried traffic -
must not become a DEGRADED that restarts the client. The same probe also carries
the witness rule: the addresses the tunnel's own route table names are asked
beside the configured target, and a witness that cannot answer never decides the
check while another one answers.

Run: python3 -m unittest tests.test_probe_retry
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

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

    def witnesses(self) -> list[probe.Witness]:
        """The single configured target the retry claims are about."""
        return [probe.Witness(*self.TARGET, timeout=self.TIMEOUT)]

    def test_one_attempt_on_a_hung_connection_is_down(self) -> None:
        """The behaviour before the fix: one attempt, one verdict."""
        proxy = self.stub(hang_first=1)
        ok, msg = probe.probe_witnesses(proxy.address, self.witnesses(),
                                        attempts=1)
        self.assertFalse(ok)
        self.assertIn('timed out', msg)

    def test_retry_recovers_from_a_hung_connection(self) -> None:
        proxy = self.stub(hang_first=1)
        ok, msg = probe.probe_witnesses(proxy.address, self.witnesses(),
                                        attempts=3)
        self.assertTrue(ok, msg)
        self.assertGreaterEqual(proxy.hits, 2, 'the retry did not happen')

    def test_every_attempt_failing_is_down(self) -> None:
        proxy = self.stub(always_hang=True)
        ok, msg = probe.probe_witnesses(proxy.address, self.witnesses(),
                                        attempts=3)
        self.assertFalse(ok)
        self.assertIn('failed all 3 attempts', msg)
        self.assertEqual(proxy.hits, 3)

    def test_a_healthy_proxy_is_not_slowed_down(self) -> None:
        proxy = self.stub()
        started = time.time()
        ok, msg = probe.probe_witnesses(proxy.address, self.witnesses(),
                                        attempts=3)
        self.assertTrue(ok, msg)
        self.assertEqual(proxy.hits, 1)
        self.assertLess(time.time() - started, self.TIMEOUT)

    def test_the_probe_sends_a_real_request(self) -> None:
        """A bare CONNECT does not count as activity for the portal, so the probe
        sends a real request: the supervision itself keeps the session alive."""
        proxy = self.stub()
        ok, _ = probe.probe_witnesses(proxy.address, self.witnesses(), attempts=1)
        self.assertTrue(ok)
        self.assertEqual(len(proxy.requests), 1)
        self.assertTrue(proxy.requests[0].startswith(b'GET http://10.0.0.10:80/'),
                        proxy.requests[0][:60])

    def test_a_proxy_error_is_not_an_answer_from_the_far_side(self) -> None:
        """tinyproxy answers 502 itself when it cannot reach the target; that must
        not look like the tunnel carrying traffic."""
        proxy = self.stub(reply=b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
        ok, msg = probe.probe_witnesses(proxy.address, self.witnesses(), attempts=1)
        self.assertFalse(ok)
        self.assertIn('502', msg)

    def test_a_witness_that_cannot_answer_does_not_decide_while_another_answers(self) -> None:
        """The unreachable-target case: the address a human named does not answer,
        another witness does. The tunnel carries traffic, so the check is online and
        the detail says which witness answered - the dead one is not a tunnel fault."""
        proxy = self.stub(hang_first=1)      # the first witness hangs, the second answers
        witnesses = self.witnesses() + [probe.Witness('10.0.0.11', 80, timeout=self.TIMEOUT,
                                                      source='route')]
        ok, msg = probe.probe_witnesses(proxy.address, witnesses)
        self.assertTrue(ok, msg)
        self.assertIn('no answer from 10.0.0.10:80', msg)
        self.assertIn('probe 10.0.0.11:80 ok', msg)
        self.assertIn(', route', msg, 'the detail does not say where the witness came from')

    def test_the_route_hosts_are_the_witnesses_when_none_is_configured(self) -> None:
        """The live table's shape: bare addresses are candidates (a /32 counts), the
        client's own subnet carvings are not, and the configured target stays first."""
        lines = ['10.0.0.20 ', '10.0.0.21/32 ', '198.18.0.2/31 ', '198.18.255.1 ',
                 'default via 192.0.2.1 dev eth0', '2001:db8::1/128 ']
        got = probe.witnesses_for([('10.0.0.10', 80)], lines, discover=True)
        self.assertEqual([(w.host, w.port, w.source) for w in got],
                         [('10.0.0.10', 80, 'target'),
                          ('10.0.0.20', 80, 'route'),
                          ('10.0.0.21', 80, 'route'),
                          ('198.18.255.1', 80, 'route')])
        self.assertEqual(got[0].timeout, probe.PROBE_TIMEOUT)
        self.assertEqual(got[-1].timeout, probe.DISCOVERY_TIMEOUT)
        self.assertEqual(len(probe.witnesses_for([], lines, discover=False)), 0,
                         'the switch off must not discover anything')
        # A configured target that is also a route host is asked once, as the target.
        deduped = probe.witnesses_for([('10.0.0.20', 80)], lines, discover=True)
        self.assertEqual([(w.host, w.source) for w in deduped][:2],
                         [('10.0.0.20', 'target'), ('10.0.0.21', 'route')])

    def test_check_discovers_a_witness_from_the_tunnels_own_routes(self) -> None:
        """End to end through `check`: no configured target, one host route, and the
        request that finds it is the same one the supervisor sends every cycle."""
        proxy = self.stub()
        with mock.patch.object(probe, 'tun_state', return_value=(True, 'utun7 2.0.0.1/24')), \
                mock.patch.object(probe, 'route_lines',
                                  return_value=(['10.0.0.10 ', '198.18.0.2/31 '],
                                                '2 route(s) via utun7')):
            result = probe.check('utun7', proxy.address, [], discover=True)
        self.assertTrue(result.online)
        self.assertTrue(result.probes_configured)
        self.assertIn('probe 10.0.0.10:80 ok', result.detail)
        self.assertIn(', route', result.detail)
        self.assertEqual(proxy.hits, 1)

    def test_check_without_a_target_or_a_route_host_probes_nothing(self) -> None:
        """Nothing to ask (the switch off, or a tunnel whose routes are subnets only):
        the interface and its routes are the proof, exactly as before discovery."""
        with mock.patch.object(probe, 'tun_state', return_value=(True, 'utun7 2.0.0.1/24')), \
                mock.patch.object(probe, 'route_lines',
                                  return_value=(['198.18.0.2/31 '], '1 route(s) via utun7')):
            result = probe.check('utun7', '127.0.0.1:9', [], discover=True)
        self.assertTrue(result.online)
        self.assertFalse(result.probes_configured, 'an unwitnessed check claimed a witness')

    def test_check_skips_the_probe_without_a_datapath(self) -> None:
        """A tunnel that is already down must not pay the retry budget."""
        started = time.time()
        result = probe.check('ndef0', '127.0.0.1:9', [self.TARGET])
        self.assertFalse(result.online)
        self.assertIn('not probed', result.detail)
        self.assertLess(time.time() - started, self.TIMEOUT)


if __name__ == '__main__':
    unittest.main()
