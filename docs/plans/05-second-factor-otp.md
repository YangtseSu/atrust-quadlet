<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 05 — Second factor (OTP)

Status: ⛔ blocked — no portal with OTP enabled to capture or test against
Depends on: a portal whose deployment has the second factor switched on
Touches: `docs/DESIGN.md`, `atrustd/totp.py` (new), `atrustd/__main__.py`, `atrustd/portal.py`,
`tests/test_totp.py` (new), `README.md`

## Goal

The account in front of this deployment has no second factor, so the flow cannot be captured and any
guess at the portal's OTP request would be wrong by construction. What *can* be done without such a
portal: write down what is known, make the human path usable today, and record the capture recipe that
closes the unknown the day a portal has OTP.

Facts to keep in the file, not in memory: the sibling project
[`kenvix/aTrustLogin`](https://github.com/kenvix/aTrustLogin) does TOTP **at the web layer**
(`src/main.py:332`, page text `TOTP` + `二次认证`, input `input[contains(@class,'totp')]`, code from
`pyotp.TOTP(key).now()`), which is a browser-driving approach, not the portal API this engine uses. So
their code proves the *client* of the factor (a TOTP secret in hand is enough) and nothing about the
request an OTP-enabled portal expects.

## Deliverables

- ⬜ `docs/DESIGN.md`: an "auth methods this project does not drive" table — graphical captcha (handed
  over to VNC, verified), TOTP/二次认证, SMS, QR code, and a portal-forced password change (also a
  hand-over: `uiauto` reports the page as not-the-password-form and `NEED_VNC` carries the reason,
  which step 01 then pushes to the desktop).
- ⬜ `atrustd/totp.py` + `python3 -m atrustd --totp`: RFC 6238 codes from `ATRUST_TOTP_KEY` (stdlib
  `hmac`/`base32`, 30 s step, 6 digits), so a human can read the current code from the host and type it
  into the VNC session while the hand-over is up.
- ⬜ `tests/test_totp.py`: the RFC 6238 appendix-B vectors (SHA-1) and the clock-skew boundaries.
- ⬜ The capture recipe: what to record from an OTP portal — the `auth/psw` response that announces the
  second factor, the submit endpoint and body for the code, and whether the client's own window needs
  the code too (`uiauto` page dump). Written here with the STATUS-era browser-hook recipe as the tool.
- ⬜ Once a portal with OTP exists: `portal.py` submits the code, `ATRUST_TOTP_KEY` feeds it, and the
  live acceptance (login through the engine, then the client's own window) is recorded here.

## Exit criteria

- ⬜ The TOTP vectors pass and `--totp` prints a code for a known key (machine-checkable, offline).
- ⬜ The capture recipe is complete enough that one session with an OTP portal produces the endpoint
  shapes with no further exploration.
- ⛔ Live: the engine logs in on a portal that asks for a second factor.

## Progress log

* 2026-10-10 — written as step 05, blocked on the portal. Two of its deliverables (the TOTP generator
  with its vectors, and the design table) need no portal and can be done first if the human wants them
  ahead of the block.
