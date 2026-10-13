# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The state directory is a host mount, so every file the engine writes in it is 0600.

`~/.atrust-data/run` is mounted into the container at `/run/atrustd` and is readable by every local
user of the host, while the files there carry the account name, the client's own view of the session
and, during a hand-over, the portal's captcha image. The writers are pinned under the umask the old
one was measured under (`022`, with which a plain `write_text` produced 0644) - the modes must hold
whatever the umask says.

Run: python3 -m unittest tests.test_state
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import apps  # noqa: E402
from atrustd.state import State, StateFile, Status  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16


class PrivateFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.umask = os.umask(0o022)
        self.addCleanup(os.umask, self.umask)

    def mode(self, path: Path) -> str:
        return '%o' % (path.stat().st_mode & 0o777)

    def write_everything(self) -> None:
        state_file = StateFile(self.dir)
        state_file.write(Status(state=State.NEED_VNC.value, message='waiting for a human'))
        state_file.set_vnc_hint('NEED_VNC: the portal is asking for a graphical captcha', PNG)
        apps.save(self.dir, [apps.App(name='a web app')])

    def test_every_file_in_the_state_directory_is_private(self) -> None:
        self.write_everything()
        self.assertEqual(sorted(path.name for path in self.dir.iterdir()),
                         ['NEED_VNC', 'apps.json', 'captcha.png', 'state.json'])
        for path in sorted(self.dir.iterdir()):
            self.assertEqual(self.mode(path), '600', '%s is %s' % (path.name, self.mode(path)))

    def test_the_atomic_temp_file_is_already_private_when_it_is_moved(self) -> None:
        """`state.json`/`apps.json` are replaced from a temp file: that file is 0600 as it lies."""
        modes: list[str] = []
        real_replace = Path.replace

        def spy(path: Path, target: Path) -> Path:
            modes.append('%o' % (path.stat().st_mode & 0o777))
            return real_replace(path, target)

        with mock.patch.object(Path, 'replace', spy):
            self.write_everything()
        self.assertEqual(modes, ['600', '600'])

    def test_a_file_an_older_version_left_readable_comes_back_private(self) -> None:
        path = self.dir / 'state.json'
        path.write_text('{}', encoding='utf-8')
        self.assertEqual(self.mode(path), '644')     # what the old writer left behind
        StateFile(self.dir).write(Status())
        self.assertEqual(self.mode(path), '600')

    def test_the_journal_facing_content_is_unchanged(self) -> None:
        """The mode is the only thing that moved: the files still read back."""
        self.write_everything()
        state = StateFile(self.dir).read()
        self.assertIsNotNone(state)
        self.assertEqual(state.state, State.NEED_VNC.value)
        self.assertIn('NEED_VNC:', (self.dir / 'NEED_VNC').read_text(encoding='utf-8'))
        self.assertEqual([app.name for app in apps.load(self.dir)], ['a web app'])


if __name__ == '__main__':
    unittest.main()
