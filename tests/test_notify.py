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
# podman cp <container>:<path> <host path> - the only podman call the script makes; an exec would
# write `container exec` records into the journal through the container's own log driver
if [ "${ATRUST_TEST_NO_CONTAINER:-}" = 1 ]; then
    exit 125
fi

last=''
source=''
for argument in "$@"; do
    if [ -n "$last" ]; then
        source="$last"
    fi
    last="$argument"
done

case "$source" in
    atrust:/run/atrustd/*)
        file="$ATRUST_TEST_STATE_DIR/${source#atrust:/run/atrustd/}"
        if [ -f "$file" ]; then
            exec cp "$file" "$last"
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
        for tool in ('sed', 'head', 'cat', 'mv', 'rm', 'tr'):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.write_marker('ONLINE', 100.0)
        result = subprocess.run([str(SCRIPT)], capture_output=True, text=True,
                                env={'HOME': str(self.root), 'PATH': str(self.bin),
                                     'XDG_RUNTIME_DIR': str(self.runtime)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n100.0\n')

    # --- the mounted state directory ------------------------------------------

    def test_the_mount_is_read_without_podman(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('DEGRADED', 200.0, message='tunnel not usable', detail='probe timed out')
        result = self.run_script(ATRUST_STATE_HOST_DIR=str(self.state_dir),
                                 ATRUST_TEST_NO_CONTAINER='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is not usable',
                         'probe timed out')

    def test_the_mounted_captcha_is_used_in_place_and_kept(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('NEED_VNC', 200.0, message='waiting for a human in VNC')
        captcha = b'\x89PNG\r\n\x1a\n' + b'captcha-bytes' * 8
        (self.state_dir / 'captcha.png').write_bytes(captcha)

        result = self.run_script(ATRUST_STATE_HOST_DIR=str(self.state_dir),
                                 ATRUST_TEST_NO_CONTAINER='1')

        self.assertEqual(result.returncode, 0, result.stderr)
        argv = self.only_notification()
        self.assertEqual(argv[argv.index('-i') + 1], str(self.state_dir / 'captcha.png'),
                         'the mounted captcha was not passed in place')
        self.assertEqual((self.state_dir / 'captcha.png').read_bytes(), captcha,
                         'the notifier touched a file of the container state directory')

    def test_an_empty_mount_still_falls_back_to_podman(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('DEGRADED', 200.0, message='tunnel not usable', detail='probe timed out')
        empty = self.root / 'empty-mount'
        empty.mkdir()
        result = self.run_script(ATRUST_STATE_HOST_DIR=str(empty))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is not usable',
                         'probe timed out')

    # --- the mute filter ------------------------------------------------------

    def test_a_muted_class_is_silent_and_still_moves_the_marker(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('DEGRADED', 200.0, message='tunnel not usable', detail='probe timed out')
        result = self.run_script(ATRUST_NOTIFY_MUTE='DEGRADED')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'DEGRADED\n200.0\n',
                         'a muted class did not move the marker')

        # the recovery is not muted and must not be swallowed by the silent degradation
        self.write_state('ONLINE', 300.0, message='tunnel up', detail='probe ok')
        self.run_script(ATRUST_NOTIFY_MUTE='DEGRADED')
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up', 'probe ok')

    def test_the_mute_list_takes_several_classes_insensitively(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('DEGRADED', 200.0, message='tunnel not usable', detail='probe timed out')
        self.run_script(ATRUST_NOTIFY_MUTE='online, degraded')
        self.write_state('ONLINE', 300.0, message='tunnel up', detail='probe ok')
        self.run_script(ATRUST_NOTIFY_MUTE='online, degraded')
        self.assertEqual(self.notifications(), [])

        # a class outside the list still rings
        self.write_state('LOGGED_OUT', 400.0, message='the client has to log in again')
        result = self.run_script(ATRUST_NOTIFY_MUTE='online, degraded')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: session gone, logging in again',
                         'the client has to log in again')

    def test_need_vnc_can_be_muted_too(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('NEED_VNC', 200.0, message='waiting for a human in VNC')
        result = self.run_script(ATRUST_NOTIFY_MUTE='need_vnc')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'NEED_VNC\n200.0\n')

    def test_an_unknown_mute_class_is_a_warning_not_a_filter(self) -> None:
        self.write_marker('ONLINE', 100.0)
        self.write_state('DEGRADED', 200.0, message='tunnel not usable', detail='probe timed out')
        result = self.run_script(ATRUST_NOTIFY_MUTE='DEGRADED,LOUD')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unknown ATRUST_NOTIFY_MUTE class 'LOUD'", result.stderr)
        self.assertEqual(self.notifications(), [], 'the known class was not muted')


if __name__ == '__main__':
    unittest.main()
