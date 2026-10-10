# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The notifier must fire once per transition - and only then.

A regression here is silent in both directions - a transition that never
reaches the desktop, or a 15 s poll that notifies the same state again and
again. The container side is stubbed: a fake `podman` serves a temporary state
directory and a fake `notify-send` records its argv, so the whole script runs
without podman, without GNOME and without the engine.

Run: python3 -m unittest tests.test_notify
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCRIPT = Path(__file__).resolve().parent.parent / 'quadlet' / 'atrust-notify.sh'

PODMAN_STUB = r"""#!/bin/sh
# podman exec <container> cat <path>
if [ "${ATRUST_TEST_NO_CONTAINER:-}" = 1 ]; then
    exit 125
fi
if [ "$2" != "atrust" ]; then
    exit 125
fi
case "$4" in
    /run/atrustd/*)
        file="$ATRUST_TEST_STATE_DIR/${4#/run/atrustd/}"
        if [ -f "$file" ]; then
            exec cat "$file"
        fi
        ;;
esac
exit 125
"""

NOTIFY_STUB = r"""#!/bin/sh
printf '%s\t' "$@" >> "$NOTIFY_LOG"
printf '\n' >> "$NOTIFY_LOG"
icon=''
previous=''
for argument in "$@"; do
    if [ "$previous" = '-i' ]; then
        icon="$argument"
    fi
    previous="$argument"
done
if [ -n "$icon" ]; then
    cp "$icon" "$NOTIFY_ICON_DIR/"
fi
"""


class NotifyTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state_dir = self.root / 'state'
        self.runtime = self.root / 'run'
        self.icons = self.root / 'icons'
        self.bin = self.root / 'bin'
        for directory in (self.state_dir, self.runtime, self.icons, self.bin):
            directory.mkdir()
        self.log = self.root / 'notify.log'
        self.install('notify-send', NOTIFY_STUB)
        self.install('podman', PODMAN_STUB)

    # --- the world the script runs in -----------------------------------------

    def install(self, name: str, text: str) -> None:
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def env(self, **extra: str) -> dict[str, str]:
        env = {
            'HOME': str(self.root),
            'NOTIFY_LOG': str(self.log),
            'NOTIFY_ICON_DIR': str(self.icons),
            'ATRUST_TEST_STATE_DIR': str(self.state_dir),
            'PATH': os.pathsep.join([str(self.bin), os.defpath]),
            'XDG_RUNTIME_DIR': str(self.runtime),
        }
        env.update(extra)
        return env

    def run_script(self, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(SCRIPT)], env=self.env(**extra),
                              capture_output=True, text=True)

    def write_state(self, state: str, since: float, message: str = '', detail: str = '') -> None:
        status = {'state': state, 'since': since, 'updated': since, 'attempts': 0,
                  'message': message, 'detail': detail, 'vnc_hint': ''}
        (self.state_dir / 'state.json').write_text(json.dumps(status, ensure_ascii=False, indent=2))

    def write_marker(self, state: str, since: float) -> None:
        (self.runtime / 'atrust-notify.last').write_text('%s\n%s\n' % (state, repr(since)))

    def marker(self) -> str:
        path = self.runtime / 'atrust-notify.last'
        return path.read_text() if path.exists() else ''

    def notifications(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [line.split('\t')[:-1] for line in self.log.read_text().splitlines()]

    def only_notification(self) -> list[str]:
        lines = self.notifications()
        self.assertEqual(len(lines), 1, 'expected exactly one notification, got %d' % len(lines))
        return lines[0]

    def assert_sent(self, argv: list[str], urgency: str, title: str, body: str,
                    icon: bytes | None = None) -> None:
        self.assertEqual(argv[-3:], ['--', title, body])
        self.assertEqual(argv[argv.index('-a') + 1], 'aTrust')
        self.assertEqual(argv[argv.index('-u') + 1], urgency)
        if icon is None:
            self.assertNotIn('-i', argv)
        else:
            copied = list(self.icons.iterdir())
            self.assertEqual(len(copied), 1, 'the icon did not reach notify-send')
            self.assertEqual(copied[0].read_bytes(), icon)

    # --- the transitions ------------------------------------------------------

    def test_the_first_run_seeds_the_marker_silently(self) -> None:
        self.write_state('ONLINE', 100.0, detail='utun7 2.0.0.1/24; probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n100.0\n')

    def test_a_poll_that_sees_the_same_state_is_silent(self) -> None:
        self.write_state('ONLINE', 100.0, detail='utun7 2.0.0.1/24; probe ok')
        self.run_script()  # seeds the marker
        # the engine rewrites the file every cycle: same state and since, new `updated` and detail
        self.write_state('ONLINE', 100.0, detail='utun7 2.0.0.1/24; probe ok, a cycle later')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [], 'the same (state, since) was notified twice')

    def test_the_tunnel_going_down_notifies_once(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('DEGRADED', 200.0, message='tunnel not usable',
                         detail='utun7 2.0.0.1/24; probe timed out')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is not usable',
                         'utun7 2.0.0.1/24; probe timed out')
        self.assertEqual(self.marker(), 'DEGRADED\n200.0\n')

    def test_the_tunnel_coming_back_notifies_once(self) -> None:
        self.write_marker('DEGRADED', 200.0)
        self.write_state('ONLINE', 300.0, message='tunnel up',
                         detail='utun7 2.0.0.1/24; 30 route(s) via utun7; probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         'utun7 2.0.0.1/24; 30 route(s) via utun7; probe ok')

    def test_need_vnc_carries_the_hint_the_captcha_and_critical_urgency(self) -> None:
        self.write_marker('DEGRADED', 200.0)
        self.write_state('NEED_VNC', 300.0, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text(
            'NEED_VNC: the portal is asking for the graphical captcha; answer it in the client '
            'window over VNC\n'
            'Open the container desktop and finish the login there:\n'
            '  vncviewer 127.0.0.1:5901      (password: the container password / PASSWORD env)\n')
        captcha = b'\x89PNG\r\n\x1a\n' + b'not-a-real-captcha' * 8
        (self.state_dir / 'captcha.png').write_bytes(captcha)

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: human action required',
                         'the portal is asking for the graphical captcha; answer it in the client '
                         'window over VNC', icon=captcha)
        self.assertEqual(self.marker(), 'NEED_VNC\n300.0\n')
        self.assertEqual(sorted(p.name for p in self.runtime.iterdir()), ['atrust-notify.last'],
                         'the captcha copy was left behind')

    def test_need_vnc_without_a_captcha_falls_back_to_the_message(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('NEED_VNC', 200.0, message='waiting for a human in VNC')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: human action required',
                         'waiting for a human in VNC')

    def test_the_recovery_from_need_vnc_notifies(self) -> None:
        self.write_marker('NEED_VNC', 200.0)
        self.write_state('ONLINE', 300.0, message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up', 'probe ok')

    def test_a_pending_need_vnc_is_not_seeded_silently(self) -> None:
        self.write_state('NEED_VNC', 200.0, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text(
            'NEED_VNC: the portal is asking for the graphical captcha\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: human action required',
                         'the portal is asking for the graphical captcha')

    def test_a_daemon_restart_does_not_announce_the_tunnel_again(self) -> None:
        self.write_marker('ONLINE', 100.0)
        # a recreated container loses the state file, so the fresh daemon writes ONLINE with a new
        # `since`: the tunnel never left, and must not be announced
        self.write_state('ONLINE', 500.0, message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n500.0\n')

    def test_a_state_it_does_not_know_is_recorded_without_a_notification(self) -> None:
        self.write_marker('DEGRADED', 200.0)
        self.write_state('STARTING', 300.0)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'STARTING\n300.0\n')

    # --- the host without a container -----------------------------------------

    def test_a_missing_container_is_silence(self) -> None:
        self.write_marker('ONLINE', 100.0)
        result = self.run_script(ATRUST_TEST_NO_CONTAINER='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n100.0\n')

    def test_a_host_without_podman_is_silence(self) -> None:
        (self.bin / 'podman').unlink()
        for tool in ('sed', 'head', 'cat', 'mv', 'rm'):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.write_marker('ONLINE', 100.0)
        result = subprocess.run([str(SCRIPT)], capture_output=True, text=True,
                                env={'HOME': str(self.root), 'PATH': str(self.bin),
                                     'XDG_RUNTIME_DIR': str(self.runtime)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n100.0\n')

    # --- the urgency knobs ----------------------------------------------------

    def test_the_state_urgency_is_configurable(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('DEGRADED', 200.0, message='tunnel not usable', detail='probe timed out')
        result = self.run_script(ATRUST_NOTIFY_URGENCY_STATE='low')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'low', 'aTrust: tunnel is not usable',
                         'probe timed out')

    def test_the_need_vnc_urgency_is_configurable(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('NEED_VNC', 200.0, message='waiting for a human in VNC')
        result = self.run_script(ATRUST_NOTIFY_URGENCY_NEED_VNC='normal')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: human action required',
                         'waiting for a human in VNC')

    def test_an_invalid_urgency_falls_back_to_the_default(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('DEGRADED', 200.0, message='tunnel not usable', detail='probe timed out')
        result = self.run_script(ATRUST_NOTIFY_URGENCY_STATE='loud')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('invalid ATRUST_NOTIFY_URGENCY_STATE', result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is not usable',
                         'probe timed out')


if __name__ == '__main__':
    unittest.main()
