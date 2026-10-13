# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Portal HTTP client: the same calls the web SPA makes, without a browser.

Verified wire format (Debian/bookworm container, aTrust portal SPA):

    GET  /passport/v1/public/authConfig?clientType=SDPBrowserClient&platform=Linux&lang=zh-CN&needTicket=1
         -> data.pubKey (hex, RSA-2048), data.pubKeyExp ("65537"), data.antiReplayRand,
            data.unitid, data.defaultDomain, data.firstAuth, data.clientInstallMode
    POST /passport/v1/auth/psw?<same query>
         body {"username": "<user>@<domain>", "password": "<hex>", "rememberPwd": "0"}
         password = RSA(pubKey, pubKeyExp) over UTF-8 "<password>_<antiReplayRand>"
         -> data.ticket, data.nextService = "auth/authCheck"
    GET  /passport/v1/auth/authCheck?<same query>       -> data.onlineInfo.isOnline
    GET  /passport/v1/user/onlineInfo?<same query>      -> code 75500002 "会话无效" when logged out

Once the session is live, its cookies mint the ticket the client's own workbench hands to the
agent for the login handshake:
    POST /passport/v1/public/ticketExchange?<same query>
         (no body; the session cookies are the whole request)
         -> data.sidTicket (73 characters)
Measured live 2026-10-11: the agent's `POST /v1/service/start` takes that ticket and brings the
tunnel up with no window and no X11 (`atrustd.clientapi.start`; see docs/CLIENT-LOCAL-API.md).

The graphical captcha, when the portal asks for it, is served as an image by
    GET /passport/v1/public/checkCode?clientType=..&platform=..&lang=..&rnd=<ms>
and answered inside the login body; this client does not solve it - it reads the answer as the
`captcha` class (`classify`) so the supervisor can hand over to VNC.
"""
from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import logging
import os
import random
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger('atrustd.portal')

# The classes a non-zero portal answer is read as. The codes are the stable half - the same
# demand reaches the client's own log in English (`The characters has expired. Please try
# again`) and the engine's login in Chinese (`图形验证码已超时，请重试`), so a decision made on
# the prose alone is a decision made on the language the caller happened to ask for. Each class
# is pinned by what was measured where it is defined; the two whose code is not pinned yet are
# read from the row's own words, in both languages the two logins have shown.
SESSION_INVALID = 'session-invalid'
ALREADY_ONLINE = 'already-online'
CAPTCHA = 'captcha'
WRONG_PASSWORD = 'wrong-password'
RATE_LIMITED = 'rate-limited'

# The session-death codes: `75500002` (`会话无效`, the answer `/v1/user/onlineInfo` gives once
# the session is gone) and `75500001` (session timeout) are this project's own measurements;
# `10000004` is the sibling reimplementation's (`zju-connect`, `client/atrust/auth/request.go`,
# where `authConfig` treats it as `ErrSessionInvalid` while every other code is retried).
SESSION_INVALID_CODES = frozenset({75500002, 75500001, 10000004})
# `75500006 当前账号已在线，无需重复上线` - measured 2026-10-11: the portal keeps the account
# online for ~24 minutes after a client-side logout and refuses a fresh login in the meantime.
ALREADY_ONLINE_CODES = frozenset({75500006})
# `75500000` is the code the graphical-captcha demand arrives as once the attempt went stale
# (`The characters has expired. Please try again` with `data.graphCheckCodeEnable: 1`, read out
# of the client's own log 2026-10-08). The field is the language-independent half; the code
# alone is not enough, because the same generic failure code carries other passport refusals.
CAPTCHA_CODES = frozenset({75500000})
CAPTCHA_HINTS = ('校验码', '验证码', 'captcha', 'checkCode', 'antiCode')

# The wrong-password row's own words: `The username or password is incorrect. You still have 9
# attempts left` is the row the 2026-10-10 drill read off the client's window (it asks
# `lang=en-US`; the engine asks `lang=zh-CN`, and `密码错误` is the phrase the Chinese half of
# the same row is expected to carry). The lockout rows are the family's own brute-force answers,
# which `EZ4Connect` classifies out of the same core's output. A code measured for either class
# joins the sets above and leaves these as the fallback.
WRONG_PASSWORD_HINTS = ('username or password is incorrect', 'attempts left', '密码错误')
RATE_LIMITED_HINTS = ('brute-force', 'too many login failures', 'too many attempts')

# The classes that stop the supervisor's own login attempts: a credential the portal refused or
# a lockout it counted. The credential comes from `ATRUST_PASSWORD`, so nothing inside a running
# process can correct it, and every repeat spends one of the account's own attempts - the row
# carries the count.
HELD_CLASSES = (WRONG_PASSWORD, RATE_LIMITED)


def graph_check_code(data: Any) -> bool:
    """`data.graphCheckCodeEnable == 1`: the portal demands the graphical captcha.

    A field of the `auth/psw` data, not of the message: read out of the client's own log
    (2026-10-08) and the sibling reimplementation's answer to the same demand.
    """
    if not isinstance(data, dict):
        return False
    try:
        return int(data.get('graphCheckCodeEnable') or 0) == 1
    except (TypeError, ValueError):
        return False


def classify(code: int, message: str = '', data: Any = None) -> str:
    """The class `code` (and the row beside it) is read as; '' for success and the unpinned.

    The order is the decision. The two strict codes first - neither can mean anything else -
    then the rows whose own words name a refused credential: they outrank
    `graphCheckCodeEnable`, because a portal that demands the captcha writes that field into
    every psw answer it refuses, whatever the reason, and a wrong password must not read as a
    captcha demand (the retry that would invite is one of the account's attempts). The captcha
    itself comes last: the field first, the words second, the code third.
    """
    if code == 0:
        return ''
    text = (message or '').lower()
    if code in SESSION_INVALID_CODES:
        return SESSION_INVALID
    if code in ALREADY_ONLINE_CODES:
        return ALREADY_ONLINE
    if any(hint.lower() in text for hint in WRONG_PASSWORD_HINTS):
        return WRONG_PASSWORD
    if any(hint.lower() in text for hint in RATE_LIMITED_HINTS):
        return RATE_LIMITED
    if graph_check_code(data) or code in CAPTCHA_CODES:
        return CAPTCHA
    if any(hint.lower() in text for hint in CAPTCHA_HINTS):
        return CAPTCHA
    return ''


def answer_text(code: int, message: str = '', answer_class: str = '') -> str:
    """`code=75500006 class=already-online message=…`, the class beside the code.

    The form the journal, the state detail and the hand-over carry a refusal in; an unpinned
    row (or code 0) simply carries no class.
    """
    parts = ['code=%d' % code]
    if answer_class:
        parts.append('class=%s' % answer_class)
    return ' '.join(parts + ['message=%s' % message])


ATTEMPTS_LEFT = re.compile(r'(\d+)\s+attempts?\s+left', re.IGNORECASE)


def attempts_left(message: str) -> int | None:
    """The account's remaining attempts as a refusal row prints them, or None.

    The counter is the portal's own (`… You still have 9 attempts left`, measured 2026-10-10, one
    decrement of the account's ten); a row that prints none still decides its class, this only
    feeds the hint that says how much is left.
    """
    match = ATTEMPTS_LEFT.search(message or '')
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------- RSA
def _mgf1(seed: bytes, length: int, hash_name: str = 'sha1') -> bytes:
    out = b''
    counter = 0
    while len(out) < length:
        out += hashlib.new(hash_name, seed + counter.to_bytes(4, 'big')).digest()
        counter += 1
    return out[:length]


def _rsa_pkcs1_v15(message: bytes, n: int, e: int) -> bytes:
    k = (n.bit_length() + 7) // 8
    if len(message) > k - 11:
        raise ValueError('message too long for %d-bit key' % n.bit_length())
    pad = bytearray()
    while len(pad) < k - len(message) - 3:
        b = os.urandom(1)[0]
        if b:
            pad.append(b)
    em = b'\x00\x02' + bytes(pad) + b'\x00' + message
    return pow(int.from_bytes(em, 'big'), e, n).to_bytes(k, 'big')


def _rsa_oaep_sha1(message: bytes, n: int, e: int, label: bytes = b'') -> bytes:
    k = (n.bit_length() + 7) // 8
    hlen = 20
    if len(message) > k - 2 * hlen - 2:
        raise ValueError('message too long for OAEP')
    lhash = hashlib.sha1(label).digest()
    ps = b'\x00' * (k - len(message) - 2 * hlen - 2)
    db = lhash + ps + b'\x01' + message
    seed = os.urandom(hlen)
    db_mask = _mgf1(seed, k - hlen - 1)
    masked_db = bytes(a ^ b for a, b in zip(db, db_mask))
    seed_mask = _mgf1(masked_db, hlen)
    masked_seed = bytes(a ^ b for a, b in zip(seed, seed_mask))
    em = b'\x00' + masked_seed + masked_db
    return pow(int.from_bytes(em, 'big'), e, n).to_bytes(k, 'big')


def rsa_encrypt_hex(plaintext: str, pubkey_hex: str, exponent: str, padding: str = 'pkcs1') -> str:
    n = int(pubkey_hex.strip(), 16)
    e = int(exponent.strip() or '65537')
    msg = plaintext.encode('utf-8')
    if padding == 'pkcs1':
        blob = _rsa_pkcs1_v15(msg, n, e)
    elif padding == 'oaep':
        blob = _rsa_oaep_sha1(msg, n, e)
    else:
        raise ValueError('unknown padding %r' % padding)
    return blob.hex()


# ------------------------------------------------------------------------ client
@dataclass
class LoginResult:
    ok: bool
    code: int = -1
    message: str = ''
    answer_class: str = ''
    ticket: str = ''
    next_service: str = ''
    auth: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    online: bool | None = None
    auth_check: dict[str, Any] = field(default_factory=dict)


# The image ships one machine id, identical in every container built from it (measured 2026-10-10:
# the published image's /etc/machine-id, and no md5/sha1/sha256 of it anywhere in the client's own
# profile, so the client's own terminal record does not use it either). Deriving the id this client
# reports from it made unrelated deployments share one device id, and every rebuild replaced it, so
# it is the last resort here, not the default.
MACHINE_ID_FILES = ('/etc/machine-id', '/var/lib/dbus/machine-id')


def _read_device_id(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def _keep_device_id(path: Path, value: str) -> str:
    """The id `path` holds after this call, or '' when nothing could be written.

    O_EXCL: the daemon and a one-off `--login-probe` can reach the first use at
    the same time, and the loser has to take the winner's id, not overwrite it.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_device_id(path) or value
    except OSError:
        return ''
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(value + '\n')
    return value


def _machine_id() -> str:
    for candidate in MACHINE_ID_FILES:
        try:
            value = Path(candidate).read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if value:
            return value
    return socket.gethostname()


class PortalClient:
    def __init__(self, cfg, padding: str = 'pkcs1', timeout: float = 20.0):
        self.cfg = cfg
        self.padding = padding
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        if cfg.insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ctx),
        )
        self.ua = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/151.0.0.0 Safari/537.36')
        # The portal SPA sends these on every call; POSTs need the CSRF token that
        # authConfig hands out in data.security.csrfToken, otherwise the portal
        # answers "非法的请求" (HTTP 400).
        self.rid = base64.b64encode(self._host_port().encode()).decode()
        self.csrf = ''
        self.device_id = getattr(cfg, 'device_id', '') or ''
        self.auth: dict[str, Any] = {}
        self.last_csrf_error = ''
        # The class, code and row of the last login the portal refused ('' and 0 after one it
        # took). The supervisor reads the class across cycles and decides with it: the credential
        # comes from the environment, so a class that says the credential is wrong cannot be
        # repaired by asking again - only a restart or a human can change what this process
        # sends. The graphical-captcha demand is part of the same record: its class is `captcha`.
        self.refused_class = ''
        self.refused_code = 0
        self.refused_message = ''

    def clear_refused(self) -> None:
        """Forget the last refusal: a login the portal took, or a tunnel that came up.

        Both mean the refusal no longer says anything about the world the supervisor is in.
        """
        self.refused_class, self.refused_code, self.refused_message = '', 0, ''

    def _host_port(self) -> str:
        parsed = urllib.parse.urlparse(self.cfg.portal_url)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        return '%s:%d' % (parsed.hostname or '', port)

    def _sdp_env(self) -> str:
        return base64.b64encode(json.dumps({'deviceId': self._device_id()}).encode()).decode()

    def _device_id(self) -> str:
        """The id this session reports as `x-sdp-env`, stable per deployment.

        `ATRUST_DEVICE_ID` wins; otherwise the state directory's `device-id` is
        used, generated on first use. `/etc/machine-id` is only the last resort
        (a state directory that cannot be written): the image ships one file
        every container built from it shares, so it is neither the deployment's
        own nor stable across rebuilds.
        """
        if self.device_id:
            return self.device_id
        path = self.cfg.state_dir / 'device-id'
        value = _read_device_id(path)
        if not value:
            value = _keep_device_id(path, '00-%s' % os.urandom(20).hex())
        if not value:
            log.warning('cannot keep a device id in %s, deriving one from the machine id', path)
            value = '00-%s' % hashlib.sha1(_machine_id().encode()).hexdigest()
        self.device_id = value
        return self.device_id

    def report_env(self, ticket: str) -> dict[str, Any]:
        device_id = self._device_id()
        body = {
            'ticket': ticket,
            'deviceId': device_id,
            'env': {'endpoint': {'device_id': device_id, 'device': {'type': 'browser'}}},
        }
        return self._request('POST', '/controller/v1/public/reportEnv', body=body)

    def warmup(self) -> None:
        """Fetch the portal page once so the portal can set its base cookies."""
        req = urllib.request.Request(self.cfg.portal_url)
        req.add_header('User-Agent', self.ua)
        req.add_header('x-sdp-rid', self.rid)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                resp.read(4096)
        except OSError as exc:
            log.debug('warmup failed: %s', exc)

    def load_client_tokens(self) -> dict[str, str]:
        """Reuse the tid/tid.sig the client already owns.

        These are read from the client's own profile - never taken from a
        parameter - so the portal does not ask for the graphical captcha again.
        """
        stored: dict[str, str] = {}
        try:
            from .tokens import read as read_tokens
            stored = read_tokens(self.cfg.client_cookie_db, self.cfg.host)
        except Exception as exc:  # noqa: BLE001 - token reuse is an optimisation
            log.debug('cannot read client tokens: %s', exc)
            return {}
        for name, value in stored.items():
            self.jar.set_cookie(http.cookiejar.Cookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain=self.cfg.host, domain_specified=True, domain_initial_dot=False,
                path='/', path_specified=True, secure=True, expires=None, discard=False,
                comment=None, comment_url=None, rest={}, rfc2109=False))
        if stored:
            log.info('reusing %s from the client profile', ','.join(sorted(stored)))
        return stored

    def prepare(self) -> None:
        self.warmup()
        self.load_client_tokens()

    # -- plumbing ---------------------------------------------------------------
    def _query(self, extra: dict[str, Any] | None = None) -> str:
        params = {
            'clientType': self.cfg.client_type,
            'platform': self.cfg.platform,
            'lang': self.cfg.lang,
        }
        params.update(extra or {})
        return urllib.parse.urlencode(params)

    def _request(self, method: str, path: str, extra: dict[str, Any] | None = None,
                 body: dict[str, Any] | None = None, referer: str | None = None) -> dict[str, Any]:
        url = '%s?%s' % (self.cfg.api(path), self._query(extra))
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('User-Agent', self.ua)
        req.add_header('Accept', 'application/json, text/plain, */*')
        req.add_header('Content-Type', 'application/json;charset=utf-8')
        req.add_header('Referer', referer or self.cfg.portal_url)
        req.add_header('Origin', self.cfg.portal_url.rstrip('/'))
        req.add_header('x-sdp-rid', self.rid)
        req.add_header('x-sdp-traceid', '%08x' % random.getrandbits(32))
        req.add_header('x-csrf-token', self.csrf)
        env = self._sdp_env()
        if env:
            req.add_header('x-sdp-env', env)
        if log.isEnabledFor(logging.DEBUG):
            safe = {k: ('<%d chars>' % len(v) if k.lower() in ('x-csrf-token', 'x-sdp-env') else str(v)[:40])
                    for k, v in req.header_items()}
            log.debug('%s %s headers=%s', method, path, json.dumps(safe))
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                payload = resp.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode('utf-8', 'replace')
            log.warning('%s %s -> HTTP %s', method, path, exc.code)
        except OSError as exc:
            raise PortalUnreachable('%s %s failed: %s' % (method, path, exc)) from exc
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            raise PortalUnreachable('%s %s returned non-JSON: %s' % (method, path, payload[:200]))

    # -- API --------------------------------------------------------------------
    def auth_config(self) -> dict[str, Any]:
        resp = self._request('GET', '/passport/v1/public/authConfig', {'needTicket': 1})
        code = int(resp.get('code') or 0)
        message = str(resp.get('message') or '')
        data = resp.get('data') or {}
        if code != 0:
            raise PortalUnreachable('authConfig failed: %s'
                                    % answer_text(code, message, classify(code, message, data)))
        self.auth = data
        security = data.get('security') or {}
        if security.get('csrfToken'):
            self.csrf = str(security['csrfToken'])
        return data

    def login(self, auth: dict[str, Any] | None = None) -> LoginResult:
        auth = auth or self.auth_config()
        rand = str(auth.get('antiReplayRand') or '')
        domain = str(auth.get('defaultDomain') or 'local')
        plaintext = '%s_%s' % (self.cfg.password, rand)
        try:
            encrypted = rsa_encrypt_hex(plaintext, str(auth['pubKey']), str(auth.get('pubKeyExp') or '65537'),
                                        padding=self.padding)
        except KeyError as exc:
            raise PortalUnreachable('authConfig has no %s' % exc) from exc
        body = {
            'username': '%s@%s' % (self.cfg.username, domain),
            'password': encrypted,
            'rememberPwd': '0',
        }
        resp = self._request('POST', '/passport/v1/auth/psw', body=body)
        code = int(resp.get('code') or 0)
        message = str(resp.get('message') or '')
        data = resp.get('data') or {}
        answer_class = classify(code, message, data)
        result = LoginResult(
            ok=(code == 0),
            code=code,
            message=message,
            answer_class=answer_class,
            ticket=str(data.get('ticket') or ''),
            next_service=str(data.get('nextService') or ''),
            auth=auth,
            raw=resp,
        )
        # The refusal is kept on the object, not just in the result: the supervisor reads it in
        # the cycles after this one (the credential comes from the environment, so nothing this
        # process does can change what the portal refused).
        if code:
            self.refused_class, self.refused_code, self.refused_message = \
                answer_class, code, message
        else:
            self.clear_refused()
        if result.ok:
            log.info('password auth ok (next=%s)', result.next_service or '-')
            # The SPA reports its environment (device id) before authCheck; the
            # portal answers "env.need = true, timing = pre-login" on the login
            # response, so skipping it leaves the session half-open.
            try:
                self.report_env(result.ticket)
            except PortalUnreachable as exc:
                log.warning('reportEnv failed: %s', exc)
            check = self.auth_check()
            result.auth_check = check
            info = (check.get('data') or {}).get('onlineInfo') or {}
            result.online = bool(info.get('isOnline')) if check.get('code') == 0 else None
            if check.get('code') != 0:
                log.warning('authCheck: code=%s message=%s', check.get('code'), check.get('message'))
        elif answer_class == CAPTCHA:
            log.warning('portal requires the graphical captcha: %s', message)
        else:
            log.error('password auth failed: %s', answer_text(code, message, answer_class))
        return result

    def auth_check(self) -> dict[str, Any]:
        resp = self._request('GET', '/passport/v1/auth/authCheck')
        return resp

    def client_resources(self) -> dict[str, Any]:
        """The apps this account may launch, as the client's own panel shows them.

        The SPA posts one of a few ``resourceType`` shapes and retries with a
        smaller one when the portal rejects it; this is the shape a full client
        uses. The launch URL and method live in ``appInfo[].apps[]``
        (``accessAddress`` / ``openModel.model``).
        """
        body = {'resourceType': {'sdpPolicy': {}, 'appList': {}, 'favoriteAppList': {},
                                 'featureCenter': {}, 'uemSpace': {'params': {'action': 'login'}}}}
        resp = self._request('POST', '/controller/v1/user/clientResource', body=body)
        if resp.get('code') != 0:
            raise PortalUnreachable('clientResource failed: code=%s %s'
                                    % (resp.get('code'), resp.get('message')))
        return ((resp.get('data') or {}).get('appList') or {}).get('data') or {}

    def online_info(self) -> dict[str, Any]:
        return self._request('GET', '/passport/v1/user/onlineInfo')

    def sid_ticket(self) -> str:
        """Mint the SDPC session ticket the client's own workbench hands the agent.

        `POST /passport/v1/public/ticketExchange` is the workbench's login handshake: it takes no
        body and needs no CSRF token - the engine's session cookies carry the whole request
        (verified live 2026-10-11, `docs/CLIENT-LOCAL-API.md`, "The login path, verified") - and
        answers `data.sidTicket` (73 characters). `atrustd.clientapi.start` takes that ticket and
        brings the tunnel up with no window and no X11.

        It needs a live session: with the cookies expired the portal answers a non-zero code (or
        no `data` at all) and this raises ``PortalUnreachable``, i.e. it is not a way around a
        portal that wants a fresh login.
        """
        resp = self._request('POST', '/passport/v1/public/ticketExchange', body={})
        code = int(resp.get('code') or 0)
        if code != 0:
            raise PortalUnreachable('ticketExchange failed: code=%s %s'
                                    % (code, resp.get('message')))
        data = resp.get('data') or {}
        ticket = str(data.get('sidTicket') or '') if isinstance(data, dict) else ''
        if not ticket:
            raise PortalUnreachable('ticketExchange answered no sidTicket: %s' % resp)
        log.info('ticketExchange minted a %d-character sidTicket', len(ticket))
        return ticket

    def is_logged_in(self) -> bool:
        """Cheap session probe; a `session-invalid` answer is the only "no" it knows.

        The `session-invalid` codes are what `/v1/user/onlineInfo` answers once the session is
        gone (`75500002 会话无效`, and the siblings it shares the class with); every other answer
        keeps its old reading - code 0 and `data.isOnline` decide.
        """
        try:
            resp = self.online_info()
        except PortalUnreachable:
            return False
        code = int(resp.get('code') or 0)
        message = str(resp.get('message') or '')
        if classify(code, message, resp.get('data')) == SESSION_INVALID:
            return False
        data = resp.get('data') or {}
        return code == 0 and bool(data.get('isOnline', True))

    def check_code_url(self) -> str:
        return '%s?%s' % (self.cfg.api('/passport/v1/public/checkCode'),
                          self._query({'rnd': int(time.time() * 1000)}))

    def fetch_check_code(self) -> bytes:
        """The captcha image, for saving next to the VNC hint."""
        req = urllib.request.Request(self.check_code_url())
        req.add_header('User-Agent', self.ua)
        with self.opener.open(req, timeout=self.timeout) as resp:
            return resp.read()

    # -- tokens -----------------------------------------------------------------
    def tokens(self) -> dict[str, str]:
        return {c.name: c.value for c in self.jar if c.name in ('tid', 'tid.sig') and c.value}

    def cookie_snapshot(self) -> list[dict[str, str]]:
        return [{'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path} for c in self.jar]


class PortalUnreachable(RuntimeError):
    pass


def jitter(seconds: float, ratio: float = 0.1) -> float:
    return seconds * (1 + random.uniform(-ratio, ratio))
