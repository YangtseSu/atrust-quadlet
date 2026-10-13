# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`atrustd --bundle`: one tarball of a bump's own evidence, and the secrets it must not carry.

A bundle is what is read after a client bump went wrong, and the copy may be handed to someone else -
so the membership is pinned (every enumerated member, and only those), the mode is pinned (0600, the
file and its members: `state.json` carries the account name), and the two things that must never be
in it - the deployment's `device-id` and the client's cookie store, whose `tid`/`tid.sig` are session
credentials - are asserted absent by value, not only by name.

The log member is a *tail*: the profile grows ~0.2 GB/day (B02) and the tray's daily file is the one
series without a rotation ceiling, so the bound is pinned here (the member is the last
`LOG_TAIL_BYTES` of the newest `aTrustTray*.log`), together with the rule that it is the newest file
that is read.

Run: python3 -m unittest tests.test_bundle
"""
from __future__ import annotations

import os
import sys
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import bundle  # noqa: E402
from atrustd.clientapi import ClientAPIError  # noqa: E402
from atrustd.config import Config  # noqa: E402

# 2026-10-13T14:20:00Z: a fixed clock, so the tarball's own name and its members' mtimes are pinned.
WHEN = 1791901200
DEVICE_ID = '00-' + 'ab' * 20
TOKEN = 'SECRET-TID-VALUE'


class FakeAPI:
    """The client's own service as the bundle uses it: a few reads, or a refusal."""

    def __init__(self, answers: dict[str, dict] | None = None):
        self.answers = dict(answers or {})
        self.calls: list[str] = []

    def session(self, path, data=None):
        self.calls.append(path)
        if path not in self.answers:
            raise ClientAPIError('the client service is not listening (54630)')
        return self.answers[path]


class BundleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.logs = self.root / 'logs'
        self.logs.mkdir()
        self.addr = self.root / 'addr.conf'
        self.version = self.root / 'atrust-version'
        self.cookies = self.root / 'Cookies'

    def config(self, **overrides) -> Config:
        fields = dict(portal_url='https://portal.example/', username='<account>', password='<pw>',
                      state_dir=self.state, client_log_dir=self.logs, client_addr_conf=self.addr,
                      client_version_file=self.version, client_cookie_db=self.cookies)
        fields.update(overrides)
        return Config(**fields)

    def write(self, cfg=None, api=None) -> Path:
        with mock.patch.object(bundle.probe, 'route_lines',
                               return_value=(['10.0.0.10 dev utun7'], '1 route(s) via utun7')):
            return bundle.write(cfg or self.config(), api=api, now=WHEN)

    def members(self, path: Path) -> dict[str, bytes]:
        with tarfile.open(path) as tar:
            return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}

    def modes(self, path: Path) -> dict[str, int]:
        with tarfile.open(path) as tar:
            return {m.name: m.mode for m in tar.getmembers()}

    def full_state(self) -> FakeAPI:
        (self.state / 'state.json').write_text('{"state": "NEED_VNC"}')
        (self.state / 'NEED_VNC').write_text('NEED_VNC: the portal is asking for the captcha\n')
        (self.state / 'captcha.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 64)
        (self.state / 'device-id').write_text(DEVICE_ID + '\n')
        self.cookies.write_bytes(('tid=' + TOKEN).encode())
        (self.logs / 'aTrustTray20261013.log').write_text('getHistoryAddr: portal\n')
        self.addr.write_text('https://portal.example:4430')
        self.version.write_text('2.5.16.41\n')
        return FakeAPI({
            '/v1/service/status': {'code': 0, 'data': {'status': 'online',
                                                      'data': {'tunnelStatus': 'tunnelAvailable'}}},
            '/v1/service/init': {'code': 0, 'data': {'status': 'otherSdpCLogin',
                                                     'clientVersion': '2.5.16.41'}},
        })

    def test_the_membership_and_the_mode(self) -> None:
        path = self.write(api=self.full_state())
        self.assertEqual(path.name, 'atrust-bundle-20261013-142000.tar.gz')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        members = self.members(path)
        self.assertEqual(sorted(members), [
            'client/addr.conf',
            'client/log-tail.txt',
            'client/status.json',
            'engine/NEED_VNC',
            'engine/captcha.png',
            'engine/routes.txt',
            'engine/state.json',
            'manifest.txt',
            'system/atrust-version',
        ])
        self.assertEqual(members['engine/state.json'], b'{"state": "NEED_VNC"}')
        self.assertEqual(members['engine/NEED_VNC'],
                         b'NEED_VNC: the portal is asking for the captcha\n')
        self.assertEqual(members['engine/captcha.png'], b'\x89PNG\r\n\x1a\n' + b'x' * 64)
        self.assertEqual(members['engine/routes.txt'], b'10.0.0.10 dev utun7')
        self.assertEqual(members['client/addr.conf'], b'https://portal.example:4430')
        self.assertEqual(members['system/atrust-version'], b'2.5.16.41\n')
        self.assertEqual(members['client/status.json'],
                         b'{\n  "code": 0,\n  "data": {\n    "status": "online",\n'
                         b'    "data": {\n      "tunnelStatus": "tunnelAvailable"\n    }\n  }\n}\n')
        for name, mode in self.modes(path).items():
            self.assertEqual(mode, 0o600, name)
        # The bundle is read after a bump went wrong, so its manifest is its own explanation.
        manifest = members['manifest.txt'].decode('utf-8')
        self.assertIn('atrustd bundle, created 2026-10-13T14:20:00Z', manifest)
        self.assertRegex(manifest, r'client image\s+2\.5\.16\.41')
        self.assertRegex(manifest, r'running client\s+2\.5\.16\.41 \(its own /v1/service/init answer\)')
        self.assertRegex(manifest, r'base image\s+not recorded')
        self.assertIn('engine/state.json: 21 bytes', manifest)

    def test_the_two_reads_the_client_owns(self) -> None:
        api = self.full_state()
        self.write(api=api)
        self.assertIn('/v1/service/status', api.calls)
        self.assertIn('/v1/service/init', api.calls)

    def test_no_device_id_and_no_token(self) -> None:
        path = self.write(api=self.full_state())
        blob = b''.join(self.members(path).values())
        self.assertNotIn(DEVICE_ID.encode(), blob)
        self.assertNotIn(TOKEN.encode(), blob)
        self.assertNotIn(b'device-id', blob)

    def test_the_log_member_is_the_newest_file_s_tail(self) -> None:
        newest = self.logs / 'aTrustTray20261013.log'
        newest.write_bytes(b'N' * (bundle.LOG_TAIL_BYTES + 1000))
        older = self.logs / 'aTrustTray20261012.log'
        older.write_bytes(b'O' * 32)
        os.utime(older, (WHEN - 3600, WHEN - 3600))
        os.utime(newest, (WHEN - 60, WHEN - 60))
        members = self.members(self.write(api=FakeAPI()))
        tail = members['client/log-tail.txt']
        self.assertEqual(len(tail), bundle.LOG_TAIL_BYTES)
        self.assertEqual(tail, b'N' * bundle.LOG_TAIL_BYTES)
        manifest = members['manifest.txt'].decode('utf-8')
        self.assertIn('the last %d of %d bytes of aTrustTray20261013.log'
                      % (bundle.LOG_TAIL_BYTES, bundle.LOG_TAIL_BYTES + 1000), manifest)

    def test_a_bare_state_directory_still_bundles(self) -> None:
        cfg = self.config(client_api=False)
        with mock.patch.object(bundle.probe, 'route_lines',
                               return_value=([], '0 route(s) via utun7')):
            members = self.members(bundle.write(cfg, api=None, now=WHEN))
        self.assertEqual(sorted(members), ['engine/routes.txt', 'manifest.txt'])
        self.assertEqual(members['engine/routes.txt'], b'')
        manifest = members['manifest.txt'].decode('utf-8')
        self.assertIn("client/status.json: not there - the client's own API is off", manifest)
        self.assertIn('engine/NEED_VNC: not there - no hand-over is pending', manifest)
        self.assertRegex(manifest, r'client image\s+not recorded')

    def test_a_client_that_is_down_is_a_manifest_line(self) -> None:
        (self.state / 'state.json').write_text('{}')
        members = self.members(self.write(api=FakeAPI()))
        self.assertNotIn('client/status.json', members)
        manifest = members['manifest.txt'].decode('utf-8')
        self.assertIn('client/status.json: not there - the client service is not '
                      'listening (54630)', manifest)
        self.assertIn('running client: not read', manifest)

    def test_the_base_image_is_named_when_the_image_records_one(self) -> None:
        (self.state / 'state.json').write_text('{}')
        base = 'ghcr.io/example/atrust-quadlet:base-2.5.16.41-abcdef12-amd64'
        with mock.patch.dict(os.environ, {'ATRUST_BASE_REF': base}):
            manifest = self.members(self.write(api=FakeAPI()))['manifest.txt'].decode('utf-8')
        self.assertRegex(manifest, r'base image\s+%s' % base)


if __name__ == '__main__':
    unittest.main()
