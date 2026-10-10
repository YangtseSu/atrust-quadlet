# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The client-family sweep must take the family and nothing else.

`stop_client_family()` is what the daemon runs on its way out of the container:
SIGTERM to the client, SIGKILL for what is left, and only then the cgroup's
SIGKILL. A regression here is silent in both directions - a pattern that no
longer matches leaves the client to the cgroup, one that is too broad kills a
process that is not the client - so the family patterns are swapped for
throwaway ones and real processes carry the test.

Run: python3 -m unittest tests.test_stop_family
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import tokens  # noqa: E402

# `bash -c SCRIPT NAME` makes NAME the shell's $0, and `exec -a` keeps it as
# the command line of the program that is exec'd - which is what the sweep
# matches on (the kernel truncates the command *name* to 15 characters, so a
# path pattern is the only reliable handle on aTrustXtunnel-64).
EXEC = ['bash', '-c', 'exec -a "$0" sleep 30']
IGNORES_TERM = ['bash', '-c', 'trap "" TERM; exec -a "$0" sleep 30']


class StopFamilyTest(unittest.TestCase):
    def setUp(self) -> None:
        # Never the production patterns: a client may be running on this
        # machine (a container's processes are visible in the host namespace).
        self.pattern = 'atrustd-family-test-%d' % os.getpid()
        patcher = mock.patch.object(tokens, 'CLIENT_FAMILY', (self.pattern,))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.processes: list[subprocess.Popen] = []

    def spawn(self, argv: list[str], name: str) -> subprocess.Popen:
        proc = subprocess.Popen(argv + [name])
        self.processes.append(proc)
        self.addCleanup(self.reap, proc)
        return proc

    @staticmethod
    def reap(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()
        proc.wait()

    def test_sigterm_then_sigkill_and_no_collateral(self) -> None:
        sensitive = self.spawn(EXEC, self.pattern)
        immune = self.spawn(IGNORES_TERM, self.pattern)
        # A name the pattern must not match: the sweep is name based and the
        # client shares the container with the proxies and the X server.
        control = self.spawn(EXEC, 'atrustd-control-%d' % os.getpid())

        self.assertTrue(tokens.stop_client_family(timeout=0.6),
                        'the sweep reported survivors')
        self.assertEqual(sensitive.poll(), -signal.SIGTERM, 'the client was SIGKILLed outright')
        self.assertEqual(immune.poll(), -signal.SIGKILL, 'the survivor was not SIGKILLed')
        self.assertIsNone(control.poll(), 'the sweep killed a process outside the family')


if __name__ == '__main__':
    unittest.main()
