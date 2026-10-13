# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The page the client's own log names, and how it reaches the human.

The client's SPA writes `final route:<page>` into its tray log on every navigation (measured live
2026-10-13: `final route:login`, `final route:app_center`, `final route:connectSetting`), and the
hand-over uses it to say *which* page the window is on when the password form is not it - the
captcha, a second factor. Every half is best-effort: a tail that names no page leaves the hint
exactly as it was, and a read whose offset the writer split mid-line still sees the marker.

Run: python3 -m unittest tests.test_page_naming
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import uiauto, vnc  # noqa: E402
from atrustd.config import Config  # noqa: E402
from atrustd.state import StateFile  # noqa: E402

# One recorded line of the SPA's router guard, private fields left as they were captured.
ROUTE_LINE = ('[15:06:10.86] [pid:108] <info> [portal] [20261013 15:06:10.83]'
              '[UI:routerGuard][Aio][pid:431][fed:904074]final route:%s\n')
CHATTER = ('[12:41:30.93] [pid:108] <info> [portal] web/iconfont.7108884b.js:1:188810\n'
           '[12:41:30.93] [pid:108] <info> [portal] is not login, go to target route： login hash:connectSetting\n')


class PickerTest(unittest.TestCase):
    """`uiauto.page_token` over recorded tails."""

    def test_the_last_route_token_wins(self) -> None:
        text = ROUTE_LINE % 'login' + ROUTE_LINE % 'login' + ROUTE_LINE % 'totpAuth'
        self.assertEqual(uiauto.page_token(text), 'totpAuth')

    def test_a_tail_that_names_no_route_names_nothing(self) -> None:
        # The guard's "go to target route：" line is a full-width colon beside a space, and no
        # route of this log's own: the picker claims nothing rather than guessing the page.
        self.assertEqual(uiauto.page_token(CHATTER), '')

    def test_a_half_written_token_is_not_a_name(self) -> None:
        """The writer can be mid-line at the end of the file: the last *complete* token wins."""
        text = ROUTE_LINE % 'login' + '[15:06:10.86] [UI:routerGuard]final route:tot'
        self.assertEqual(uiauto.page_token(text), 'login')


class LogTailTest(unittest.TestCase):
    """A read since an offset the writer split a line at."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.logs = Path(tmp.name)
        self.path = self.logs / 'aTrustTray.log'
        self.cfg = Config(portal_url='https://vpn.example.com/', username='user', password='pw',
                          client_log_dir=self.logs)

    def test_an_offset_inside_a_token_still_reads_the_token(self) -> None:
        """The marker was written while the offset was taken: without the backup, the read
        starts at the marker's suffix and neither read ever saw the whole word."""
        self.path.write_text('chat\n' + ROUTE_LINE % 'totpAuth', encoding='utf-8')
        offset = self.path.stat().st_size - len('Auth\n')
        self.assertEqual(uiauto.page_token(uiauto.log_since(self.cfg, offset)), 'totpAuth')

    def test_a_checkcode_split_by_the_offset_is_still_requested(self) -> None:
        line = ('[15:06:06.58] [pid:108] <info> [portal] [UI:api][Aio][pid:437][fed:986061]'
                'Request: /passport/v1/public/checkCode success. traceId: 8ca24b21 hash:login\n')
        self.path.write_text('chat\n' + line, encoding='utf-8')
        offset = self.path.stat().st_size - len('hash:login\n')
        self.assertTrue(uiauto.captcha_requested(self.cfg, offset))

    def test_an_offset_at_a_line_start_reads_from_there(self) -> None:
        self.path.write_text('first\nsecond\n', encoding='utf-8')
        self.assertEqual(uiauto.log_since(self.cfg, len('first\n')), 'second\n')

    def test_the_backup_is_bounded(self) -> None:
        """One enormous line must not make the read grow with the file."""
        text = 'x' * 100000
        self.path.write_text(text, encoding='utf-8')
        self.assertEqual(uiauto.log_since(self.cfg, len(text) - 1),
                         'x' * (uiauto.LOG_LINE_BACKUP + 1))

    def test_an_offset_at_the_write_frontier_reads_nothing(self) -> None:
        self.path.write_text('a line\n', encoding='utf-8')
        self.assertEqual(uiauto.log_since(self.cfg, 7), '')

    def test_last_page_reads_the_newest_route_of_the_log(self) -> None:
        self.path.write_text(CHATTER + ROUTE_LINE % 'login' + CHATTER, encoding='utf-8')
        self.assertEqual(uiauto.last_page(self.cfg), 'login')


class WithPageTest(unittest.TestCase):
    """The clause, and the text it must not change when no page was read."""

    REASON = 'the portal is asking for the graphical captcha; answer it in the client window over VNC'

    def test_a_page_is_named_beside_the_reason(self) -> None:
        self.assertEqual(
            vnc.with_page(self.REASON, 'totpAuth'),
            self.REASON + '; the client\'s own log last named the page "totpAuth"')

    def test_a_page_named_alone_is_the_whole_text(self) -> None:
        self.assertEqual(vnc.with_page('', 'login'),
                         'the client\'s own log last named the page "login"')

    def test_no_page_leaves_the_text_byte_identical(self) -> None:
        self.assertEqual(vnc.with_page(self.REASON, ''), self.REASON)
        self.assertEqual(vnc.with_page('', ''), '')

    def test_the_named_page_reaches_the_hint(self) -> None:
        with TemporaryDirectory() as tmp:
            reason = vnc.with_page(self.REASON, 'totpAuth')
            path = vnc.hint(None, StateFile(Path(tmp)), reason)
            first = path.read_text(encoding='utf-8').splitlines()[0]
        self.assertEqual(first, 'NEED_VNC: ' + reason)


if __name__ == '__main__':
    unittest.main()
