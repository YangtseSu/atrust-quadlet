# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""uiauto's screen geometry is pinned to dumps of the real client's window.

Every constant in ``atrustd.uiauto`` was measured by hand on the client's own
window, and a rewrite once moved a rectangle by 20 px before a human noticed.
These tests replay the probes over saved dumps of that window - the connection
page, the password form, the error row the client inserts after a rejected
submit and the captcha dialog of client 2.5.16.30 - and assert the constants
still land exactly on the pixels they were measured from: shifting
``USERNAME_BOX`` by 20 px, or swapping a dump, fails here - offline, no X
server, no container.

Capture recipe (redo on a client bump): run a one-off container of the
published image, let the fresh client show "Connection Options", pin its
window to 921x570 (``uiauto.normalize``), then ``xwd -silent -root -nobdrs``
of the screen, gzipped. The login page needs the address box driven with a
real portal address and OK clicked (``uiauto._set_address`` - no credentials
are submitted) until ``classify()`` reports ``login``. The error row needs a
submit with a wrong password and the captcha dialog a submit with the right
one, both from a test account; the captcha is a click-in-order dialog whose
characters must be clicked within the minute the portal allows. The typed
account and password pixels are masked out of those two dumps before they
enter the tree, and every dump is reviewed as a PNG first - the workspace
screen is where private text would leak and is deliberately not in this set.
The file names carry the client version; bump the name and ``CLIENT``
together with the re-capture.

Run: python3 -m unittest tests.test_uiauto_geometry
"""
from __future__ import annotations

import gzip
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import uiauto

SCREENS = Path(__file__).resolve().parent / 'data' / 'screens'
CLIENT = '2.5.16.30'
# The window the dumps were captured with, in absolute screen coordinates.
WIN = uiauto.Window(0, 95, 25, 921, 570)
# Measured on the error-row dump: the inline error row ("... you still have N
# attempts left") pushes the submit button 18 px past BUTTON_DY.
ERROR_ROW_BUTTON_DY = 177


def _load(name: str) -> tuple[bytes, uiauto.Screen]:
    with gzip.open(SCREENS / ('%s-%s.xwd.gz' % (name, CLIENT)), 'rb') as fh:
        raw = fh.read()
    return raw, uiauto.Screen(raw)


def _expected(dy: int) -> uiauto.Rect:
    """Where the constants say a card row sits, in screen coordinates."""
    return uiauto.Rect(WIN.x + uiauto.USERNAME_BOX[0], WIN.y + uiauto.USERNAME_BOX[1] + dy,
                       *uiauto.USERNAME_BOX[2:])


def _password(screen: uiauto.Screen) -> uiauto.Rect | None:
    return uiauto.find_box(screen, WIN,
                           (uiauto.USERNAME_BOX[0], uiauto.USERNAME_BOX[1] + uiauto.PASSWORD_DY),
                           uiauto.USERNAME_BOX[2:])


def _blank(screen: uiauto.Screen, raw: bytes, rect: uiauto.Rect, rgb) -> uiauto.Screen:
    """A copy of the dump with ``rect`` flat-filled, as ``Screen`` reads it.

    Written through the same pixel indexing the reads use, so the result is
    what the probes would see on a screen where that region has no content -
    a row the client inserts or hides (a captcha prompt, a ticked box).
    """
    def shift(mask: int) -> int:
        return (mask & -mask).bit_length() - 1

    value = 0
    for channel, mask in zip(rgb, (screen.red_mask, screen.green_mask, screen.blue_mask)):
        value |= (channel << shift(mask)) & mask
    unit = value.to_bytes(screen.pixel_bytes, 'little' if screen.byte_order == 0 else 'big')
    data = bytearray(raw)
    for y in range(rect.y, rect.y + rect.h):
        for x in range(rect.x, rect.x + rect.w):
            start = screen.offset + y * screen.stride + x * screen.pixel_bytes
            data[start:start + screen.pixel_bytes] = unit
    return uiauto.Screen(bytes(data))


class ConnectionPage(unittest.TestCase):
    """The first-run page, when the client has no portal address yet."""

    def test_classify_finds_the_page_and_the_address_box(self):
        _raw, screen = _load('connection')
        page, box = uiauto.classify(screen, WIN)
        self.assertEqual(page, uiauto.CONNECTION)
        self.assertEqual(box, uiauto.Rect(WIN.x + uiauto.ADDRESS_BOX[0],
                                          WIN.y + uiauto.ADDRESS_BOX[1],
                                          *uiauto.ADDRESS_BOX[2:]))

    def test_the_page_is_other_without_the_address_box(self):
        raw, screen = _load('connection')
        box = uiauto.classify(screen, WIN)[1]
        background = screen.pixel(box.x + box.w + 40, box.cy)
        gone = _blank(screen, raw,
                      uiauto.Rect(box.x - 4, box.y - 4, box.w + 8, box.h + 8), background)
        self.assertEqual(uiauto.classify(gone, WIN), (uiauto.OTHER, None))


class LoginPage(unittest.TestCase):
    """The password form, as a fresh profile of client 2.5.16.30 renders it."""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.screen = _load('login')

    def button(self) -> uiauto.Rect:
        return uiauto.find_button(self.screen, _password(self.screen))

    def test_classify_finds_the_page_and_the_account_field(self):
        page, account = uiauto.classify(self.screen, WIN)
        self.assertEqual(page, uiauto.LOGIN)
        self.assertEqual(account, _expected(0))

    def test_password_field_sits_at_password_dy(self):
        self.assertEqual(_password(self.screen), _expected(uiauto.PASSWORD_DY))

    def test_submit_button_is_found_by_its_fill_at_button_dy(self):
        self.assertEqual(self.button(),
                         uiauto.Rect(WIN.x + uiauto.USERNAME_BOX[0],
                                     WIN.y + uiauto.USERNAME_BOX[1] + uiauto.BUTTON_DY,
                                     *uiauto.BUTTON_SIZE))

    def test_agreement_box_is_read_at_dy_from_button(self):
        button = self.button()
        # 2.5.16.30 renders the box pre-ticked on a fresh profile (its button
        # is already in the primary colour, too).
        self.assertTrue(uiauto._agreement_checked(self.screen, button))
        password = _password(self.screen)
        rect = uiauto.Rect(button.x, button.y + uiauto.AGREE_DY_FROM_BUTTON,
                           uiauto.AGREE_SIZE, uiauto.AGREE_SIZE)
        background = self.screen.pixel(password.x + password.w + 40, password.cy)
        blanked = _blank(self.screen, self.raw,
                         uiauto.Rect(rect.x - 4, rect.y - 4, rect.w + 8, rect.h + 8), background)
        self.assertFalse(uiauto._agreement_checked(blanked, button))

    def test_password_row_gone_is_manual_not_login(self):
        """No password field under the account field means a captcha, a QR
        code or another auth method - never the password form."""
        password = _password(self.screen)
        background = self.screen.pixel(password.x + password.w + 40, password.cy)
        gone = _blank(self.screen, self.raw,
                      uiauto.Rect(password.x - 4, password.y - 4,
                                  password.w + 8, password.h + 8), background)
        page, account = uiauto.classify(gone, WIN)
        self.assertEqual(page, uiauto.MANUAL)
        self.assertEqual(account, _expected(0))


class ErrorRowPage(unittest.TestCase):
    """The password form with the rejected-submit error row inserted."""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.screen = _load('error-row')

    def test_classify_still_finds_the_form_around_the_error_row(self):
        page, account = uiauto.classify(self.screen, WIN)
        self.assertEqual(page, uiauto.LOGIN)
        self.assertEqual(account, _expected(0))
        self.assertEqual(_password(self.screen), _expected(uiauto.PASSWORD_DY))

    def test_the_error_row_pushes_the_button_past_button_dy(self):
        button = uiauto.find_button(self.screen, _password(self.screen))
        self.assertEqual(button,
                         uiauto.Rect(WIN.x + uiauto.USERNAME_BOX[0],
                                     WIN.y + uiauto.USERNAME_BOX[1] + ERROR_ROW_BUTTON_DY,
                                     *uiauto.BUTTON_SIZE))

    def test_the_agreement_read_follows_the_found_button(self):
        button = uiauto.find_button(self.screen, _password(self.screen))
        self.assertTrue(uiauto._agreement_checked(self.screen, button))
        # the no-error fallback position reads the error text, not the box:
        # this is why _submit_login finds the button before the agreement
        fallback = uiauto.Rect(button.x, WIN.y + uiauto.USERNAME_BOX[1] + uiauto.BUTTON_DY,
                               *uiauto.BUTTON_SIZE)
        self.assertFalse(uiauto._agreement_checked(self.screen, fallback))


class CaptchaPage(unittest.TestCase):
    """The click-in-order captcha, a modal dialog over the form."""

    @classmethod
    def setUpClass(cls):
        cls.raw, cls.screen = _load('captcha')

    def test_the_dialog_is_not_read_as_a_login_page(self):
        # the dialog covers the account field's border and the password
        # field's left half, so no page is claimed at all; the supervisor's
        # captcha hand-over rides on the client's checkCode log signal
        self.assertEqual(uiauto.classify(self.screen, WIN), (uiauto.OTHER, None))
