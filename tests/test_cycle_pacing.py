# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The supervisor must not spin.

`cycle()` used to `return` from its healthy path without sleeping, so with the
tunnel up `run_daemon` ran `probe.check()` (two `ip` forks plus one CONNECT to
the intranet target) roughly forty times a second - which is what flooded the
client's netstack with connections and made the probe itself time out.

Run: python3 -m unittest tests.test_cycle_pacing
"""
from __future__ import annotations

import signal
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import __main__ as main  # noqa: E402
from atrustd import probe, tokens, uiauto  # noqa: E402
from atrustd.config import Config  # noqa: E402
from atrustd.state import Backoff, StateFile, Status  # noqa: E402

ONLINE = probe.ProbeResult(tun_up=True, routes=True, proxy_ok=True, probes_configured=True,
                           detail='utun7 2.0.0.1/24; 30 route(s) via utun7; probe ok')
NO_DATAPLANE = probe.ProbeResult(tun_up=True, routes=True, proxy_ok=False, probes_configured=True,
                                 detail='utun7 2.0.0.1/24; 30 route(s) via utun7; probe timed out')


class CyclePacingTest(unittest.TestCase):
    WATCH = 90

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = Config(portal_url='https://vpn.example.com/', username='user', password='pw',
                          watch_interval=self.WATCH, state_dir=Path(tmp.name))
        self.state_file = StateFile(self.cfg.state_dir)
        self.status = Status()
        self.backoff = Backoff()
        self.slept: list[float] = []
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(sig)
            self.addCleanup(signal.signal, sig, previous)
        sleep_patcher = mock.patch.object(main.time, 'sleep', self.slept.append)
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)
        seed_patcher = mock.patch.object(uiauto, 'seed_address')
        seed_patcher.start()
        self.addCleanup(seed_patcher.stop)

    def cycle(self) -> float:
        with mock.patch.object(probe, 'check', return_value=self.result):
            return main.cycle(self.cfg, mock.Mock(), self.state_file, self.status, self.backoff)

    def test_online_waits_the_watch_interval_without_sleeping_internally(self) -> None:
        self.result = ONLINE
        started = time.time()
        delay = self.cycle()
        self.assertEqual(delay, self.WATCH)
        self.assertLess(time.time() - started, 0.5)
        self.assertEqual(self.slept, [], 'cycle() slept; the caller owns the pacing')
        self.assertEqual(self.status.state, 'ONLINE')

    def test_a_client_that_does_not_come_back_backs_off(self) -> None:
        self.result = NO_DATAPLANE
        client = mock.Mock()
        client.is_logged_in.return_value = True
        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(tokens, 'stop_client'), \
                mock.patch.object(tokens, 'wait_client', return_value=False):
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff)
        self.assertEqual(delay, Backoff().base)
        self.assertEqual(self.slept, [])
        self.assertEqual(self.status.state, 'DEGRADED')

    def test_the_human_recovery_reports_the_tunnel_it_saw(self) -> None:
        """The ONLINE after a human action carries the probe's own detail.

        It used to call ``transition()`` without one, so the state file kept the
        previous cycle's detail - "no utun7: Device \"utun7\" does not exist.; 0
        route(s) via utun7; not probed, no datapath yet" - beside a message that
        said the tunnel had come up. The desktop notifier reads that same field,
        so the notification contradicted itself as well (seen live on
        2026-10-10, the NEED_VNC drill).
        """
        client = mock.Mock()
        client.is_logged_in.return_value = False
        client.captcha_required = False
        client.fetch_check_code.return_value = b''
        ui = mock.Mock()
        ui.acted = False
        ui.needs_human = True
        ui.detail = 'the window shows the captcha'
        ui.describe.return_value = ui.detail
        with mock.patch.object(probe, 'check', side_effect=[NO_DATAPLANE, ONLINE]), \
                mock.patch.object(main, 'refresh_tokens', return_value=False), \
                mock.patch.object(uiauto, 'log_offset', return_value=0), \
                mock.patch.object(uiauto, 'login', return_value=ui), \
                mock.patch.object(uiauto, 'captcha_requested', return_value=False):
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.status.state, 'ONLINE')
        self.assertEqual(self.status.message, 'tunnel up after human action')
        self.assertEqual(self.status.detail, ONLINE.detail,
                         'the recovery left the detail of the cycle that gave up')
        self.assertFalse(self.state_file.vnc_hint_path.exists(), 'the hint outlived the recovery')

    def test_the_daemon_waits_between_cycles(self) -> None:
        calls: list[float] = []

        def sleeper(_stop, seconds: float) -> None:
            calls.append(seconds)
            if len(calls) >= 3:
                raise SystemExit('three cycles are enough')

        with mock.patch.object(probe, 'check', return_value=ONLINE), \
                mock.patch.object(main, 'pause', sleeper):
            with self.assertRaises(SystemExit):
                main.run_daemon(self.cfg)
        self.assertEqual(calls, [self.WATCH] * 3, 'the daemon did not sleep between cycles')

    def test_once_runs_a_single_cycle_and_returns(self) -> None:
        with mock.patch.object(probe, 'check', return_value=ONLINE) as check:
            self.assertEqual(main.run_daemon(self.cfg, once=True), 0)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(self.slept, [])


if __name__ == '__main__':
    unittest.main()
