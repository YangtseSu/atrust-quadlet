# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""atrustd: keep the aTrust tunnel logged in without cookies as parameters.

Modes:
    --daemon        supervise forever (default; used by the Quadlet unit)
    --once          one supervision cycle, then exit
    --status        print the last known status (JSON) and exit
    --login-probe   only do a portal login and print the outcome (diagnostics)
    --totp          print the current TOTP code from ATRUST_TOTP_KEY and exit (RFC 6238)

Flow per cycle (see docs/DESIGN.md for the pieces around it):
    1. probe the data plane (utun7 + routes + a witness through the proxy: the
       configured target, or one discovered off the tunnel's own routes)
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
import threading
import time
from dataclasses import dataclass

from . import portal as portal_mod
from . import apps as apps_mod
from . import clientapi, probe, tokens, totp as totp_mod, uiauto, vnc
from .config import Config
from .state import Backoff, State, StateFile, Status

log = logging.getLogger('atrustd')

TUNNEL_WAIT = 120.0
# The client's own window finishes its login much faster than a fresh start.
UI_TUNNEL_WAIT = 60.0
# The ticket path has no form to fill: `start` is one HTTP call, and the measured tunnel came up
# three seconds after it (five on the 2.5.16.41 bump). The wait is probe-driven - it returns on the
# first passing sample - so the bound is paid only when the tunnel is not coming on this path, which
# is the window fallback's case. Kept at sixty: a smaller number would only end a slow recovery
# sooner, and the numbers the bound governs are all single-digit seconds.
API_TUNNEL_WAIT = 60.0
# How long a ticket attempt waits for a just-restarted client to become usable: its HTTP service
# is unreachable for ~2-4 s after a tray restart and its `sdpcguid` stays empty until its own
# state is loaded (both measured live), so ten seconds of 1 s reads is the bound - anything down
# for longer is a down client, and the window path takes it from there.
CLIENT_RESTART_WAIT = 10.0
POLL = 5.0
# Right after the client starts, utun7 exists but the routes are not installed
# yet; do not declare the tunnel down during that window.
TUNNEL_GRACE = 30.0
# How coarsely a wait notices a client event: `threading.Event.wait` takes one
# event, so a wait that watches two (the stop event and the poller's wake) checks
# the wake between short slices of the stop wait. A quarter second of latency on
# a wait that lasts minutes is nothing beside a probe cycle.
WAIT_SLICE = 0.25


def _wait_any(events: list[threading.Event], seconds: float) -> threading.Event | None:
    """Wait until one of `events` is set or `seconds` pass; the set one, or None."""
    end = time.monotonic() + seconds
    while True:
        for event in events:
            if event.is_set():
                return event
        remaining = end - time.monotonic()
        if remaining <= 0:
            return None
        events[0].wait(min(WAIT_SLICE, remaining))


def pause(stop: threading.Event | None, seconds: float,
          wake: threading.Event | None = None) -> bool:
    """Sleep, waking early when a stop is requested or a client event arrives.

    True means "stop now". ``wake`` is the client event poller's event
    (`atrustd.clientapi.EventPoller`): a transition on the client's own channel
    cuts the remaining wait short, so the next cycle starts on the event instead
    of at the next ``ATRUST_WATCH_INTERVAL``. Nothing is consumed here - the
    daemon takes the reason and hands it to the cycle.

    The daemon's waits last minutes (the watch interval, ``ATRUST_VNC_WAIT``)
    and CPython re-enters ``time.sleep`` after a signal, so a ``SIGTERM`` in
    there was answered only when the wait ended - past podman's own stop
    timeout, which then SIGKILLed the whole container instead.
    """
    watchers = [event for event in (stop, wake) if event is not None]
    if not watchers:
        time.sleep(seconds)
        return False
    return _wait_any(watchers, seconds) is stop


def reap_orphans() -> int:
    """Collect every child that already exited; PID 1 has to do this itself.

    The client family is swept on every recovery and on the way out, and the
    children of a dead tray (its Electron helpers, the detached tunnel) reparent
    to this process - PID 1 in the container. Nothing else ever calls ``waitpid``
    for them, so without this they stay zombies in the task list and count
    against the runtime's pids limit; a container left running long enough could
    fill that limit with dead entries until nothing new can start.

    Deliberately not a ``SIGCHLD`` handler: the module's own ``subprocess.run``
    calls (``ip``, ``xdotool``, ``xwd``) wait for their children directly, and a
    handler would steal the exit statuses they depend on.
    """
    reaped = 0
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if not pid:
            break
        reaped += 1
    if reaped:
        log.info('reaped %d orphan(s)', reaped)
    return reaped


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s %(levelname)-7s %(name)s: %(message)s',
        stream=sys.stdout,
    )


def transition(state_file: StateFile, status: Status, state: State, message: str, detail: str = '') -> None:
    if status.state != state.value:
        client = status.client_line()
        log.info('%s -> %s (%s)%s', status.state, state.value, message or state.value,
                 '; %s' % client if client else '')
        status.state = state.value
        status.since = time.time()
    status.updated = time.time()
    status.message = message
    if detail:
        status.detail = detail[:400]
    state_file.write(status)


def data_plane(cfg: Config) -> probe.ProbeResult:
    """One data-plane check: the witnesses a human named, and the tunnel's own routes.

    `ATRUST_PROBE_TARGET` names the witnesses the deployment trusts; with
    `ATRUST_PROBE_DISCOVER` (the default) the tunnel's own route table adds the
    addresses it carries one by one, so a deployment needs no intranet address of
    its own - and a configured one that cannot answer no longer decides the check
    while another witness answers.
    """
    return probe.check(cfg.tun, cfg.proxy, cfg.probe_targets, discover=cfg.probe_discover)


def wait_for_tunnel(cfg: Config, seconds: float = TUNNEL_WAIT,
                    stop: threading.Event | None = None) -> probe.ProbeResult:
    end = time.time() + seconds
    result = data_plane(cfg)
    while not result.online and time.time() < end and not pause(stop, POLL):
        result = data_plane(cfg)
    return result


def refresh_tokens(cfg: Config, client: portal_mod.PortalClient) -> bool:
    """Step 3 of the cycle: web login -> tokens into the client's own profile.

    Returns True when the portal accepted the login: the session is then usable
    for the app list as well. A refusal raises with its class beside the code -
    the caller reads `client.refused_class` for the classes the cycle decides
    with (`portal.HELD_CLASSES`, `portal.CAPTCHA`) - and False is only the
    captcha demand, which belongs to a human.
    """
    client.prepare()
    auth = client.auth_config()
    result = client.login(auth)
    if result.answer_class == portal_mod.CAPTCHA:
        return False
    if not result.ok:
        raise portal_mod.PortalUnreachable('login rejected: %s' % portal_mod.answer_text(
            result.code, result.message, result.answer_class))
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


def _client_view(api: 'clientapi.ClientAPI', stop: threading.Event | None = None,
                 seconds: float = 0.0, want_guid: bool = False) -> 'clientapi.ClientStatus':
    """The client's own view, waiting up to `seconds` for it to become usable.

    A client-family restart leaves the agent's HTTP service unreachable for a few seconds, and a
    tray that has just started answers an empty `sdpcguid` until its own state is loaded
    (measured both live, `docs/CLIENT-LOCAL-API.md`) - so `want_guid` waits for the field the
    `/v1/service/start` envelope needs, not just for any answer. A wait of 0 is one read.
    """
    def usable(view: 'clientapi.ClientStatus') -> bool:
        return view.ok and (bool(view.guid) or not want_guid)

    view = api.status()
    deadline = time.time() + seconds
    while not usable(view) and time.time() < deadline:
        if pause(stop, 1.0):
            break
        view = api.status()
    return view


@dataclass
class TicketAttempt:
    """What the ticket path did in one cycle, as a value the caller reads.

    ``result`` is the probe result when the tunnel came up, ``reason`` the short
    string the hand-over carries when the attempt could not run or failed (empty
    when it could not run at all), and ``logged_in`` says whether this attempt ran
    the portal login itself. The caller reads that flag: the window path would ask
    the portal for a login of its own otherwise, and the repeat is refused
    (`75500006 当前账号已在线，无需重复上线`, measured 0.3 s after the first had
    landed), which reads like a failed login although the first one stood.
    """

    result: 'probe.ProbeResult | None' = None
    reason: str = ''
    logged_in: bool = False


def _with_ticket_note(detail: str, reason: str | None) -> str:
    """`detail` plus the ticket path's refusal, when there was one.

    The refusal is the short string `_api_login`'s attempt carries when it could not run or
    failed, and it belongs beside the recovery a human reads: it is how a client bump that moved
    the interface shows up without anyone reading the journal (the notifier shows the
    transition's detail).
    """
    if not reason:
        return detail
    return ('%s; the ticket login: %s' % (detail, reason)) if detail \
        else 'the ticket login: %s' % reason


def _api_login(cfg: Config, client: portal_mod.PortalClient, api: 'clientapi.ClientAPI | None',
               stop: threading.Event | None = None) -> TicketAttempt:
    """Try the measured ticket path: portal session -> ticket -> agent -> tunnel.

    The sequence the client's own workbench makes when a user logs in on the portal page
    (`docs/CLIENT-LOCAL-API.md`, "The login path, verified"): `sid_ticket()` mints a ticket from
    whatever live session the engine has, `start()` hands it to the client's local service, and
    the tunnel is up about three seconds later - no window, no X11, no cookie surgery. A dead
    engine session is no reason to skip it: the fresh login (`refresh_tokens`, its client
    restart included) is run here and the mint then follows - that login is the window path's
    ground work either way, and whether a session the portal has already replaced can still
    mint is exactly the thing to measure rather than assume.

    The attempt's `result` is the probe result when the tunnel is up (its detail is what the
    ONLINE transition carries); an empty attempt (no reason, no result) is one that could not run
    at all - no local API, or the client's own view says it is in a session, repairing which is
    the restart/human paths' business since `start` would only answer "already logged in"; and a
    reason is a short string saying why it failed, a value on purpose because the caller falls
    back to the window path on anything but a result. `logged_in` is set when this attempt ran
    the fresh portal login itself, so the caller knows not to ask the portal again.
    """
    if api is None:
        return TicketAttempt()

    def restart_wait() -> float:
        """How long to wait for a view the ticket path can use - only where a restart is likely.

        A tray that has just restarted answers within ~5 s and its HTTP service is unreachable
        for ~2-4 s around it, so the bound is worth paying there. A daemon that has never seen a
        guid from this client has a client that started with it - a container that has just been
        recreated, whose first guid takes 35 s+ (both measured live 2026-10-12) - and the window
        path, whose login runs in that case anyway, takes the cycle, so the bound would be paid
        for nothing. The two were indistinguishable before this and every cold start paid it.
        """
        return CLIENT_RESTART_WAIT if api.seen_guid else 0.0

    view = _client_view(api, stop, restart_wait(), want_guid=True)
    if view.ok and view.state in ('online', 'otherSdpCLogin'):
        log.info('the client reports %s/%s; the ticket path cannot repair it',
                 view.state, view.tunnel)
        return TicketAttempt()
    logged_in = False
    if not client.is_logged_in():
        landed = False
        try:
            landed = refresh_tokens(cfg, client)
        except portal_mod.PortalUnreachable as exc:
            # A refusal is a value here, not the end of the cycle: the class and the row stay on
            # the client (`refused_class`/`refused_code`/`refused_message`) and the caller reads
            # them - the hand-over when `portal.HELD_CLASSES` stops the retries, the window path
            # otherwise. It used to propagate, which ended the cycle before either could run.
            log.warning('the fresh portal login did not land: %s', exc)
        if not landed:
            log.info('no live portal session to mint a ticket in, and a fresh login did not land')
            return TicketAttempt(reason='no live portal session to mint a ticket from')
        logged_in = True
        # The fresh login also answers what this account may launch.
        publish_apps(cfg, client)
        view = _client_view(api, stop, restart_wait(), want_guid=True)
    if not view.ok:
        log.info('the client service is not answering (%s); the ticket cannot be handed over',
                 view.detail)
        return TicketAttempt(reason='the client service did not answer: %s' % view.detail[:120],
                             logged_in=logged_in)
    if not view.guid:
        # `/v1/service/start` rejects an empty envelope guid (`Invalid schema:
        # #/properties/guid`, measured live on a tray that was still loading its state), so a
        # client that has not published one has no ticket to take yet.
        log.info('the client published no session guid; the ticket cannot be handed over')
        return TicketAttempt(reason='the client has no session guid yet', logged_in=logged_in)
    api.guid = view.guid
    try:
        ticket = client.sid_ticket()
    except portal_mod.PortalUnreachable as exc:
        log.warning('cannot mint a ticket for the client: %s', exc)
        return TicketAttempt(reason='cannot mint a ticket: %s' % str(exc)[:120],
                            logged_in=logged_in)
    result = api.start(ticket)
    if not result.ok:
        log.warning('the client did not take the ticket: %s', result.detail)
        return TicketAttempt(reason='the client did not take the ticket: %s' % result.detail[:120],
                            logged_in=logged_in)
    if result.answer_class == clientapi.ALREADY_LOGGED_IN:
        log.info('the client reports it is already logged in; confirming with the tunnel')
    else:
        log.info('the client took the ticket; waiting up to %.0fs for the tunnel',
                 API_TUNNEL_WAIT)
    probe_result = wait_for_tunnel(cfg, seconds=API_TUNNEL_WAIT, stop=stop)
    if not probe_result.online:
        return TicketAttempt(
            reason='the tunnel did not come up within %.0fs of the ticket' % API_TUNNEL_WAIT,
            logged_in=logged_in)
    return TicketAttempt(result=probe_result, logged_in=logged_in)


def cycle(cfg: Config, client: portal_mod.PortalClient, state_file: StateFile,
          status: Status, backoff: Backoff, stop: threading.Event | None = None,
          api: 'clientapi.ClientAPI | None' = None, wake: str = '') -> float:
    """One supervision cycle; returns the seconds to wait before the next one.

    ``stop`` is the daemon's stop event (``None`` in the tests): the waits that
    can last minutes return to the caller as soon as it is set.

    ``api`` is the client's own loopback API (``None`` in the tests that do not
    care): with it, every transition records the client's own view beside the
    data plane's.

    ``wake`` is the client event(s) that cut the daemon's wait short ('' for a
    cycle that starts on the interval). It is logged, and the cycle's *first*
    transition carries it in its detail, so the journal shows a cycle ran early
    and why. It changes nothing else: the cycle decides exactly as always.

    The portal's refusals are read as classes off the client (``refused_class``,
    ``refused_code``, ``refused_message``): the graphical captcha is the class
    that hands over, and the detail a hand-over records carries the class beside
    the code. A refusal the portal took back - a login it accepted, or a tunnel
    that came up - clears the record.

    The sleep lives in the caller on purpose: a ``return`` here used to skip it,
    so a healthy tunnel turned the supervisor into a busy loop - ``probe.check``
    (two ``ip`` forks and one CONNECT to the intranet target) ran ~40 times a
    second, which is what flooded the client's netstack with connections and made
    the probe itself time out.
    """
    wake_note = wake
    if wake:
        log.info('woke on client event(s): %s', wake)

    def note(state: State, message: str, detail: str = '') -> dict[str, str]:
        """Transition, reading the client's own view at the same moment.

        Reading it per transition (not once per cycle) means the view recorded
        in ``state.json`` belongs to the state it sits beside even when one
        cycle walks several - a recovery samples the client while it is down and
        again when it is back. The record is returned so a decision can read the
        same sample the transition carries, at no extra request.
        """
        nonlocal wake_note
        if api is not None:
            status.client = api.status().as_record()
        else:
            # No API in this cycle (the switch is off, or the caller gave none): no view is
            # recorded, and one an earlier run left in the state file is not carried forward -
            # the file must not claim a client view nobody read (measured live 2026-10-12: a
            # start with the API off kept reporting the previous run's `online/tunnelAvailable`).
            status.client = {}
        if wake_note:
            detail = ('%s; woke on client event %s' % (detail, wake_note)) if detail \
                else 'woke on client event %s' % wake_note
            wake_note = ''
        transition(state_file, status, state, message, detail)
        return status.client

    def online(message: str, detail: str = '') -> float:
        """The one ONLINE path: the hint goes, the pacing resets, the refused class lifts.

        The tunnel being up is what a refused login waits for: the human may have fixed the
        credential and logged in over VNC themselves, so the next recovery is allowed to ask the
        portal again - and a class that says "the portal wants the captcha" is a statement about
        the attempt that got it, not a permanent one.
        """
        state_file.clear_vnc_hint()
        backoff.reset()
        status.attempts = 0
        client.clear_refused()
        note(State.ONLINE, message, detail)
        return cfg.watch_interval

    # PID 1's own housekeeping, before anything else looks at the world: the
    # dead children a sweep or the client's own restarts left behind wait here.
    reap_orphans()
    result = data_plane(cfg)
    if result.online:
        return online('tunnel up', result.detail)

    if result.tun_up and not result.routes:
        log.info('tunnel interface is up but routes are not installed yet; waiting up to %.0fs',
                 TUNNEL_GRACE)
        result = wait_for_tunnel(cfg, seconds=TUNNEL_GRACE, stop=stop)
        if result.online:
            return online('tunnel up', result.detail)

    status.attempts += 1
    view = note(State.DEGRADED, 'tunnel not usable', result.detail)

    web_session = client.is_logged_in()
    marker = uiauto.log_offset(cfg)
    skipped = ''
    if web_session:
        if view.get('state') == 'logout' and view.get('tunnel') == 'tunnelUnavailable':
            # The client itself says the portal ended its session, and a restart cannot repair
            # that: the measured detour (tray stop, restart, 120 s tunnel wait) cost 2.4 minutes
            # and brought nothing up, while the login path below recovers in seconds. Only this
            # positive view skips the branch - a failed or missing read is not a statement about
            # the session, and the client's own service is unreachable around a restart.
            skipped = 'client %s/%s; not restarting it' % (view['state'], view['tunnel'])
            log.info('%s', skipped)
        else:
            log.info('web session is alive but the tunnel is not; restarting the client')
            tokens.stop_client()
            if not tokens.wait_client():
                note(State.DEGRADED, 'client did not restart')
                return backoff.next()
            result = wait_for_tunnel(cfg, stop=stop)
            if result.online:
                return online('tunnel up after client restart', result.detail)

    # The client is out of its own session. Recovery has two paths, and the measured one goes
    # first: the engine's live portal session mints the ticket the workbench hands over
    # (`ticketExchange`), the agent's `/v1/service/start` takes it and brings the tunnel up with
    # no window and no X11. The window path keeps running as the fallback - for a portal that
    # wants a captcha or a factor on this path (it stops the ticket mint as well), or for any
    # other step that fails.
    note(State.LOGGED_OUT, 'the client has to log in again', skipped)
    attempt = _api_login(cfg, client, api, stop)
    if attempt.result is not None:
        return online('tunnel up after the ticket login', attempt.result.detail)
    if attempt.reason:
        # A warning, not an INFO: a refusal here is the one thing that says the interface moved
        # or the client has nothing to take a ticket with, and it costs the waits above.
        log.warning('the ticket login did not bring the tunnel up (%s); '
                    'falling back to the client window', attempt.reason)

    # The window path: the engine's login exists to keep that login captcha free, and the two
    # always run together - a login rotates the device token, which drops the client's session
    # as well, so a restart alone cannot recover from it. One pass per cycle: a login that does
    # not come up waits for the next cycle (the backoff) like it always has. One exception: a
    # cycle the ticket path already logged the portal in does not ask again - the repeat was
    # measured refused (`75500006 当前账号已在线，无需重复上线`) and reads like a failed login,
    # and that path published the app list from its own session already.
    if not attempt.logged_in:
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
        result = wait_for_tunnel(cfg, seconds=UI_TUNNEL_WAIT, stop=stop)
        if result.online:
            return online('tunnel up after the client login',
                          _with_ticket_note(result.detail, attempt.reason))
    captcha_pending = client.refused_class == portal_mod.CAPTCHA \
        or uiauto.captcha_requested(cfg, marker)

    if status.attempts >= cfg.logins_before_vnc or captcha_pending or ui.needs_human:
        # The state file (and the NEED_VNC hint beside it) carries what the portal answered -
        # the class beside the code - next to the ticket path's own reason, so the hand-over
        # says which paths were already tried and what each answered.
        refusal = portal_mod.answer_text(client.refused_code, client.refused_message,
                                         client.refused_class) if client.refused_code else ''
        detail = _with_ticket_note(refusal, attempt.reason or None)
        if detail:
            note(State.LOGGED_OUT, 'the client has to log in again', detail)
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
        note(State.NEED_VNC, 'waiting for a human in VNC')
        end = time.time() + cfg.vnc_wait
        while time.time() < end:
            if pause(stop, POLL):
                return 0.0
            result = data_plane(cfg)
            if result.online:
                return online('tunnel up after human action', result.detail)
        status.attempts = 0
        note(State.DEGRADED, 'gave up waiting for a human, will retry')

    delay = backoff.next()
    log.info('next attempt in %.0fs', delay)
    return delay


def run_daemon(cfg: Config, once: bool = False) -> int:
    state_file = StateFile(cfg.state_dir)
    status = state_file.read() or Status()
    client = portal_mod.PortalClient(cfg)
    # `ATRUST_CLIENT_API=0` takes the client's own interface out of the cycle entirely - no
    # status read, no event channel, no ticket path - which is the data-plane-only supervisor for
    # a deployment that wants an interface nobody documents out of its recovery path.
    api = clientapi.ClientAPI(cfg) if cfg.client_api else None
    if api is None:
        log.info("the client's own API is off (ATRUST_CLIENT_API=0); "
                 'the supervisor reads the data plane only')
    backoff = Backoff()
    stop = threading.Event()
    # The client opens on "Connection Options" and asks for the portal address
    # unless it finds it in its own config; that config lives outside the
    # mounted profile, so a recreated container would ask again.
    uiauto.seed_address(cfg)

    def _handler(signum, _frame):
        log.info('signal %s received, shutting down', signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)

    # The client's own event channel, watched in the background: a transition on
    # the client's side (the portal ending the session, the tunnel going down,
    # the client coming back) sets `poller.wake` and cuts the inter-cycle wait.
    # The woken cycle is unchanged and the probe still decides. `--once` has no
    # wait to cut, so it does not start it.
    poller = None
    if not once and api is not None:
        poller = clientapi.EventPoller(api, stop)
        poller.start()

    while not stop.is_set():
        wake = poller.take_wake() if poller is not None else ''
        try:
            delay = cycle(cfg, client, state_file, status, backoff, stop, api, wake)
        except Exception as exc:  # noqa: BLE001 - the supervisor must survive anything
            log.exception('cycle failed: %s', exc)
            delay = backoff.next()
            log.info('retrying in %.0fs', delay)
        if once or stop.is_set():
            break
        pause(stop, delay, poller.wake if poller is not None else None)

    # The event poller is not joined: its worst case is one bounded long poll,
    # and the container's stop path is budgeted at well under podman's own
    # timeout - the stop event ends its loop, the process exit takes the rest.
    # The container stops when PID 1 exits, and podman SIGKILLs whatever is left
    # after its own timeout: give the client the SIGTERM it never got before.
    if stop.is_set():
        started = time.time()
        if not tokens.stop_client_family():
            log.warning('the client family outlived the stop')
        log.info('client stop took %.2fs', time.time() - started)
        # What the sweep left reparents to this process; collect it before PID 1
        # goes, so the pids limit does not carry entries of a container that is
        # already gone.
        reap_orphans()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='atrustd', description=__doc__.splitlines()[0])
    parser.add_argument('--daemon', action='store_true', help='supervise forever (default)')
    parser.add_argument('--once', action='store_true', help='run a single supervision cycle')
    parser.add_argument('--status', action='store_true', help='print the last known status as JSON')
    parser.add_argument('--login-probe', action='store_true', help='only test the portal login flow')
    parser.add_argument('--apps', action='store_true',
                        help='print the apps the portal grants (launch url/method)')
    parser.add_argument('--totp', action='store_true',
                        help='print the current TOTP code from ATRUST_TOTP_KEY (RFC 6238); nothing '
                             'is submitted, the code is for the human in the VNC session')
    parser.add_argument('--refresh', action='store_true',
                        help='with --apps: log in again and fetch the list (new session, the '
                             'client has to log in afterwards)')
    parser.add_argument('--padding', default='pkcs1', choices=['pkcs1', 'oaep'], help='RSA padding for the password')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    # --totp is pure arithmetic on a local secret: it must work without the portal's own
    # configuration (the operator may run it from a checkout on the host during a hand-over).
    if args.totp:
        secret = os.environ.get(totp_mod.ENV_KEY, '')
        if not secret:
            log.error('--totp needs %s: the base32 secret the portal showed when the account '
                      'enrolled its authenticator app', totp_mod.ENV_KEY)
            return 2
        try:
            code = totp_mod.code(secret)
        except ValueError as exc:
            log.error('%s is unusable: %s', totp_mod.ENV_KEY, exc)
            return 2
        print(code)
        print('(valid for %ds; a new code every %ds)' % (totp_mod.remaining(), totp_mod.STEP))
        return 0

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
        log.info('login: ok=%s %s ticket=%d chars', result.ok,
                 portal_mod.answer_text(result.code, result.message, result.answer_class),
                 len(result.ticket))
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
            log.error('cannot list the apps, the portal login failed: %s',
                      portal_mod.answer_text(result.code, result.message, result.answer_class))
            return 1
        return 0 if publish_apps(cfg, client) else 1

    return run_daemon(cfg, once=args.once)


if __name__ == '__main__':
    sys.exit(main())
