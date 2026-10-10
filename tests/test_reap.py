# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The PID 1 reaper must collect the dead, and only the dead.

`atrustd` is PID 1 in the container: the children of a swept tray (its Electron
helpers, the detached tunnel) reparent to it, and a PID 1 that never calls
`waitpid` keeps every one of them in the task list, counting against podman's
pids limit until nothing new can start. A regression here stays silent in a
quiet container and only bites after a long run, so the fork/die/collect
sequence is pinned instead.

Run: python3 -m unittest tests.test_reap
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd.__main__ import reap_orphans  # noqa: E402


class ReapTest(unittest.TestCase):
    def test_an_exited_child_is_collected(self) -> None:
        pid = os.fork()
        if pid == 0:  # the child only has to exist as a status
            os._exit(0)
        # WNOWAIT waits for the exit without collecting the status, so the
        # reaper has exactly one thing to collect and no timing to guess.
        os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
        self.assertGreaterEqual(reap_orphans(), 1, 'the exited child was not collected')
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)

    def test_nothing_to_reap_is_harmless(self) -> None:
        # No child at all: waitpid(-1) raises ChildProcessError, which must end
        # the loop instead of escaping it.
        self.assertEqual(reap_orphans(), 0)

    def test_a_live_child_keeps_its_status(self) -> None:
        """The reaper never waits on a live child, so a caller's own wait keeps working.

        The engine runs `ip`, `xdotool` and `xwd` through `subprocess.run`,
        which reads the exit status itself; a reaping that blocked on a live
        child (or ran as a `SIGCHLD` handler) would take that status away, and
        the probe errors would be the only sign.
        """
        proc = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(0.8); raise SystemExit(7)'])
        self.addCleanup(proc.wait)
        self.assertEqual(reap_orphans(), 0, 'the reaper touched a live child')
        self.assertEqual(proc.wait(), 7, 'the exit status did not reach its caller')


if __name__ == '__main__':
    unittest.main()
