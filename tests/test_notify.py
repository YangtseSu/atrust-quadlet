# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The notifier must fire once per transition - and only then.

A regression here is silent in both directions - a transition that never
reaches the desktop, or a 15 s poll that notifies the same state again and
again. The container side is stubbed: a fake `podman` serves a temporary state
directory, a fake `notify-send` records its argv and `date` answers a frozen
epoch, so the whole script runs without podman, without GNOME and without the
engine. The state file is written through `atrustd.state.Status.to_json()`: the
script's `field()` reads the shape that writer produces (indent=2, the key
names), so hand-building the JSON would let the two drift apart silently.

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

from atrustd.state import Status

SCRIPT = Path(__file__).resolve().parent.parent / 'quadlet' / 'atrust-notify.sh'

# The clock the `date` stub answers: a frozen epoch makes the outage duration and the staleness
# threshold exact instead of a race with the tick.
NOW = 1792120000

DATE_STUB = """#!/bin/sh
# the notifier asks for the epoch only; anything else is a change this suite should hear about
[ "$1" = '+%s' ] || { echo "date stub: unsupported arguments: $*" >&2; exit 2; }
printf '%s\\n' NOW_EPOCH
""".replace('NOW_EPOCH', str(NOW))

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
# One line per invocation: an argument's real newlines are logged as the two characters `\n`, so a
# multi-line body (a NEED_VNC may carry the browser line) stays one record. The id handling is the
# daemon's own rule (GNOME Shell 51's `notificationDaemon.js`): a non-zero `replaces_id` it knows
# is reused, anything else gets a fresh id - and the id it settled on is what `-p` prints.
for argument in "$@"; do
    printf '%s\t' "$(printf '%s' "$argument" | awk 'BEGIN{ORS=""} {print (NR>1 ? "\\n" : "") $0}')"
done >> "$NOTIFY_LOG"
printf '\n' >> "$NOTIFY_LOG"
icon=''
previous=''
replaces=0
for argument in "$@"; do
    if [ "$previous" = '-i' ]; then
        icon="$argument"
    fi
    if [ "$previous" = '-r' ]; then
        replaces="$argument"
    fi
    previous="$argument"
done
if [ -n "$icon" ]; then
    cp "$icon" "$NOTIFY_ICON_DIR/"
fi
if [ "$replaces" != 0 ] && [ -f "$NOTIFY_ID_DIR/$replaces" ]; then
    printf '%s\n' "$replaces"
    exit 0
fi
next=1
if [ -f "$NOTIFY_ID_DIR/counter" ]; then
    next=$(( $(cat "$NOTIFY_ID_DIR/counter") + 1 ))
fi
printf '%s\n' "$next" > "$NOTIFY_ID_DIR/counter"
: > "$NOTIFY_ID_DIR/$next"
printf '%s\n' "$next"
"""

# The ATRUST_NOTIFY_CMD contract is four positional arguments, so the stub logs the count beside
# them: an extra flag or a missing icon would change it.
CMD_STUB = r"""#!/bin/sh
printf '%s\t%s\t%s\t%s\t%s\n' "$#" "$1" "$2" "$3" "$4" >> "$NOTIFY_LOG"
"""


def jnum(value: float | int) -> str:
    """The marker holds the state file's own text, so the expectation comes from the same writer."""
    return json.dumps(value)


def lines(*body_lines: str) -> str:
    """The stub logs a body's real newline as `\\n`, so this is the expectation."""
    return '\\n'.join(body_lines)


class NotifyTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state_dir = self.root / 'state'
        self.runtime = self.root / 'run'
        self.icons = self.root / 'icons'
        self.bin = self.root / 'bin'
        self.ids = self.root / 'ids'
        for directory in (self.state_dir, self.runtime, self.icons, self.bin, self.ids):
            directory.mkdir()
        self.log = self.root / 'notify.log'
        self.install('notify-send', NOTIFY_STUB)
        self.install('podman', PODMAN_STUB)
        self.install('date', DATE_STUB)

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
            'NOTIFY_ID_DIR': str(self.ids),
            'ATRUST_TEST_STATE_DIR': str(self.state_dir),
            'PATH': os.pathsep.join([str(self.bin), os.defpath]),
            'XDG_RUNTIME_DIR': str(self.runtime),
        }
        env.update(extra)
        return env

    def run_script(self, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(SCRIPT)], env=self.env(**extra),
                              capture_output=True, text=True)

    def write_state(self, state: str, since: float | None = None, message: str = '',
                    detail: str = '', updated: float | int | None = None,
                    client: dict[str, str] | None = None) -> None:
        """The real writer decides the file's shape - the notifier reads what it writes."""
        status = Status(
            state=state,
            since=NOW - 30.0 if since is None else since,
            updated=NOW if updated is None else updated,
            message=message,
            detail=detail,
            client={} if client is None else client,
        )
        (self.state_dir / 'state.json').write_text(status.to_json())

    def write_marker(self, state: str, since: float, stale: str = '-') -> None:
        (self.runtime / 'atrust-notify.last').write_text(
            '%s\n%s\n%s\n' % (state, jnum(since), stale))

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
                    klass: str, icon: bytes | None = None) -> None:
        self.assertEqual(argv[-3:], ['--', title, body])
        self.assertEqual(argv[argv.index('-a') + 1], 'aTrust')
        self.assertEqual(argv[argv.index('-u') + 1], urgency)
        # `-p` is what lets the id of this class be remembered, `-r` is what replaces it next time
        self.assertIn('-p', argv, 'the notification id was not asked for')
        self.assertRegex(argv[argv.index('-r') + 1], r'^[0-9]+$')
        ids = self.notification_ids()
        self.assertIn(klass, ids, 'the id of class %s was not remembered' % klass)
        self.assertRegex(ids[klass], r'^[0-9]+$')
        if icon is None:
            self.assertNotIn('-i', argv)
        else:
            copied = list(self.icons.iterdir())
            self.assertEqual(len(copied), 1, 'the icon did not reach notify-send')
            self.assertEqual(copied[0].read_bytes(), icon)

    def notification_ids(self) -> dict[str, str]:
        """The class -> id lines the notifier keeps beside its marker."""
        path = self.runtime / 'atrust-notify.ids'
        if not path.exists():
            return {}
        return dict(line.split() for line in path.read_text().splitlines())

    # --- the transitions ------------------------------------------------------

    def test_the_first_run_seeds_the_marker_silently(self) -> None:
        self.write_state('ONLINE', since=NOW - 30.0, detail='utun7 2.0.0.1/24; probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n%s\n-\n' % jnum(NOW - 30.0))

    def test_a_poll_that_sees_the_same_state_is_silent(self) -> None:
        self.write_state('ONLINE', since=NOW - 30.0, detail='utun7 2.0.0.1/24; probe ok')
        self.run_script()  # seeds the marker
        # the engine rewrites the file every cycle: same state and since, new `updated` and detail
        self.write_state('ONLINE', since=NOW - 30.0, updated=NOW + 15,
                         detail='utun7 2.0.0.1/24; probe ok, a cycle later')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [], 'the same (state, since) was notified twice')

    def test_the_tunnel_going_down_notifies_once(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('DEGRADED', since=NOW, message='tunnel not usable',
                         detail='utun7 2.0.0.1/24; probe timed out')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is not usable',
                         'utun7 2.0.0.1/24; probe timed out', klass='DEGRADED')
        self.assertEqual(self.marker(), 'DEGRADED\n%s\n-\n' % jnum(NOW))

    def test_the_tunnel_coming_back_notifies_once(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('ONLINE', since=NOW, message='tunnel up',
                         detail='utun7 2.0.0.1/24; 30 route(s) via utun7; probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         lines('tunnel up (down 30 s)',
                               'utun7 2.0.0.1/24; 30 route(s) via utun7; probe ok'), klass='ONLINE')

    def test_the_recovery_leads_with_the_message_and_keeps_the_detail(self) -> None:
        self.write_marker('LOGGED_OUT', NOW - 300.0)
        self.write_state('ONLINE', since=NOW, message='tunnel up after the ticket login',
                         detail='utun7 2.0.0.1/24; probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         lines('tunnel up after the ticket login (down 5 min)',
                               'utun7 2.0.0.1/24; probe ok'), klass='ONLINE')

    def test_an_online_without_a_message_falls_back_to_the_detail_once(self) -> None:
        self.write_marker('DEGRADED', NOW - 45.0)
        self.write_state('ONLINE', since=NOW, detail='utun7 2.0.0.1/24; probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         'utun7 2.0.0.1/24; probe ok (down 45 s)', klass='ONLINE')

    # --- the client's own view -------------------------------------------------

    def test_the_client_view_rides_in_the_recovery_body(self) -> None:
        self.write_marker('DEGRADED', NOW - 42.0)
        self.write_state('ONLINE', since=NOW, message='tunnel up after the ticket login',
                         detail='utun7 2.0.0.1/24; probe ok',
                         client={'state': 'online', 'tunnel': 'tunnelAvailable',
                                 'user': '<user>', 'login': '2026-10-16 09:06:38'})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         lines('tunnel up after the ticket login (down 42 s)',
                               'client online/tunnelAvailable user=<user> since=2026-10-16 09:06:38',
                               'utun7 2.0.0.1/24; probe ok'), klass='ONLINE')

    def test_the_client_view_rides_in_the_logged_out_body(self) -> None:
        self.write_marker('ONLINE', NOW - 100.0)
        self.write_state('LOGGED_OUT', since=NOW, message='the client has to log in again',
                         detail='client logout/tunnelUnavailable; not restarting it',
                         client={'error': 'Connection refused'})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: session gone, logging in again',
                         lines('client logout/tunnelUnavailable; not restarting it',
                               'client unreachable: Connection refused'), klass='LOGGED_OUT')

    def test_a_client_view_without_a_user_omits_the_field(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('ONLINE', since=NOW, message='tunnel up', detail='probe ok',
                         client={'state': 'online', 'tunnel': 'tunnelAvailable'})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         lines('tunnel up (down 30 s)', 'client online/tunnelAvailable', 'probe ok'),
                         klass='ONLINE')

    def test_a_client_object_of_an_older_container_is_simply_absent(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('ONLINE', since=NOW, message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         lines('tunnel up (down 30 s)', 'probe ok'), klass='ONLINE')

    def test_a_degraded_body_keeps_the_probe_detail(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('DEGRADED', since=NOW, message='tunnel not usable', detail='probe ok',
                         client={'state': 'online', 'tunnel': 'tunnelAvailable', 'user': '<user>'})
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is not usable',
                         'probe ok', klass='DEGRADED')

    # --- the state file that stopped moving ------------------------------------

    def test_an_unmoving_state_file_rings_once(self) -> None:
        self.write_marker('ONLINE', NOW - 3600.0)
        self.write_state('ONLINE', since=NOW - 3600.0, updated=NOW - 600,
                         message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: supervisor silent',
                         lines('no state update for 10 min: the last state it published is ONLINE',
                               'the container or its supervisor is stopped '
                               '(systemctl --user status atrust.service)'), klass='STALE')
        self.assertEqual(self.marker(),
                         'ONLINE\n%s\n%s\n' % (jnum(NOW - 3600.0), jnum(NOW - 600)))

        # the frozen `updated` does not move on its own: the next tick that sees it is silent
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.notifications()), 1, 'a stopped supervisor rang twice')

    def test_a_freshened_file_re_arms_the_staleness(self) -> None:
        self.write_marker('ONLINE', NOW - 3600.0, stale=jnum(NOW - 600))
        self.write_state('ONLINE', since=NOW - 3600.0, message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [], 'a file that freshened rang')
        self.assertEqual(self.marker(), 'ONLINE\n%s\n-\n' % jnum(NOW - 3600.0),
                         'the marker kept the stale decision of the previous freeze')

        # a second freeze rings again, for its own `updated`
        self.write_state('ONLINE', since=NOW - 3600.0, updated=NOW - 500,
                         message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: supervisor silent',
                         lines('no state update for 8 min: the last state it published is ONLINE',
                               'the container or its supervisor is stopped '
                               '(systemctl --user status atrust.service)'), klass='STALE')

    def test_a_stale_file_that_comes_back_reports_the_live_state(self) -> None:
        self.write_marker('ONLINE', NOW - 3600.0, stale=jnum(NOW - 600))
        # the supervisor is back and the tunnel never left: the recovery of the file is not a
        # tunnel announcement, but the marker must leave the stale decision behind
        self.write_state('ONLINE', since=NOW - 3600.0, message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n%s\n-\n' % jnum(NOW - 3600.0))

    def test_a_state_shorter_than_the_threshold_does_not_ring_it(self) -> None:
        self.write_marker('DEGRADED', NOW - 60.0)
        self.write_state('ONLINE', since=NOW - 60.0, updated=NOW - 299,
                         message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         lines('tunnel up (down 60 s)', 'probe ok'), klass='ONLINE')

    def test_the_stale_threshold_can_be_turned_off(self) -> None:
        self.write_marker('ONLINE', NOW - 3600.0)
        self.write_state('ONLINE', since=NOW - 3600.0, updated=NOW - 600)
        result = self.run_script(ATRUST_NOTIFY_STALE_AFTER='0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])

    def test_the_stale_threshold_is_honoured(self) -> None:
        self.write_marker('ONLINE', NOW - 3600.0)
        self.write_state('ONLINE', since=NOW - 3600.0, updated=NOW - 600)
        result = self.run_script(ATRUST_NOTIFY_STALE_AFTER='900')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [], 'a file younger than the threshold rang')

    def test_a_non_numeric_threshold_is_a_warning_not_a_failure(self) -> None:
        self.write_marker('ONLINE', NOW - 3600.0)
        self.write_state('ONLINE', since=NOW - 3600.0, updated=NOW - 600)
        result = self.run_script(ATRUST_NOTIFY_STALE_AFTER='soon')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ATRUST_NOTIFY_STALE_AFTER='soon' is not a number of seconds",
                      result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: supervisor silent',
                         lines('no state update for 10 min: the last state it published is ONLINE',
                               'the container or its supervisor is stopped '
                               '(systemctl --user status atrust.service)'), klass='STALE')

    def test_the_stale_class_can_be_muted(self) -> None:
        self.write_marker('ONLINE', NOW - 3600.0)
        self.write_state('ONLINE', since=NOW - 3600.0, updated=NOW - 600)
        result = self.run_script(ATRUST_NOTIFY_MUTE='STALE')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(),
                         'ONLINE\n%s\n%s\n' % (jnum(NOW - 3600.0), jnum(NOW - 600)),
                         'the muted class did not move the marker')

    def test_a_pending_staleness_is_not_seeded_silently(self) -> None:
        self.write_state('ONLINE', since=NOW - 3600.0, updated=NOW - 600)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: supervisor silent',
                         lines('no state update for 10 min: the last state it published is ONLINE',
                               'the container or its supervisor is stopped '
                               '(systemctl --user status atrust.service)'), klass='STALE')

    # --- NEED_VNC --------------------------------------------------------------

    def test_need_vnc_carries_the_hint_the_captcha_and_critical_urgency(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
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
                         'window over VNC', klass='NEED_VNC', icon=captcha)
        self.assertEqual(self.marker(), 'NEED_VNC\n%s\n-\n' % jnum(NOW))
        self.assertEqual(sorted(p.name for p in self.runtime.iterdir()),
                         ['atrust-notify.ids', 'atrust-notify.last'],
                         'the captcha copy was left behind')

    def test_need_vnc_without_a_captcha_falls_back_to_the_message(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: human action required',
                         'waiting for a human in VNC', klass='NEED_VNC')

    def test_the_recovery_from_need_vnc_notifies(self) -> None:
        self.write_marker('NEED_VNC', NOW - 30.0)
        self.write_state('ONLINE', since=NOW, message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         lines('tunnel up (down 30 s)', 'probe ok'), klass='ONLINE')

    def test_a_pending_need_vnc_is_not_seeded_silently(self) -> None:
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text(
            'NEED_VNC: the portal is asking for the graphical captcha\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: human action required',
                         'the portal is asking for the graphical captcha', klass='NEED_VNC')

    # The default for the browser line is `auto`: it derives the portal address from
    # ~/.config/atrust.env and probes the host ports. This suite's HOME is a scratch directory with
    # no env file, so nothing is derived and nothing is probed - which is why the NEED_VNC tests
    # above assert a body without the line, and why the two cases that need the line name it
    # explicitly.

    def test_need_vnc_names_the_browser_when_it_is_configured_to(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text('NEED_VNC: the portal asks for a captcha\n')
        result = self.run_script(ATRUST_NOTIFY_WORKBENCH='https://portal.example.test/')
        self.assertEqual(result.returncode, 0, result.stderr)
        # the stub logs the body's real newline as the two characters `\n`
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: human action required',
                         'the portal asks for a captcha\\n'
                         'or finish the login in your browser: https://portal.example.test/',
                         klass='NEED_VNC')

    def test_need_vnc_can_be_told_to_never_mention_a_browser(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text('NEED_VNC: the portal asks for a captcha\n')
        result = self.run_script(ATRUST_NOTIFY_WORKBENCH='no')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: human action required',
                         'the portal asks for a captcha', klass='NEED_VNC')

    # --- the held class: a refused credential or a lockout -----------------------

    def test_a_refused_password_gets_its_own_title(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text(
            'NEED_VNC: the portal refused the password login (wrong-password, 3 attempts left): '
            'The username or password is incorrect; the engine will not retry it until the tunnel '
            'is up or the service restarts - fix the credential and test it once with '
            '`podman exec atrust python3 -m atrustd --login-probe`\n')
        result = self.run_script(ATRUST_NOTIFY_WORKBENCH='https://portal.example.test/')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical',
                         'aTrust: password refused, 3 attempts left',
                         'the portal refused the password login (wrong-password, 3 attempts left): '
                         'The username or password is incorrect; the engine will not retry it '
                         'until the tunnel is up or the service restarts - fix the credential and '
                         'test it once with `podman exec atrust python3 -m atrustd --login-probe`',
                         klass='NEED_VNC')

    def test_a_lockout_without_a_counter_gets_the_plain_title(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text(
            'NEED_VNC: the portal refused the password login (rate-limited): too many login '
            'failures; the engine will not retry it\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical', 'aTrust: password refused',
                         'the portal refused the password login (rate-limited): too many login '
                         'failures; the engine will not retry it', klass='NEED_VNC')

    def test_a_counter_inside_the_portals_own_row_is_not_the_headline(self) -> None:
        # the portal's row carries `You still have 9 attempts left` without a comma before it;
        # the engine's own counter is the one in the parenthesis
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text(
            'NEED_VNC: the portal refused the password login (wrong-password, 2 attempts left): '
            'The username or password is incorrect. You still have 9 attempts left\n')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'critical',
                         'aTrust: password refused, 2 attempts left',
                         'the portal refused the password login (wrong-password, 2 attempts left): '
                         'The username or password is incorrect. You still have 9 attempts left',
                         klass='NEED_VNC')

    # --- the transport ---------------------------------------------------------

    def test_a_repeated_class_takes_its_own_notification_back(self) -> None:
        self.write_marker('ONLINE', NOW - 60.0)
        self.write_state('DEGRADED', since=NOW - 30.0, detail='probe timed out')
        self.run_script()
        self.write_state('ONLINE', since=NOW, message='tunnel up', detail='probe ok')
        self.run_script()
        self.assertEqual(self.notification_ids(), {'DEGRADED': '1', 'ONLINE': '2'})

        # the same class again: the call carries the id that class already used, so the daemon
        # replaces its own notification instead of stacking a new one
        self.write_state('DEGRADED', since=NOW + 30.0, detail='probe timed out again')
        self.run_script()
        argv = self.notifications()[-1]
        self.assertEqual(argv[argv.index('-r') + 1], '1')
        self.assertEqual(self.notification_ids(), {'DEGRADED': '1', 'ONLINE': '2'},
                         'the replaced class grew a second id')

    def test_a_different_class_does_not_take_another_class_notification(self) -> None:
        self.write_marker('ONLINE', NOW - 3600.0)
        self.write_state('ONLINE', since=NOW - 3600.0, updated=NOW - 600)
        self.run_script()
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        self.run_script()
        argv = self.notifications()[-1]
        self.assertEqual(argv[argv.index('-r') + 1], '0', 'a new class reused another class id')
        self.assertEqual(self.notification_ids(), {'STALE': '1', 'NEED_VNC': '2'})

    def test_a_custom_command_gets_four_arguments(self) -> None:
        wrapper = self.bin / 'notify-wrapper'
        wrapper.write_text(CMD_STUB)
        wrapper.chmod(0o755)
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('DEGRADED', since=NOW, detail='probe timed out')
        result = self.run_script(ATRUST_NOTIFY_CMD=str(wrapper))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(),
                         '4\tnormal\taTrust: tunnel is not usable\tprobe timed out\t\n')

    def test_a_custom_command_gets_the_icon_path_it_can_use(self) -> None:
        wrapper = self.bin / 'notify-wrapper'
        wrapper.write_text(CMD_STUB)
        wrapper.chmod(0o755)
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        (self.state_dir / 'NEED_VNC').write_text('NEED_VNC: the portal asks for a captcha\n')
        (self.state_dir / 'captcha.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 8)
        result = self.run_script(ATRUST_NOTIFY_CMD=str(wrapper),
                                 ATRUST_STATE_HOST_DIR=str(self.state_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = self.log.read_text().strip().split('\t')
        self.assertEqual(fields[:4], ['4', 'critical', 'aTrust: human action required',
                                      'the portal asks for a captcha'])
        self.assertEqual(fields[4], str(self.state_dir / 'captcha.png'))

    def test_a_failing_command_is_reported_and_the_marker_stays(self) -> None:
        wrapper = self.bin / 'notify-wrapper'
        wrapper.write_text('#!/bin/sh\nexit 3\n')
        wrapper.chmod(0o755)
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('DEGRADED', since=NOW, detail='probe timed out')
        result = self.run_script(ATRUST_NOTIFY_CMD=str(wrapper))
        self.assertEqual(result.returncode, 1)
        self.assertIn('notify-wrapper failed, retrying on the next run', result.stderr)
        self.assertEqual(self.marker(), 'ONLINE\n%s\n-\n' % jnum(NOW - 30.0),
                         'a failed notification moved the marker')

    def test_the_marker_and_the_ids_are_private(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('ONLINE', since=NOW, message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('atrust-notify.last', 'atrust-notify.ids'):
            path = self.runtime / name
            self.assertTrue(path.exists(), name)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600,
                             '%s carries the deployment state and must not be world readable' % name)

    # --- the mute filter ------------------------------------------------------

    def test_a_muted_class_is_silent_and_still_moves_the_marker(self) -> None:
        self.write_marker('ONLINE', NOW - 60.0)
        self.write_state('DEGRADED', since=NOW - 30.0, message='tunnel not usable',
                         detail='probe timed out')
        result = self.run_script(ATRUST_NOTIFY_MUTE='DEGRADED')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'DEGRADED\n%s\n-\n' % jnum(NOW - 30.0),
                         'a muted class did not move the marker')

        # the recovery is not muted and must not be swallowed by the silent degradation
        self.write_state('ONLINE', since=NOW, message='tunnel up', detail='probe ok')
        self.run_script(ATRUST_NOTIFY_MUTE='DEGRADED')
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is up',
                         lines('tunnel up (down 30 s)', 'probe ok'), klass='ONLINE')

    def test_the_mute_list_takes_several_classes_insensitively(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('DEGRADED', since=NOW, message='tunnel not usable', detail='probe timed out')
        self.run_script(ATRUST_NOTIFY_MUTE='online, degraded')
        self.write_state('ONLINE', since=NOW + 30.0, message='tunnel up', detail='probe ok')
        self.run_script(ATRUST_NOTIFY_MUTE='online, degraded')
        self.assertEqual(self.notifications(), [])

        # a class outside the list still rings
        self.write_state('LOGGED_OUT', since=NOW + 60.0, message='the client has to log in again')
        result = self.run_script(ATRUST_NOTIFY_MUTE='online, degraded')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: session gone, logging in again',
                         'the client has to log in again', klass='LOGGED_OUT')

    def test_need_vnc_can_be_muted_too(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
        result = self.run_script(ATRUST_NOTIFY_MUTE='need_vnc')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'NEED_VNC\n%s\n-\n' % jnum(NOW))

    def test_an_unknown_mute_class_is_a_warning_not_a_filter(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('DEGRADED', since=NOW, message='tunnel not usable', detail='probe timed out')
        result = self.run_script(ATRUST_NOTIFY_MUTE='DEGRADED,LOUD')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unknown ATRUST_NOTIFY_MUTE class 'LOUD'", result.stderr)
        self.assertEqual(self.notifications(), [], 'the known class was not muted')

    # --- the states this script only records ------------------------------------

    def test_a_daemon_restart_does_not_announce_the_tunnel_again(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        # a recreated container loses the state file, so the fresh daemon writes ONLINE with a new
        # `since`: the tunnel never left, and must not be announced
        self.write_state('ONLINE', since=NOW, message='tunnel up', detail='probe ok')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n%s\n-\n' % jnum(NOW))

    def test_a_state_it_does_not_know_is_recorded_without_a_notification(self) -> None:
        self.write_marker('DEGRADED', NOW - 30.0)
        self.write_state('STARTING', since=NOW)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'STARTING\n%s\n-\n' % jnum(NOW))

    # --- the host without a container -----------------------------------------

    def test_a_missing_container_is_silence(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        result = self.run_script(ATRUST_TEST_NO_CONTAINER='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n%s\n-\n' % jnum(NOW - 30.0))

    def test_a_host_without_podman_is_silence(self) -> None:
        (self.bin / 'podman').unlink()
        for tool in ('sed', 'head', 'cat', 'mv', 'rm', 'tr'):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.write_marker('ONLINE', NOW - 30.0)
        result = subprocess.run([str(SCRIPT)], capture_output=True, text=True,
                                env={'HOME': str(self.root), 'PATH': str(self.bin),
                                     'XDG_RUNTIME_DIR': str(self.runtime)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.marker(), 'ONLINE\n%s\n-\n' % jnum(NOW - 30.0))

    # --- the mounted state directory ------------------------------------------

    def test_the_mount_is_read_without_podman(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('DEGRADED', since=NOW, message='tunnel not usable', detail='probe timed out')
        result = self.run_script(ATRUST_STATE_HOST_DIR=str(self.state_dir),
                                 ATRUST_TEST_NO_CONTAINER='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is not usable',
                         'probe timed out', klass='DEGRADED')

    def test_the_mounted_captcha_is_used_in_place_and_kept(self) -> None:
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('NEED_VNC', since=NOW, message='waiting for a human in VNC')
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
        self.write_marker('ONLINE', NOW - 30.0)
        self.write_state('DEGRADED', since=NOW, message='tunnel not usable', detail='probe timed out')
        empty = self.root / 'empty-mount'
        empty.mkdir()
        result = self.run_script(ATRUST_STATE_HOST_DIR=str(empty))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_sent(self.only_notification(), 'normal', 'aTrust: tunnel is not usable',
                         'probe timed out', klass='DEGRADED')


if __name__ == '__main__':
    unittest.main()
