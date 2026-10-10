<!--
SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Step 05 — Second factor (OTP)

Status: ⛔ blocked — the offline half is done; the live half needs a deployment with a second factor
Depends on: a portal (or account) whose deployment has a second factor switched on, and one session to
capture it
Touches: `docs/DESIGN.md`, `atrustd/totp.py` (new), `atrustd/__main__.py`, `atrustd/vnc.py`,
`tests/test_totp.py` (new), `README.md`; `atrustd/portal.py` when the capture is in hand

## Goal

The account in front of this deployment has no second factor, so the flow cannot be captured and any
guess at the portal's request would be wrong by construction. What can be done without such a portal —
write down what is known, make the human path usable today, and record the capture recipe that closes
the unknown the day a portal has a second factor — is done and below.

Two facts keep this step honest:

* the factor is **not necessarily TOTP**. The sibling project
  [`kenvix/aTrustLogin`](https://github.com/kenvix/aTrustLogin) names three distinct portal-SPA pages
  for it — `totpAuth`, `smsAuth`, `page_auth_trust_terminal` (its `src/main.py`, the commented
  "not logged in" fragment list) — and a forced password change is a fourth shape of the same
  problem. Which one a deployment shows is that deployment's setting.
* that project drives the factor **in a browser**: page text decides, `pyotp.TOTP(key).now()` gives
  the code, `send_keys` types it into `//input[contains(@class,'totp')]` and the page's own submit
  button ends it. It never observes the request the SPA makes, so it proves the *client* of the
  factor (a shared secret in hand is enough) and nothing about what an OTP-enabled portal expects.

## Deliverables

- ✅ `docs/DESIGN.md`: "Auth methods this project does not drive" — captcha, TOTP, SMS, QR enrolment,
  trust-terminal approval and forced password change, each with what this project does about it.
  The policy, fixed by the operator: **every one of them is handed over to VNC**, and a wrong guess
  into a page the engine cannot read is never made.
- ✅ `atrustd/totp.py` + `python3 -m atrustd --totp`: RFC 6238 codes from `ATRUST_TOTP_KEY` (stdlib
  `hmac`/`base64`, HMAC-SHA-1, 30 s step, 6 digits), so a human can read the current code while the
  hand-over is up. It submits nothing; `--totp` needs no portal configuration at all.
- ✅ The hint (`atrustd/vnc.py`) now carries the **complete command line** for that case:
  `podman exec -e ATRUST_TOTP_KEY=<base32 secret> atrust python3 -m atrustd --totp`.
- ✅ `tests/test_totp.py`: the RFC 6238 Appendix B vectors (8 digits, exactly as published), their
  6-digit tail, RFC 4226 Appendix D's count-0 values for the epoch step, the step boundaries, and the
  secret parsing (spaces, case, missing padding, garbage).
- ✅ The capture recipe: below, in this file. It is what one session with a second-factor portal has
  to produce, in the order the pieces will be needed.
- ⬜ Once such a portal exists: `portal.py` submits the code at the step the response announced, the
  client window's factor page is pinned as a screen if the window is the surface that asks for it,
  and the live acceptance (login through the engine, then the client's own window) is recorded here.

## The capture recipe

One session against a deployment with the second factor on, in this order:

1. **What the engine's API login is told.** Read the `auth/psw` response where the no-factor case
   answers `data.nextService = auth/authCheck`: does `nextService` change, does `code`/`message` name
   the factor, and what appears in `data`? The fields the portal already sends without a factor
   (`graphCheckCodeEnable`, `skipSecondaryAuthStatus`, `skipSecondaryAuthTimeout`) are the baseline
   the delta shows up against. Reproduce the call with `atrustd --login-probe`.
2. **Which surface asks for the code.** The engine's API login never brings the tunnel up (the client
   refuses sessions obtained elsewhere), so the *client's own window* is what matters. Dump it
   (`xwd -root`, the way `uiauto` does) while it is asking, record the journal's `atrustd.uiauto`
   line and the `NEED_VNC` reason, and check the window against the leads above (`totpAuth`,
   `smsAuth`, `page_auth_trust_terminal`). If it is a form, pin it as a saved screen the way
   `tests/test_uiauto_geometry.py` pins the two current pages.
3. **The request that carries the code.** For the API path only: drive the portal SPA with the
   STATUS-era browser hook and read the request/response that submits the code — endpoint, query,
   body keys, headers — then replay it with `urllib` and compare. Without this the API path stays
   unbuilt; the window path needs no request knowledge at all.
4. **What the account can derive locally.** If the enrolment (or the portal's binding page) yields a
   shared secret, the factor is TOTP and `ATRUST_TOTP_KEY` applies; for SMS, a QR enrolment or a
   terminal approval there is no local secret, and the human path is the only path.
5. **The cost.** The portal's own attempt counter for the factor path, the way step 04 recorded it,
   because a wrong code is a consumed attempt like a wrong password.

## Exit criteria

- ✅ The TOTP vectors pass and `--totp` prints a code for a known key (machine-checkable, offline):
  11 tests in `tests/test_totp.py` (RFC 6238 Appendix B, including the zero-padded `07081804`, the
  boundary between steps 37037036 and 37037037, and RFC 4226 count 0), and the CLI smoke:
  `ATRUST_TOTP_KEY=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ python3 -m atrustd --totp` printed a code with
  its validity, no key answered exit 2 with the reason, a non-base32 key answered exit 2 as well.
- ✅ The capture recipe is complete enough that one session with a second-factor portal produces
  every shape above with no further exploration.
- ⛔ Live: the engine logs in on a portal that asks for a second factor.

## Progress log

* 2026-10-10 — written as step 05, blocked on the portal. Two of its deliverables (the TOTP generator
  with its vectors, and the design table) need no portal and can be done first if the human wants them
  ahead of the block.
* 2026-10-10 — `kenvix/aTrustLogin` read in full (local checkout, `8bff976`) instead of quoted from
  memory, and the honest split recorded above: its TOTP branch (`src/main.py:332-352`) is browser
  automation with `pyotp`, its detection is page text (`"TOTP" in page_source and "二次认证" in
  page_source`), its submit button is `button[type='submit'], input[type='submit']` (the first match),
  and it retries only through its outer keep-alive loop. Its commented page-fragment list
  (`login`, `totpAuth`, `captcha`, `page_auth_trust_terminal`, `smsAuth`) is the one transferable
  finding: the factor is a *family* of pages, not one. Nothing in that project observes a portal
  request, so nothing in it can be copied into `portal.py`.
* 2026-10-10 — the operator's ruling, now the policy in `docs/DESIGN.md`: TOTP, SMS, QR enrolment,
  terminal approval and a forced password change are **never** driven by the engine; all of them go
  to VNC, and the hint carries the reason. The one thing the engine adds for the TOTP case is the
  code, derived locally.
* 2026-10-10 — the offline half landed: `atrustd/totp.py`, the `--totp` mode (deliberately placed
  before `Config.from_env()`, so it works from a checkout on the host with only `ATRUST_TOTP_KEY`),
  the hint's complete `podman exec … --totp` line, `tests/test_totp.py`, the DESIGN table and the
  README line. `python3 -m unittest discover -s tests` runs 59 tests, all green; the running container
  still carries the previous image, so `--totp` inside it answers `unrecognized arguments: --totp`
  until the image is rebuilt - the host and next-image behaviour is what was verified.
