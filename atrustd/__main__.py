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
         no              -> log in over HTTP, harvest tid/tid.sig and write them
                            into the client's own profile (that is what keeps the
                            client's own login captcha free)
    4. drive the client's own login window (atrustd.uiauto): portal address,
       account, password, agreement, submit; the client is the only thing that
       can bring the tunnel up
    5. while the login session is there, publish the apps this account may
       launch (atrustd.apps): name, launch URL, launch method, server address
    6. captcha required  -> write the NEED_VNC hint (and a captcha image) and
                            wait for a human, then continue automatically
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from . import portal as portal_mod
from . import apps as apps_mod
from . import probe, tokens, uiauto, vnc
from .config import Config
from .state import Backoff, State, StateFile, Status

log = logging.getLogger('atrustd')

TUNNEL_WAIT = 120.0
# The client's own window finishes its login much faster than a fresh start.
UI_TUNNEL_WAIT = 60.0
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
    """Step 3 of the cycle: web login -> tokens into the client's own profile.

    Returns True when the portal accepted the login: the session is then usable
    for the app list as well.
    """
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
        return True
    log.info('portal login ok, tokens: %s', ','.join('%s(%d chars)' % (k, len(v)) for k, v in sorted(got.items())))
    if not cfg.client_cookie_db.exists():
        log.warning('client cookie database %s does not exist yet', cfg.client_cookie_db)
        return True
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


def publish_apps(cfg: Config, client: portal_mod.PortalClient) -> bool:
    """Keep the apps this account may launch, with their launch information.

    The client shows them in its "App Details" panel (launch method + URL); on a
    headless host the same facts go to the log and to ``apps.json`` in
    ``ATRUST_STATE_DIR``, so a "Default Browser" app can be opened from the host
    through the container's proxies without a desktop.
    """
    try:
        resources = client.client_resources()
    except portal_mod.PortalUnreachable as exc:
        log.warning('cannot read the app list: %s', exc)
        return False
    apps = apps_mod.summarize(resources)
    path = apps_mod.save(cfg.state_dir, apps)
    for line in apps_mod.lines(apps):
        log.info('%s', line)
    log.info('app list written to %s', path)
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
    client.captcha_required = False  # refreshed below when the web login runs
    marker = uiauto.log_offset(cfg)
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

    # Only the client's own window brings the tunnel up, and the engine's login
    # exists to keep that login captcha free - the two always run together: a
    # login rotates the device token, which drops the client's session as well,
    # so a restart alone cannot recover from it.
    transition(state_file, status, State.LOGGED_OUT, 'the client has to log in again')
    session = False
    try:
        session = refresh_tokens(cfg, client)
    except portal_mod.PortalUnreachable as exc:
        log.warning('portal login attempt failed: %s', exc)
    if session:
        # The session also answers what this account may launch.
        publish_apps(cfg, client)
    ui = uiauto.login(cfg)
    log.info('client window: %s', ui.describe())
    if ui.acted:
        result = wait_for_tunnel(cfg, seconds=UI_TUNNEL_WAIT)
        if result.online:
            state_file.clear_vnc_hint()
            backoff.reset()
            status.attempts = 0
            transition(state_file, status, State.ONLINE, 'tunnel up after the client login',
                       result.detail)
            return
    captcha_pending = client.captcha_required or uiauto.captcha_requested(cfg, marker)

    if status.attempts >= cfg.logins_before_vnc or captcha_pending or ui.needs_human:
        if ui.needs_human:
            reason = ('the client window is not showing the password form: %s; '
                      'finish the login in VNC' % ui.detail)
        elif captcha_pending:
            reason = ('the portal is asking for the graphical captcha; '
                      'answer it in the client window over VNC')
        else:
            reason = ('the tunnel is still down after %d login attempt(s); %s'
                      % (status.attempts, ui.describe()))
        captcha = b''
        try:
            captcha = client.fetch_check_code()
        except Exception:  # noqa: BLE001 - the image is a convenience, not a requirement
            pass
        if status.state != State.NEED_VNC.value:
            vnc.hint(cfg, state_file, reason, captcha or None)
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
    # The client opens on "Connection Options" and asks for the portal address
    # unless it finds it in its own config; that config lives outside the
    # mounted profile, so a recreated container would ask again.
    uiauto.seed_address(cfg)

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
    parser.add_argument('--apps', action='store_true',
                        help='print the apps the portal grants (launch url/method)')
    parser.add_argument('--refresh', action='store_true',
                        help='with --apps: log in again and fetch the list (new session, the '
                             'client has to log in afterwards)')
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

    if args.apps:
        if not args.refresh:
            cached = apps_mod.load(cfg.state_dir)
            if not cached:
                print('no app list in %s yet; run "atrustd --apps --refresh" to fetch it '
                      '(that logs in, so the client will have to log in again)' % cfg.state_dir)
                return 1
            print('\n'.join(apps_mod.lines(cached)))
            print('(%s)' % (cfg.state_dir / apps_mod.FILE_NAME))
            return 0
        client = portal_mod.PortalClient(cfg, padding=args.padding)
        client.prepare()
        result = client.login(client.auth_config())
        if not result.ok:
            log.error('cannot list the apps, the portal login failed: code=%s %s',
                      result.code, result.message)
            return 1
        return 0 if publish_apps(cfg, client) else 1

    return run_daemon(cfg, once=args.once)


if __name__ == '__main__':
    sys.exit(main())
