# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The fake loginctl must answer the shapes the client's helpers ask.

The client reaches this shim in four ways - two from its own shell scripts
(`aTrustTrayStart.sh`, `aTrustShellExec.sh`), two from
`get_current_user_session.sh`, which `plugins/aTrustCore/libEAIOSDKWrapper.so`
calls. Two of them used to be answered with an exit 1 and a whole session dump,
which is silent in production: the helper asks, gets nothing and carries on
without a session. The shapes are pinned here so that cannot come back.

Run: python3 -m unittest tests.test_loginctl_shim
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SHIM = Path(__file__).resolve().parent.parent / 'base' / 'overlay' / 'loginctl'


class LoginctlShimTest(unittest.TestCase):
    def setUp(self) -> None:
        # The shim creates the `sangfor` account when it is missing: stub
        # `useradd` out of the way, a test must never touch the machine's users.
        stub = TemporaryDirectory()
        self.addCleanup(stub.cleanup)
        useradd = Path(stub.name) / 'useradd'
        useradd.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
        useradd.chmod(0o755)
        self.env = dict(os.environ, PATH='%s:%s' % (stub.name, os.environ.get('PATH', '')))

    def shim(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(['sh', str(SHIM), *args], capture_output=True, text=True, env=self.env)

    def test_list_sessions_in_every_spelling(self) -> None:
        for args in (['list-sessions'], ['--no-legend', 'list-sessions'], ['-n', 'list-sessions']):
            out = self.shim(*args)
            self.assertEqual((out.stdout, out.returncode), ('10644 1234 sangfor seat0\n', 0), args)

    def test_show_session_is_a_key_value_block(self) -> None:
        # aTrustTrayStart.sh / aTrustShellExec.sh read it into a bash associative
        # array and check Type and Display.
        out = self.shim('show-session', '10644')
        self.assertEqual(out.returncode, 0)
        props = dict(line.split('=', 1) for line in out.stdout.splitlines())
        self.assertEqual(props['Display'], ':1')
        self.assertEqual(props['Type'], 'x11')
        self.assertEqual(props['Class'], 'user')
        self.assertEqual(props['Active'], 'yes')
        self.assertEqual(props['Name'], 'sangfor')

    def test_one_property_at_a_time(self) -> None:
        # get_current_user_session.sh pipes the answer through awk -F= '{print $2}':
        # more than the asked-for property is not a session id.
        for args, want in ((('show-session', '-p', 'Display', '10644'), 'Display=:1\n'),
                           (('show-session', '-p', 'Leader', '10644'), 'Leader=2268286\n'),
                           (('--property=Type', 'show-session', '10644'), 'Type=x11\n')):
            out = self.shim(*args)
            self.assertEqual((out.stdout, out.returncode), (want, 0), args)

    def test_value_only(self) -> None:
        out = self.shim('show-session', '-p', 'Type', '--value', '10644')
        self.assertEqual((out.stdout, out.returncode), ('x11\n', 0))

    def test_a_verb_it_does_not_model_exits_one(self) -> None:
        out = self.shim('list-users')
        self.assertEqual((out.stdout, out.returncode), ('', 1))


if __name__ == '__main__':
    unittest.main()
