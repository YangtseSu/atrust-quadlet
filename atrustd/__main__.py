# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""atrustd: keep the aTrust tunnel logged in without cookies as parameters.

Modes:
    --daemon        supervise forever (default; used by the Quadlet unit)
    --once          one supervision cycle, then exit
    --status        print the last known status (JSON) and exit
    --login-probe   only do a portal login and print the outcome (diagnostics)

Flow per cycle (see docs in README.md):
    1. probe the data plane (utun7 + routes + an intranet target through the proxy)
    2. online            -> sleep and re-check
    3. not online        -> is the *web* session still valid?
         yes             -> client-side problem: restart the client once
         no              -> log in over HTTP, harvest tid/tid.sig, write them into
                            the client's own profile, restart the client, wait
    4. captcha required  -> write the NEED_VNC hint (and the captcha image) and wait
                            for a human, then continue automatically
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from . import portal as portal_mod
from . import probe, tokens, vnc
from .config import Config
from .state import Backoff, State, StateFile, Status

log = logging.getLogger('atrustd')

TUNNEL_WAIT = 120.0
POLL = 5.0
# Right after the client starts, utun7 exists but the routes are not installed
# yet; do not declare the tunnel down during that window.
TUNNEL_GRACE = 30.0


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s %(levelname)-7s %(name)s: %(message)s',
        stream=sys.stdout,
    )


def transition(state_file: StateFile, status: Status, state: State, message: str, detail: str = '') -> None:
    if status.state != state.value:
        log.info('%s -> %s (%s)', status.state, state.value, message or state.value)
        status.state = state.value
        status.since = time.time()
    status.updated = time.time()
    status.message = message
    if detail:
        status.detail = detail[:400]
    state_file.write(status)


def wait_for_tunnel(cfg: Config, seconds: float = TUNNEL_WAIT) -> probe.ProbeResult:
    end = time.time() + seconds
    result = probe.check(cfg.tun, cfg.proxy, cfg.probe_targets)
    while not result.online and time.time() < end:
        time.sleep(POLL)
        result = probe.check(cfg.tun, cfg.proxy, cfg.probe_targets)
    return result


def refresh_tokens(cfg: Config, client: portal_mod.PortalClient) -> bool:
    """Steps 3 of the cycle: web login -> tokens into the client's own profile."""
    client.prepare()
    auth = client.auth_config()
    result = client.login(auth)
    if result.captcha_required:
        return False
    if not result.ok:
        raise portal_mod.PortalUnreachable('login rejected: code=%s %s' % (result.code, result.message))
    got = client.tokens()
    if not got:
        log.warning('login succeeded but the portal did not hand out tid/tid.sig; '
                    'nothing to persist into the client profile')
        return False
    log.info('portal login ok, tokens: %s', ','.join('%s(%d chars)' % (k, len(v)) for k, v in sorted(got.items())))
    if not cfg.client_cookie_db.exists():
        log.warning('client cookie database %s does not exist yet', cfg.client_cookie_db)
        return False
    if tokens.stop_client():
        try:
            tokens.write(cfg.client_cookie_db, cfg.host, got)
        finally:
            if not tokens.wait_client():
                log.error('client tray did not come back after writing tokens')
    else:
        log.warning('client tray did not stop in time; writing tokens anyway')
        tokens.write(cfg.client_cookie_db, cfg.host, got)
    return True


def cycle(cfg: Config, client: portal_mod.PortalClient, state_file: StateFile,
          status: Status, backoff: Backoff) -> None:
    result = probe.check(cfg.tun, cfg.proxy, cfg.probe_targets)
    if result.online:
        state_file.clear_vnc_hint()
        backoff.reset()
        status.attempts = 0
        transition(state_file, status, State.ONLINE, 'tunnel up', result.detail)
        return

    if result.tun_up and not result.routes:
        log.info('tunnel interface is up but routes are not installed yet; waiting up to %.0fs',
                 TUNNEL_GRACE)
        result = wait_for_tunnel(cfg, seconds=TUNNEL_GRACE)
        if result.online:
            state_file.clear_vnc_hint()
            backoff.reset()
            status.attempts = 0
            transition(state_file, status, State.ONLINE, 'tunnel up', result.detail)
            return

    status.attempts += 1
    transition(state_file, status, State.DEGRADED, 'tunnel not usable', result.detail)

    web_session = client.is_logged_in()
    if web_session:
        log.info('web session is alive but the tunnel is not; restarting the client')
        tokens.stop_client()
        if not tokens.wait_client():
            transition(state_file, status, State.DEGRADED, 'client did not restart')
            return
        result = wait_for_tunnel(cfg)
        if result.online:
            state_file.clear_vnc_hint()
            backoff.reset()
            status.attempts = 0
            transition(state_file, status, State.ONLINE, 'tunnel up after client restart', result.detail)
            return
    else:
        transition(state_file, status, State.LOGGED_OUT, 'session gone, logging in again')
        try:
            refresh_tokens(cfg, client)
            result = wait_for_tunnel(cfg)
            if result.online:
                state_file.clear_vnc_hint()
                backoff.reset()
                status.attempts = 0
                transition(state_file, status, State.ONLINE, 'tunnel up after re-login', result.detail)
                return
        except portal_mod.PortalUnreachable as exc:
            log.warning('login attempt failed: %s', exc)

    if status.attempts >= cfg.logins_before_vnc:
        captcha = b''
        try:
            captcha = client.fetch_check_code()
        except Exception:  # noqa: BLE001 - the image is a convenience, not a requirement
            pass
        if status.state != State.NEED_VNC.value:
            vnc.hint(cfg, state_file, 'portal needs a graphical captcha or a manual login', captcha or None)
        transition(state_file, status, State.NEED_VNC, 'waiting for a human in VNC')
        end = time.time() + cfg.vnc_wait
        while time.time() < end:
            time.sleep(POLL)
            if probe.check(cfg.tun, cfg.proxy, cfg.probe_targets).online:
                state_file.clear_vnc_hint()
                backoff.reset()
                status.attempts = 0
                transition(state_file, status, State.ONLINE, 'tunnel up after human action')
                return
        status.attempts = 0
        transition(state_file, status, State.DEGRADED, 'gave up waiting for a human, will retry')

    delay = backoff.next()
    log.info('next attempt in %.0fs', delay)
    time.sleep(delay)


def run_daemon(cfg: Config, once: bool = False) -> int:
    state_file = StateFile(cfg.state_dir)
    status = state_file.read() or Status()
    client = portal_mod.PortalClient(cfg)
    backoff = Backoff()
    stop = {'now': False}

    def _handler(signum, _frame):
        log.info('signal %s received, shutting down', signum)
        stop['now'] = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)

    while not stop['now']:
        try:
            cycle(cfg, client, state_file, status, backoff)
        except Exception as exc:  # noqa: BLE001 - the supervisor must survive anything
            log.exception('cycle failed: %s', exc)
            delay = backoff.next()
            log.info('retrying in %.0fs', delay)
            time.sleep(delay)
        if once:
            break
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='atrustd', description=__doc__.splitlines()[0])
    parser.add_argument('--daemon', action='store_true', help='supervise forever (default)')
    parser.add_argument('--once', action='store_true', help='run a single supervision cycle')
    parser.add_argument('--status', action='store_true', help='print the last known status as JSON')
    parser.add_argument('--login-probe', action='store_true', help='only test the portal login flow')
    parser.add_argument('--padding', default='pkcs1', choices=['pkcs1', 'oaep'], help='RSA padding for the password')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    cfg = Config.from_env()

    if args.status:
        status = StateFile(cfg.state_dir).read()
        print(status.to_json() if status else '{}')
        return 0

    if args.login_probe:
        client = portal_mod.PortalClient(cfg, padding=args.padding)
        client.prepare()
        auth = client.auth_config()
        log.info('authConfig: firstAuth=%s domain=%s installMode=%s pubKey=%d hex chars exp=%s',
                 auth.get('firstAuth'), auth.get('defaultDomain'), auth.get('clientInstallMode'),
                 len(str(auth.get('pubKey') or '')), auth.get('pubKeyExp'))
        result = client.login(auth)
        log.info('login: ok=%s code=%s message=%s ticket=%d chars',
                 result.ok, result.code, result.message, len(result.ticket))
        if result.ok:
            info = (result.auth_check.get('data') or {}).get('onlineInfo') or {}
            log.info('session: authCheck code=%s isOnline=%s user=%s clientIp=%s',
                     result.auth_check.get('code'), result.online, info.get('username'), info.get('clientIp'))
            toks = client.tokens()
            log.info('tokens: %s', {k: '%d chars' % len(v) for k, v in toks.items()} or 'none')
        return 0 if result.ok else 1

    return run_daemon(cfg, once=args.once)


if __name__ == '__main__':
    sys.exit(main())
