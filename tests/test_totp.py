# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The TOTP codes have to be the ones the RFC publishes, and the clock decides which.

`atrustd --totp` exists for the one second factor a local secret can answer: while the VNC hand-over
is up, the human can read the current code on the host instead of finding another device. The
algorithm is RFC 6238 with its default parameters, so its interoperability test values (Appendix B)
are the test - they are the same numbers every TOTP authenticator reproduces, and a wrong step,
digest or truncation shows up as a wrong string here.

Run: python3 -m unittest tests.test_totp
"""
from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrustd import totp  # noqa: E402

# RFC 6238 Appendix B: the shared secret is the ASCII string "12345678901234567890", the step is 30 s
# and T0 is the Unix epoch. The published codes are 8 digits; the table is quoted in full because the
# 6-digit form below is derived from it (a 31-bit value modulo 10**6 is its 8-digit form modulo
# 10**6), not from a second implementation.
SECRET = base64.b32encode(b'12345678901234567890').decode()
RFC_VECTORS = (
    (59, '94287082'),
    (1111111109, '07081804'),
    (1111111111, '14050471'),
    (1234567890, '89005924'),
    (2000000000, '69279037'),
    (20000000000, '65353130'),
)


class PublishedVectorsTest(unittest.TestCase):
    def test_the_rfc_appendix_b_vectors(self) -> None:
        for at, expected in RFC_VECTORS:
            with self.subTest(at=at):
                self.assertEqual(totp.code(SECRET, at=at, digits=8), expected)

    def test_the_default_six_digit_form_is_the_tail_of_the_published_code(self) -> None:
        for at, expected in RFC_VECTORS:
            with self.subTest(at=at):
                self.assertEqual(totp.code(SECRET, at=at), expected[-6:])

    def test_the_default_parameters_are_the_rfc_ones(self) -> None:
        self.assertEqual((totp.DIGITS, totp.STEP, totp.ALGORITHM), (6, 30, 'sha1'))

    def test_the_code_is_zero_padded(self) -> None:
        # 1111111109 -> 07081804, 1234567890 -> 89005924; the padded ones are the interesting half
        self.assertEqual(totp.code(SECRET, at=1111111109, digits=8)[0], '0')
        self.assertEqual(len(totp.code(SECRET, at=1111111109)), 6)


class ClockTest(unittest.TestCase):
    def test_the_code_is_constant_inside_a_step_and_changes_at_the_boundary(self) -> None:
        # 1111111080 starts step 37037036 and 1111111110 starts 37037037; RFC 6238 pins the codes of
        # both (07081804 at 1111111109, 14050471 at 1111111111).
        inside = {totp.code(SECRET, at=float(at)) for at in range(1111111080, 1111111110)}
        self.assertEqual(inside, {'07081804'[-6:]}, 'the timestamps of one step disagree')
        self.assertEqual(totp.code(SECRET, at=1111111110.0), '14050471'[-6:])
        self.assertNotEqual(totp.code(SECRET, at=1111111110.0), inside.pop())

    def test_the_step_starts_at_the_epoch(self) -> None:
        self.assertEqual(totp.code(SECRET, at=0.0), totp.code(SECRET, at=29.999))
        # T = 0 is HOTP count 0, whose values RFC 4226 Appendix D publishes: the 31-bit truncation is
        # 1284755224 (0x4c93cf18), so its last 6 digits are 755224 and its last 8 are 84755224.
        self.assertEqual(totp.code(SECRET, at=0.0), '755224')
        self.assertEqual(totp.code(SECRET, at=0.0, digits=8), '84755224')

    def test_remaining_counts_down_to_the_next_step(self) -> None:
        self.assertEqual(totp.remaining(at=0.0), 30)
        self.assertEqual(totp.remaining(at=29.0), 1)
        self.assertEqual(totp.remaining(at=29.5), 0)
        self.assertEqual(totp.remaining(at=59.999), 0)
        self.assertEqual(totp.remaining(at=60.0), 30)

    def test_now_is_the_default_clock(self) -> None:
        # no injected timestamp: the code must be reproducible within its own step
        self.assertEqual(totp.code(SECRET), totp.code(SECRET, at=None))


class SecretTest(unittest.TestCase):
    def test_spaces_lower_case_and_missing_padding_are_tolerated(self) -> None:
        messy = ' ' + SECRET.lower()[: 10] + '  ' + SECRET.lower()[10:].rstrip('=')
        self.assertEqual(totp.decode_secret(messy), b'12345678901234567890')

    def test_a_secret_that_is_not_base32_is_refused(self) -> None:
        for bad in ('not-base32!', '1234567', 'A'):
            with self.subTest(secret=bad):
                with self.assertRaises(ValueError):
                    totp.decode_secret(bad)

    def test_an_empty_secret_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            totp.decode_secret('   ')


if __name__ == '__main__':
    unittest.main()
