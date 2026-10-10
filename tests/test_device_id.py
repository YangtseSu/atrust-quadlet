# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The reported device id belongs to the deployment, not to the image.

The published image ships one /etc/machine-id that every container built from it
shares (and every rebuild replaces), so the id this client reports as `x-sdp-env`
comes from somewhere else: the state directory's `device-id`, generated on first
use, with ATRUST_DEVICE_ID as the explicit override. The machine id stays the last
resort for a state directory that cannot be written.

Run: python3 -m unittest tests.test_device_id
"""
from __future__ import annotations

import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import portal  # noqa: E402
from atrustd.config import Config  # noqa: E402

ID_RE = re.compile(r'^00-[0-9a-f]{40}$')


def make_client(state_dir: Path, device_id: str = '') -> portal.PortalClient:
    cfg = Config(portal_url='https://vpn.example.com/', username='u', password='p',
                 state_dir=state_dir, device_id=device_id)
    return portal.PortalClient(cfg)


class DeviceIdTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_explicit_id_wins_without_touching_the_state(self) -> None:
        client = make_client(self.dir, device_id='00-' + 'ab' * 20)
        self.assertEqual(client._device_id(), '00-' + 'ab' * 20)
        self.assertFalse((self.dir / 'device-id').exists())

    def test_generated_once_and_kept_for_the_next_client(self) -> None:
        first = make_client(self.dir)._device_id()
        self.assertRegex(first, ID_RE)
        self.assertEqual((self.dir / 'device-id').read_text(encoding='utf-8').strip(), first)
        self.assertEqual(make_client(self.dir)._device_id(), first)

    def test_an_existing_file_is_used_as_it_is(self) -> None:
        (self.dir / 'device-id').write_text('00-' + 'cd' * 20 + '\n', encoding='utf-8')
        self.assertEqual(make_client(self.dir)._device_id(), '00-' + 'cd' * 20)

    def test_a_concurrent_first_use_keeps_the_winner(self) -> None:
        path = self.dir / 'device-id'
        path.write_text('00-' + 'ef' * 20 + '\n', encoding='utf-8')
        self.assertEqual(portal._keep_device_id(path, '00-' + '11' * 20), '00-' + 'ef' * 20)

    def test_the_machine_id_is_only_the_last_resort(self) -> None:
        machine = self.dir / 'machine-id'
        machine.write_text('0123456789abcdef0123456789abcdef\n', encoding='utf-8')
        original = portal.MACHINE_ID_FILES
        portal.MACHINE_ID_FILES = (str(machine),)
        self.addCleanup(setattr, portal, 'MACHINE_ID_FILES', original)
        # a state directory whose parent is a regular file cannot be created
        blocked = self.dir / 'file' / 'run'
        (self.dir / 'file').write_text('', encoding='utf-8')
        client = make_client(blocked)
        expected = '00-%s' % hashlib.sha1(b'0123456789abcdef0123456789abcdef').hexdigest()
        self.assertEqual(client._device_id(), expected)
        self.assertEqual(client._device_id(), expected)


if __name__ == '__main__':
    unittest.main()
