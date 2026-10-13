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

import json
import signal
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import __main__ as main  # noqa: E402
from atrustd import clientapi, probe, tokens, uiauto  # noqa: E402
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
        # The client's own API is a stub here: the daemon constructs it and every
        # transition reads it, and a unit test must not touch loopback for real.
        api_patcher = mock.patch.object(main.clientapi, 'ClientAPI')
        self.api_class = api_patcher.start()
        self.addCleanup(api_patcher.stop)
        self.api_class.return_value.status.return_value = clientapi.ClientStatus(
            ok=False, detail='test stub: not listening')
        # The event poller is a stub for the same reason: the daemon starts it
        # and the cycle's wake reason comes out of it. A real one would poll.
        poller_patcher = mock.patch.object(main.clientapi, 'EventPoller')
        self.poller_class = poller_patcher.start()
        self.addCleanup(poller_patcher.stop)
        self.poller = self.poller_class.return_value
        self.poller.wake = threading.Event()
        self.poller.take_wake.return_value = ''

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

    # -- the ticket path, and the window as its fallback ---------------------
    def client_status(self, **fields) -> clientapi.ClientStatus:
        base = {'ok': True, 'state': 'logout', 'tunnel': 'tunnelUnavailable', 'guid': 'ab' * 32}
        base.update(fields)
        return clientapi.ClientStatus(**base)

    def test_the_ticket_path_brings_the_tunnel_up_without_the_window(self) -> None:
        """The measured sequence: live session -> ticket -> `start` -> tunnel.

        No window opens and no fresh login runs - the client's own workbench calls, nothing
        else. The ONLINE transition names the path, so the journal says which one ran.
        """
        client = mock.Mock()
        client.is_logged_in.side_effect = [False, True]
        client.sid_ticket.return_value = 't' * 73
        api = mock.Mock()
        api.status.return_value = self.client_status()
        api.start.return_value = clientapi.StartResult(ok=True, code=0)
        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(main, 'wait_for_tunnel', return_value=ONLINE) as wait, \
                mock.patch.object(main, 'refresh_tokens') as refresh, \
                mock.patch.object(uiauto, 'login') as login:
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.status.state, 'ONLINE')
        self.assertEqual(self.status.message, 'tunnel up after the ticket login')
        self.assertEqual(self.status.detail, ONLINE.detail)
        login.assert_not_called()
        refresh.assert_not_called()
        client.sid_ticket.assert_called_once_with()
        api.start.assert_called_once_with('t' * 73)
        self.assertEqual('ab' * 32, api.guid)
        self.assertEqual(main.API_TUNNEL_WAIT, wait.call_args.kwargs['seconds'])

    def test_a_refused_ticket_falls_back_to_the_window(self) -> None:
        """`start` refusing the ticket sends the cycle down the old path, window included."""
        client = mock.Mock()
        client.is_logged_in.side_effect = [False, True]
        client.sid_ticket.return_value = 'garbage'
        client.captcha_required = False
        api = mock.Mock()
        api.status.return_value = self.client_status()
        api.start.return_value = clientapi.StartResult(
            ok=False, code=75500307, message='非法的随机校验码',
            detail='code 75500307 非法的随机校验码')
        ui = mock.Mock()
        ui.acted = True
        ui.needs_human = False
        ui.describe.return_value = 'credentials submitted [page=login]'
        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(main, 'wait_for_tunnel', return_value=ONLINE), \
                mock.patch.object(main, 'refresh_tokens', return_value=True), \
                mock.patch.object(main, 'publish_apps'), \
                mock.patch.object(uiauto, 'login', return_value=ui) as login, \
                mock.patch.object(uiauto, 'captcha_requested', return_value=False), \
                self.assertLogs(main.log, level='INFO') as logs:
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.status.state, 'ONLINE')
        self.assertEqual(self.status.message, 'tunnel up after the client login')
        login.assert_called_once()
        api.start.assert_called_once()
        self.assertIn('the ticket login did not bring the tunnel up', '\n'.join(logs.output))

    def test_a_ticket_whose_tunnel_never_comes_up_falls_back_to_the_window(self) -> None:
        """`start` accepted the ticket and the tunnel stayed down: the window takes it."""
        client = mock.Mock()
        client.is_logged_in.side_effect = [False, True]
        client.sid_ticket.return_value = 't' * 73
        client.captcha_required = False
        api = mock.Mock()
        api.status.return_value = self.client_status()
        api.start.return_value = clientapi.StartResult(ok=True, code=0)
        ui = mock.Mock()
        ui.acted = True
        ui.needs_human = False
        ui.describe.return_value = 'credentials submitted [page=login]'
        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(main, 'wait_for_tunnel',
                                  side_effect=[NO_DATAPLANE, ONLINE]) as wait, \
                mock.patch.object(main, 'refresh_tokens', return_value=True), \
                mock.patch.object(main, 'publish_apps'), \
                mock.patch.object(uiauto, 'login', return_value=ui), \
                mock.patch.object(uiauto, 'captcha_requested', return_value=False):
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.status.state, 'ONLINE')
        self.assertEqual(self.status.message, 'tunnel up after the client login')
        self.assertEqual(2, wait.call_count, 'the ticket wait and the window wait')
        self.assertEqual(main.API_TUNNEL_WAIT, wait.call_args_list[0].kwargs['seconds'])
        self.assertEqual(main.UI_TUNNEL_WAIT, wait.call_args_list[1].kwargs['seconds'])

    def test_a_client_without_a_guid_is_not_given_a_ticket(self) -> None:
        """`/v1/service/start` rejects an empty envelope guid (`Invalid schema:
        #/properties/guid`, seen live on a tray that was still loading its state), so a client
        that has not published one is not attempted at all: the window path takes it."""
        client = mock.Mock()
        client.is_logged_in.side_effect = [False, True]
        api = mock.Mock()
        api.status.return_value = self.client_status(guid='')
        ui = mock.Mock()
        ui.acted = True
        ui.needs_human = False
        ui.describe.return_value = 'credentials submitted [page=login]'
        with mock.patch.object(main, 'CLIENT_RESTART_WAIT', 0.1), \
                mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(main, 'wait_for_tunnel', return_value=ONLINE), \
                mock.patch.object(main, 'refresh_tokens', return_value=True), \
                mock.patch.object(main, 'publish_apps'), \
                mock.patch.object(uiauto, 'login', return_value=ui) as login, \
                mock.patch.object(uiauto, 'captcha_requested', return_value=False):
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.status.state, 'ONLINE')
        self.assertEqual(self.status.message, 'tunnel up after the client login')
        client.sid_ticket.assert_not_called()
        api.start.assert_not_called()
        login.assert_called_once()

    def test_the_hand_over_carries_why_the_ticket_path_did_not_work(self) -> None:
        """When the ticket path cannot even mint (no live session), the state says so.

        The state file - and the NEED_VNC hint beside it - is what a human reads; the ticket
        path's refusal has to be in there beside the window's, not only in the journal.
        """
        client = mock.Mock()
        client.is_logged_in.return_value = False
        client.captcha_required = False
        client.fetch_check_code.return_value = b''
        api = mock.Mock()
        api.status.return_value = self.client_status()
        ui = mock.Mock()
        ui.acted = False
        ui.needs_human = True
        ui.detail = 'the window shows the captcha'
        ui.describe.return_value = ui.detail
        details: list[tuple[str, str]] = []
        real_transition = main.transition

        def spy(state_file, status, state, message, detail=''):
            details.append((state.value, detail))
            real_transition(state_file, status, state, message, detail)

        with mock.patch.object(probe, 'check', side_effect=[NO_DATAPLANE, ONLINE]), \
                mock.patch.object(main, 'refresh_tokens', return_value=False), \
                mock.patch.object(uiauto, 'log_offset', return_value=0), \
                mock.patch.object(uiauto, 'login', return_value=ui), \
                mock.patch.object(uiauto, 'captcha_requested', return_value=False), \
                mock.patch.object(main, 'transition', spy):
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.status.state, 'ONLINE')
        notes = [detail for state, detail in details if state == 'LOGGED_OUT' and detail]
        self.assertTrue(any(detail.startswith('the ticket login:') for detail in notes),
                        'the ticket path left no trace in the transitions: %r' % (details,))
        client.sid_ticket.assert_not_called()

    def test_the_client_view_is_recorded_beside_the_transitions(self) -> None:
        """Every state ``state.json`` holds carries the client's own view.

        The step's point: the file (and the notifier that reads it) gains what
        the data plane cannot see - the client's user state, tunnel state, user
        name and login time - read at the moment of the transition, and the
        journal line carries it next to the probe's detail.
        """
        api = self.api_class.return_value
        api.status.return_value = clientapi.ClientStatus(
            ok=True, state='offline', tunnel='tunnelUnavailable',
            username='alice', login_time='2026-10-11 13:00:18')
        client = mock.Mock()
        client.is_logged_in.return_value = True
        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(tokens, 'stop_client'), \
                mock.patch.object(tokens, 'wait_client', return_value=False), \
                self.assertLogs(main.log, level='INFO') as logs:
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, Backoff().base)
        record = json.loads(self.state_file.path.read_text(encoding='utf-8'))['client']
        self.assertEqual({'state': 'offline', 'tunnel': 'tunnelUnavailable', 'user': 'alice',
                          'login': '2026-10-11 13:00:18'}, record)
        self.assertEqual(2, api.status.call_count, 'the view is not read per transition')
        self.assertIn('client offline/tunnelUnavailable user=alice since=2026-10-11 13:00:18',
                      '\n'.join(logs.output))

    def test_the_window_path_reuses_the_login_the_ticket_path_ran(self) -> None:
        """One portal login per cycle, whoever runs it first.

        `_api_login` runs the fresh login when the engine's session is cold - the window
        path's ground work either way - and the window path's own `refresh_tokens` right
        after it was measured refused (`75500006 当前账号已在线，无需重复上线`, 0.3 s after
        the first had landed), which reads like a failed login although the first one stood.
        A cycle the ticket path logged into reuses that session; the app list is still
        published from it.
        """
        client = mock.Mock()
        client.is_logged_in.return_value = False
        client.sid_ticket.return_value = 't' * 73
        api = mock.Mock()
        api.status.return_value = self.client_status()
        api.start.return_value = clientapi.StartResult(
            ok=False, code=75500307, message='非法的随机校验码',
            detail='code 75500307 非法的随机校验码')
        ui = mock.Mock()
        ui.acted = True
        ui.needs_human = False
        ui.describe.return_value = 'credentials submitted [page=login]'
        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(main, 'wait_for_tunnel', return_value=ONLINE), \
                mock.patch.object(main, 'refresh_tokens', return_value=True) as refresh, \
                mock.patch.object(main, 'publish_apps') as apps, \
                mock.patch.object(uiauto, 'login', return_value=ui), \
                mock.patch.object(uiauto, 'captcha_requested', return_value=False):
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.status.message, 'tunnel up after the client login')
        refresh.assert_called_once_with(self.cfg, client)
        self.assertEqual(1, apps.call_count, 'the session still answers the app list')

    # -- the skip: one view may send the restart branch aside -----------------
    def test_a_client_side_logout_skips_the_restart(self) -> None:
        """`logout`/`tunnelUnavailable` - and only that - sends the branch aside.

        The measured detour on 2.5.16.41: the restart, the tray's own stop and the 120 s
        tunnel wait cost 2.4 minutes before `LOGGED_OUT`, and the ticket path then
        recovered in 5.4 s. So the cycle goes straight to the login path - in this same
        cycle, not back to the backoff - pays the ticket wait only, and both the journal
        and the transition carry why the restart did not happen.
        """
        client = mock.Mock()
        client.is_logged_in.return_value = True
        client.sid_ticket.return_value = 't' * 73
        api = mock.Mock()
        api.status.return_value = self.client_status()
        api.start.return_value = clientapi.StartResult(ok=True, code=0)
        details: list[tuple[str, str]] = []
        real_transition = main.transition

        def spy(state_file, status, state, message, detail=''):
            details.append((state.value, detail))
            real_transition(state_file, status, state, message, detail)

        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(tokens, 'stop_client') as stop, \
                mock.patch.object(tokens, 'wait_client') as wait, \
                mock.patch.object(main, 'wait_for_tunnel', return_value=ONLINE) as tunnel_wait, \
                mock.patch.object(uiauto, 'login') as login, \
                mock.patch.object(main, 'transition', spy), \
                self.assertLogs(main.log, level='INFO') as logs:
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH, 'the skipped cycle went back to the backoff')
        self.assertEqual(self.status.state, 'ONLINE')
        self.assertEqual(self.status.message, 'tunnel up after the ticket login')
        stop.assert_not_called()
        wait.assert_not_called()
        login.assert_not_called()
        self.assertEqual(1, tunnel_wait.call_count, 'the ticket wait is the only one paid')
        self.assertIn('client logout/tunnelUnavailable; not restarting it', '\n'.join(logs.output))
        self.assertNotIn('web session is alive', '\n'.join(logs.output))
        self.assertIn(('LOGGED_OUT', 'client logout/tunnelUnavailable; not restarting it'), details)

    def assert_restart_branch_runs(self, status: 'clientapi.ClientStatus | None') -> None:
        """One cycle whose view must not skip the branch; it restarts as before."""
        client = mock.Mock()
        client.is_logged_in.return_value = True
        api = self.api_class.return_value if status is not None else None
        if status is not None:
            api.status.return_value = status
        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(tokens, 'stop_client') as stop, \
                mock.patch.object(tokens, 'wait_client', return_value=False), \
                self.assertLogs(main.log, level='INFO') as logs:
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, Backoff().base, 'the branch did not run; it went elsewhere')
        stop.assert_called_once()
        self.assertIn('web session is alive but the tunnel is not', '\n'.join(logs.output))

    def test_the_restart_branch_keeps_when_the_view_is_not_a_logout(self) -> None:
        self.assert_restart_branch_runs(
            self.client_status(state='online', tunnel='tunnelUnavailable'))

    def test_the_restart_branch_keeps_when_a_logout_carries_another_tunnel(self) -> None:
        self.assert_restart_branch_runs(self.client_status(tunnel='tunnelPreparing'))

    def test_the_restart_branch_keeps_when_the_view_cannot_be_read(self) -> None:
        # setUp's stub answers ok=False with a reason: a failed read is not a statement
        # about the session, and the client's service is unreachable around a restart
        self.assert_restart_branch_runs(self.api_class.return_value.status.return_value)

    def test_the_restart_branch_keeps_without_the_client_api(self) -> None:
        self.assert_restart_branch_runs(None)

    def test_the_daemon_waits_between_cycles(self) -> None:
        calls: list[float] = []

        def sleeper(_stop, seconds: float, wake=None) -> None:
            self.assertIs(wake, self.poller.wake, 'the wait does not watch the poller')
            calls.append(seconds)
            if len(calls) >= 3:
                raise SystemExit('three cycles are enough')

        with mock.patch.object(probe, 'check', return_value=ONLINE), \
                mock.patch.object(main, 'pause', sleeper):
            with self.assertRaises(SystemExit):
                main.run_daemon(self.cfg)
        self.assertEqual(calls, [self.WATCH] * 3, 'the daemon did not sleep between cycles')
        self.poller.start.assert_called_once()

    def test_a_client_event_wakes_a_wait_without_sleeping_it_out(self) -> None:
        """A transition on the client's side cuts the wait; a stop still wins."""
        stop = threading.Event()
        wake = threading.Event()
        timer = threading.Timer(0.05, wake.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.time()
        self.assertFalse(main.pause(stop, 30.0, wake))
        self.assertLess(time.time() - started, 2.0, 'the wake did not cut the wait')
        stop.set()
        self.assertTrue(main.pause(stop, 30.0, wake), 'a stop lost to an event')

    def test_pause_keeps_its_plain_shape(self) -> None:
        """No poller, no change: a bare sleep while the stop is absent."""
        stop = threading.Event()
        self.assertFalse(main.pause(stop, 0.05))
        self.assertFalse(main.pause(None, 0.01))
        stop.set()
        self.assertTrue(main.pause(stop, 30.0))

    def test_a_woken_cycle_carries_the_event_into_its_first_transition(self) -> None:
        """The journal says why a cycle ran early - and only its first transition
        detail carries the event; the ones after it in the same cycle do not."""
        client = mock.Mock()
        client.is_logged_in.return_value = False
        client.captcha_required = False
        ui = mock.Mock()
        ui.acted = False
        ui.needs_human = False
        ui.describe.return_value = 'no window'
        details: list[str] = []
        real_transition = main.transition

        def spy(state_file, status, state, message, detail=''):
            details.append(detail)
            real_transition(state_file, status, state, message, detail)

        with mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(main, 'refresh_tokens', return_value=False), \
                mock.patch.object(uiauto, 'log_offset', return_value=0), \
                mock.patch.object(uiauto, 'login', return_value=ui), \
                mock.patch.object(uiauto, 'captcha_requested', return_value=False), \
                mock.patch.object(main, 'transition', spy), \
                self.assertLogs(main.log, level='INFO') as logs:
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               wake='logout')
        self.assertEqual(delay, Backoff().base)
        self.assertEqual(self.status.state, 'LOGGED_OUT')
        self.assertIn('woke on client event(s): logout', '\n'.join(logs.output))
        self.assertEqual(2, len(details), 'the cycle did not walk the expected transitions')
        self.assertIn('woke on client event logout', details[0])
        self.assertEqual('', details[1], 'the note was repeated on the next transition')
        self.assertIn('woke on client event logout',
                      json.loads(self.state_file.path.read_text(encoding='utf-8'))['detail'])

    def test_a_client_event_reaches_the_next_cycle_as_its_wake_reason(self) -> None:
        """`run_daemon` hands the poller's reason to the cycle that ran early."""
        reasons: list[str] = []

        def faked_cycle(_cfg, _client, _state_file, _status, _backoff, stop=None, api=None,
                        wake=''):
            reasons.append(wake)
            if len(reasons) >= 2:
                raise SystemExit('two cycles are enough')
            return self.WATCH

        self.poller.take_wake.side_effect = ['', 'logout']
        with mock.patch.object(main, 'cycle', faked_cycle), \
                mock.patch.object(main, 'pause', lambda _stop, _seconds, _wake=None: False):
            with self.assertRaises(SystemExit):
                main.run_daemon(self.cfg)
        self.assertEqual(['', 'logout'], reasons)

    def test_once_runs_a_single_cycle_and_returns(self) -> None:
        with mock.patch.object(probe, 'check', return_value=ONLINE) as check:
            self.assertEqual(main.run_daemon(self.cfg, once=True), 0)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(self.slept, [])
        self.poller.start.assert_not_called()

    # -- the waits the interface pays, and the switch that takes it out ------
    def test_a_client_that_has_never_published_a_guid_is_not_waited_for(self) -> None:
        """The bound belongs to a restart, not to a container whose client has just started.

        Measured live: a tray that has published a guid publishes it again within ~5 s of its
        restart, while a client that has never published one - a container that has just been
        recreated - takes 35 s+, and the window path's login runs in that case anyway. Paid
        twice per attempt, the bound was ~20 s of step 14's cold start (54.4 s against the old
        path's 13.5 s); the discriminator is the daemon's own memory of a guid.
        """
        client = mock.Mock()
        client.is_logged_in.return_value = False
        client.captcha_required = False
        client.fetch_check_code.return_value = b''
        api = mock.Mock()
        api.seen_guid = False
        api.status.return_value = self.client_status(guid='')
        ui = mock.Mock()
        ui.acted = True
        ui.needs_human = False
        ui.describe.return_value = 'credentials submitted [page=login]'
        with mock.patch.object(main, 'CLIENT_RESTART_WAIT', 10.0), \
                mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(main, 'wait_for_tunnel', return_value=ONLINE), \
                mock.patch.object(main, 'refresh_tokens', return_value=True), \
                mock.patch.object(main, 'publish_apps'), \
                mock.patch.object(uiauto, 'login', return_value=ui), \
                mock.patch.object(uiauto, 'captcha_requested', return_value=False), \
                self.assertLogs(main.log, level='WARNING') as logs:
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.slept, [], 'the cold path paid the restart bound')
        self.assertEqual(self.status.message, 'tunnel up after the client login')
        self.assertIn('the ticket login: the client has no session guid yet', self.status.detail)
        client.sid_ticket.assert_not_called()
        self.assertIn('the ticket login did not bring the tunnel up',
                      '\n'.join(logs.output), 'the fallback is not visible at WARNING')

    def test_a_client_that_has_published_a_guid_before_still_gets_the_wait(self) -> None:
        """The measured case the bound was written for: a tray restart, its guid back in ~5 s.

        Its HTTP service is unreachable for ~2-4 s around the restart and the guid follows, so
        the cycle waits - and the ticket path then recovers the session without the window.
        """
        client = mock.Mock()
        client.is_logged_in.side_effect = [False, True]
        client.sid_ticket.return_value = 't' * 73
        api = mock.Mock()
        api.seen_guid = True
        api.status.side_effect = [self.client_status(guid='')] * 3 + [self.client_status()] * 2
        api.start.return_value = clientapi.StartResult(ok=True, code=0)
        with mock.patch.object(main, 'CLIENT_RESTART_WAIT', 3.0), \
                mock.patch.object(probe, 'check', return_value=NO_DATAPLANE), \
                mock.patch.object(main, 'wait_for_tunnel', return_value=ONLINE) as wait, \
                mock.patch.object(uiauto, 'login') as login:
            delay = main.cycle(self.cfg, client, self.state_file, self.status, self.backoff,
                               api=api)
        self.assertEqual(delay, self.WATCH)
        self.assertEqual(self.slept, [1.0], 'the guid wait did not happen where it belongs')
        self.assertEqual(self.status.message, 'tunnel up after the ticket login')
        login.assert_not_called()
        api.start.assert_called_once_with('t' * 73)
        self.assertEqual(main.API_TUNNEL_WAIT, wait.call_args.kwargs['seconds'])

    def test_the_client_api_can_be_switched_off(self) -> None:
        """`ATRUST_CLIENT_API=0`: no API object, no poller, no view in the state file.

        The interface is measured, not documented - a client bump may move it with nothing to
        announce it - so a deployment needs a way back that is not a downgrade: one variable
        and the supervisor reads the data plane only, exactly as it did before the interface.
        """
        cfg = Config(portal_url='https://vpn.example.com/', username='user', password='pw',
                     watch_interval=self.WATCH, state_dir=self.cfg.state_dir, client_api=False)
        # A view the previous run left in the file is not carried into this one: the state file
        # must not claim a client view nobody read (measured live 2026-10-12 - a start with the
        # switch off kept reporting the earlier run's `online/tunnelAvailable`).
        self.state_file.write(Status(state='DEGRADED', message='tunnel not usable',
                                     client={'state': 'online', 'tunnel': 'tunnelAvailable',
                                             'user': 'user', 'login': '2026-10-12 13:00:00'}))
        with mock.patch.object(probe, 'check', return_value=ONLINE):
            self.assertEqual(main.run_daemon(cfg, once=True), 0)
        self.api_class.assert_not_called()
        self.poller_class.assert_not_called()
        written = json.loads(self.state_file.path.read_text(encoding='utf-8'))
        self.assertEqual({}, written['client'], 'the switched-off supervisor recorded a view')

    def test_the_api_switch_is_parsed_from_the_environment(self) -> None:
        base = {'ATRUST_PORTAL_URL': 'https://vpn.example.com/', 'ATRUST_USERNAME': 'user',
                'ATRUST_PASSWORD': 'pw'}
        self.assertTrue(Config.from_env(base).client_api, 'the interface is on by default')
        self.assertTrue(Config.from_env(dict(base, ATRUST_CLIENT_API='1')).client_api)
        for raw in ('0', 'false', 'no', 'off', 'OFF', ' off '):
            with self.subTest(raw=raw):
                self.assertFalse(Config.from_env(dict(base, ATRUST_CLIENT_API=raw)).client_api)

    def test_the_discovery_switch_is_parsed_from_the_environment(self) -> None:
        """`ATRUST_PROBE_DISCOVER=0`: no witness is discovered, and with no
        `ATRUST_PROBE_TARGET` either the interface and its routes are the proof -
        the supervisor a deployment had before discovery existed."""
        base = {'ATRUST_PORTAL_URL': 'https://vpn.example.com/', 'ATRUST_USERNAME': 'user',
                'ATRUST_PASSWORD': 'pw'}
        self.assertTrue(Config.from_env(base).probe_discover, 'discovery is on by default')
        self.assertEqual([], Config.from_env(base).probe_targets)
        self.assertTrue(Config.from_env(dict(base, ATRUST_PROBE_DISCOVER='1')).probe_discover)
        for raw in ('0', 'false', 'no', 'off', 'OFF', ' off '):
            with self.subTest(raw=raw):
                self.assertFalse(Config.from_env(dict(base, ATRUST_PROBE_DISCOVER=raw)).probe_discover)


if __name__ == '__main__':
    unittest.main()
