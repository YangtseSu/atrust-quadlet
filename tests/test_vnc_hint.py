# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The NEED_VNC hint is read during an incident, so its commands have to be copy-pasteable.

The hint is built by `str.format`, and the TOTP block inside it is a template of its own - which is
how a literal `{container}` reached a hint that was otherwise complete (found by a smoke run, not by
a test). The commands are what the human executes while the session is down: a placeholder left in
one is worse than no line at all, so the shapes are pinned here.

Run: python3 -m unittest tests.test_vnc_hint
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import vnc  # noqa: E402
from atrustd.state import StateFile  # noqa: E402


class HintTest(unittest.TestCase):
    def hint(self, totp_key: str | None) -> str:
        environment = {name: value for name, value in os.environ.items()
                       if name != 'ATRUST_TOTP_KEY'}
        if totp_key is not None:
            environment['ATRUST_TOTP_KEY'] = totp_key
        with TemporaryDirectory() as tmp, mock.patch.dict(os.environ, environment, clear=True):
            state_file = StateFile(Path(tmp))
            path = vnc.hint(None, state_file, 'the portal is asking for a graphical captcha')
            return path.read_text(encoding='utf-8')

    def test_no_template_placeholder_survives(self) -> None:
        for key in (None, 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'):
            with self.subTest(key=key):
                text = self.hint(key)
                self.assertNotIn('{', text, 'a format placeholder reached the hint')
                self.assertNotIn('}', text)

    def test_the_commands_name_the_container(self) -> None:
        for key in (None, 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'):
            with self.subTest(key=key):
                text = self.hint(key)
                self.assertIn('vncviewer 127.0.0.1:5901', text)
                self.assertIn('podman exec', text)
                self.assertIn(vnc.CONTAINER, text)

    def test_the_totp_command_adapts_to_where_the_secret_lives(self) -> None:
        without = self.hint(None)
        self.assertIn('podman exec -e ATRUST_TOTP_KEY=<base32 secret> %s python3 -m atrustd --totp'
                      % vnc.CONTAINER, without)
        with_key = self.hint('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ')
        self.assertIn('podman exec %s python3 -m atrustd --totp' % vnc.CONTAINER, with_key)
        self.assertNotIn('-e ATRUST_TOTP_KEY', with_key)


if __name__ == '__main__':
    unittest.main()
