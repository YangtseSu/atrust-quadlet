#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""RFC 6238 codes, for the one second factor a shared secret can answer.

This project does not drive the portal's second factor, whatever it turns out to be - a TOTP code,
an SMS code, a trust-terminal approval, a forced password change all end in the VNC hand-over, where
the human finishes the login in the client's own window (docs/DESIGN.md). What the engine can still
do for the TOTP case is hand the human the code:

    podman exec -e ATRUST_TOTP_KEY=<base32 secret> atrust python3 -m atrustd --totp

RFC 6238 with its default parameters (HMAC-SHA-1, 30 s step, 6 digits), standard library only -
base64 + hmac + struct, like the rest of the engine. The published test vectors are in
`tests/test_totp.py`.
"""
from __future__ import annotations

import base64
import binascii
import hmac
import struct
import time

DIGITS = 6
STEP = 30
ALGORITHM = 'sha1'
ENV_KEY = 'ATRUST_TOTP_KEY'


def decode_secret(secret: str) -> bytes:
    """The shared secret in its base32 form; spaces, lower case and missing padding are tolerated."""
    cleaned = ''.join(secret.split()).upper()
    if not cleaned:
        raise ValueError('empty secret')
    try:
        return base64.b32decode(cleaned + '=' * (-len(cleaned) % 8), casefold=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError('not a base32 secret: %s' % exc) from exc


def code(secret: str, at: float | None = None, digits: int = DIGITS, step: int = STEP,
         algorithm: str = ALGORITHM) -> str:
    """The code of the step `at` falls into (default: now), zero padded to `digits`."""
    counter = int((time.time() if at is None else at) // step)
    digest = hmac.new(decode_secret(secret), struct.pack('>Q', counter), algorithm).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % 10 ** digits).zfill(digits)


def remaining(at: float | None = None, step: int = STEP) -> int:
    """Whole seconds until `code()` stops being the current one."""
    now = time.time() if at is None else at
    return int(step - (now % step))
