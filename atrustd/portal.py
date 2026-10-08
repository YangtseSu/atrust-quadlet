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

The graphical captcha, when the portal asks for it, is served as an image by
    GET /passport/v1/public/checkCode?clientType=..&platform=..&lang=..&rnd=<ms>
and answered inside the login body; this client does not solve it - it reports
CAPTCHA_REQUIRED so the supervisor can hand over to VNC.
"""
from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import logging
import os
import random
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

CAPTCHA_HINTS = ('校验码', '验证码', 'captcha', 'checkCode', 'antiCode')
LOGGED_OUT_CODES = {75500002, 75500001}


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
    ticket: str = ''
    next_service: str = ''
    captcha_required: bool = False
    auth: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    online: bool | None = None
    auth_check: dict[str, Any] = field(default_factory=dict)


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
        # set by login(): the portal refused the request because it wants the
        # graphical captcha, which this client cannot solve (VNC hand-over).
        self.captcha_required = False

    def _host_port(self) -> str:
        parsed = urllib.parse.urlparse(self.cfg.portal_url)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        return '%s:%d' % (parsed.hostname or '', port)

    def _sdp_env(self) -> str:
        return base64.b64encode(json.dumps({'deviceId': self._device_id()}).encode()).decode()

    def _device_id(self) -> str:
        """Stable per container: the SPA derives a device id from the machine."""
        if self.device_id:
            return self.device_id
        seed = ''
        for path in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
            try:
                seed = Path(path).read_text(encoding='utf-8').strip()
                break
            except OSError:
                continue
        seed = seed or socket.gethostname()
        digest = hashlib.sha1(seed.encode()).hexdigest()
        self.device_id = '00-%s' % digest
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
        if resp.get('code') != 0:
            raise PortalUnreachable('authConfig failed: %s' % resp.get('message'))
        data = resp.get('data') or {}
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
        captcha = code != 0 and any(h.lower() in message.lower() for h in CAPTCHA_HINTS)
        result = LoginResult(
            ok=(code == 0),
            code=code,
            message=message,
            ticket=str(data.get('ticket') or ''),
            next_service=str(data.get('nextService') or ''),
            captcha_required=captcha,
            auth=auth,
            raw=resp,
        )
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
        elif captcha:
            log.warning('portal requires the graphical captcha: %s', message)
        else:
            log.error('password auth failed: code=%s message=%s', code, message)
        self.captcha_required = result.captcha_required
        return result

    def auth_check(self) -> dict[str, Any]:
        resp = self._request('GET', '/passport/v1/auth/authCheck')
        return resp

    def online_info(self) -> dict[str, Any]:
        return self._request('GET', '/passport/v1/user/onlineInfo')

    def is_logged_in(self) -> bool:
        """Cheap session probe (code 75500002 == 会话无效)."""
        try:
            resp = self.online_info()
        except PortalUnreachable:
            return False
        code = int(resp.get('code') or 0)
        if code in LOGGED_OUT_CODES:
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
