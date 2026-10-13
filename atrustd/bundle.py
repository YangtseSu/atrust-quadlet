# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One tarball of a bump's own evidence, built to be safe to read and to hand over.

The client version moves by hand (`base/build-args/<arch>.args` plus a live acceptance), and a bump
can move something nothing documents: the whole local API of `docs/CLIENT-LOCAL-API.md` was measured
out of the running client, not published. Both sibling implementations ship a capture for exactly
this - `zju-connect`'s `-debug-pcap-file`/`-debug-tls-log-file` and `EZ4Connect`'s profile pair - and
both are secret-bearing by their own documentation. This one is built the other way around: it
carries what the engine, the client and the data plane said, and nothing that authenticates.

`atrustd --bundle` writes one timestamped tarball into `ATRUST_STATE_DIR` (0600, and every member
0600) holding

    manifest.txt           what this is: the versions, the base image, one line per member
    engine/state.json      the supervisor's own state (`atrustd --status`)
    engine/NEED_VNC        the hand-over hint, when one is pending
    engine/captcha.<ext>   the captcha image served beside it, when one is
    engine/routes.txt      `ip route show dev <tun>` - the tunnel's own table
    client/status.json     the client's own `/v1/service/status` answer
    client/addr.conf       the portal address the client's own config carries
    client/log-tail.txt    the tail of the client's own log (`uiauto.tray_log`'s file)
    system/atrust-version  the client version the image was built with

and it deliberately leaves out what would make it a secret: `device-id` (the deployment's own id),
the client's cookie store (`tid`/`tid.sig` are session credentials) and the engine's environment.
Nothing here is a decision input - the supervisor never reads a bundle - and a member that is not
there (no hand-over pending, a client that is down, a state directory that was just recreated) is
one line in the manifest instead of a failure.
"""
from __future__ import annotations

import io
import json
import logging
import os
import tarfile
import time
from pathlib import Path
from typing import Any

from . import clientapi, probe, uiauto

log = logging.getLogger('atrustd.bundle')

# How much of the client's own log goes in. The profile grows ~0.2 GB/day (B02) and the tray's
# daily file is the one series with no rotation ceiling of its own, so the bundle takes a *tail*
# and never the file: 256 KiB is the last ~1.5 h of a measured ~4 MiB/day day, which is what a
# bump regression has to show.
LOG_TAIL_BYTES = 256 * 1024

MANIFEST = 'manifest.txt'
STATE = 'engine/state.json'
HINT = 'engine/NEED_VNC'
CAPTCHA_PREFIX = 'engine/captcha.'
ROUTES = 'engine/routes.txt'
STATUS = 'client/status.json'
ADDR = 'client/addr.conf'
LOG_TAIL = 'client/log-tail.txt'
ATRUST_VERSION = 'system/atrust-version'

# `/v1/service/init`'s measured request body (`docs/CLIENT-LOCAL-API.md`): the client's own answer
# carries `clientVersion`, which no other read does - the `/v1/service/status` answer has the
# session, not the build.
INIT_BODY: dict[str, str] = {'pubKey': '', 'verifyCode': ''}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _pretty(answer: Any) -> bytes | None:
    """One client answer as the bundle carries it, or None when there was none."""
    if answer is None:
        return None
    return (json.dumps(answer, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def _session(api, path: str, data: dict | None = None) -> tuple[Any, str]:
    """One read of the client's own loopback service: the answer, or why there is none."""
    try:
        return api.session(path, data), "the client's own %s answer" % path
    except Exception as exc:  # noqa: BLE001 - a bundle must survive a client that is down
        return None, str(exc)


def _log_tail(cfg) -> tuple[bytes | None, str, str]:
    """The tail of the client's own log (`uiauto.tray_log`: the newest `aTrustTray*.log`)."""
    path = uiauto.tray_log(cfg)
    if path is None:
        return None, '', 'no aTrustTray*.log under %s' % cfg.client_log_dir
    try:
        size = path.stat().st_size
        with path.open('rb') as handle:
            if size > LOG_TAIL_BYTES:
                handle.seek(size - LOG_TAIL_BYTES)
            data = handle.read(LOG_TAIL_BYTES)
    except OSError as exc:
        return None, '', 'cannot read %s - %s' % (path.name, exc)
    if size > LOG_TAIL_BYTES:
        return data, 'the last %d of %d bytes of %s' % (len(data), size, path.name), ''
    return data, 'all %d bytes of %s' % (size, path.name), ''


def _add_member(tar: tarfile.TarFile, name: str, data: bytes, when: float) -> None:
    """One tar member, mode 0600: a bundle is evidence, and it carries the account name."""
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(when)
    info.mode = 0o600
    info.uid = info.gid = 0
    tar.addfile(info, io.BytesIO(data))


def _manifest(when: time.struct_time, facts: list[tuple[str, str]], notes: list[str]) -> bytes:
    lines = ['atrustd bundle, created %s' % time.strftime('%Y-%m-%dT%H:%M:%SZ', when), '']
    lines += ['%-16s%s' % (label, text) for label, text in facts]
    lines += ['', 'members:'] + ['  %s' % note for note in notes]
    return ('\n'.join(lines) + '\n').encode('utf-8')


def write(cfg, api=None, now: float | None = None) -> Path:
    """Collect one bundle into `cfg.state_dir` and return its path.

    ``api`` is a `clientapi.ClientAPI`, or a stand-in in the tests; None means the client's own
    interface is off (`ATRUST_CLIENT_API=0`) or none was handed in, and the bundle records that
    instead of reading it - the switch is the deployment's own promise that the interface is not
    used, and a diagnostic is no exception.

    Only the tarball's own write can fail (an OSError the caller reports); every member inside it
    degrades to a line in the manifest, because a bundle is what one collects when something is
    already wrong.
    """
    created = time.time() if now is None else now
    when = time.gmtime(created)
    if api is None and getattr(cfg, 'client_api', True):
        api = clientapi.ClientAPI(cfg)

    members: list[tuple[str, bytes]] = []
    notes: list[str] = []

    def add(name: str, data: bytes | None, present: str, absent: str) -> None:
        if data is None:
            notes.append('%s: not there - %s' % (name, absent))
        else:
            members.append((name, data))
            notes.append('%s: %d bytes - %s' % (name, len(data), present))

    state_dir = Path(cfg.state_dir)
    add(STATE, _read(state_dir / 'state.json'),
        "the supervisor's own state (`atrustd --status`)", 'no state file written yet')
    add(HINT, _read(state_dir / 'NEED_VNC'), 'the hand-over hint', 'no hand-over is pending')
    captcha = sorted(state_dir.glob('captcha.*'))
    if captcha:
        add('engine/%s' % captcha[0].name, _read(captcha[0]),
            'the captcha image served beside the hint', 'the captcha image is unreadable')
    else:
        notes.append('%s<ext>: not there - no captcha is being served' % CAPTCHA_PREFIX)

    lines, route_detail = probe.route_lines(cfg.tun)
    add(ROUTES, '\n'.join(lines).encode('utf-8'), route_detail,
        'the route table could not be read')

    version = _read(cfg.client_version_file)
    client_version = ''
    if api is None:
        note = "the client's own API is off (ATRUST_CLIENT_API=0) or was not handed in"
        add(STATUS, None, '', note)
    else:
        answer, note = _session(api, '/v1/service/status')
        add(STATUS, _pretty(answer), note, note)
        init, why = _session(api, '/v1/service/init', INIT_BODY)
        client_version = str(((init or {}).get('data') or {}).get('clientVersion') or '')
        if not client_version:
            notes.append('running client: not read - %s' % why)

    add(ADDR, _read(cfg.client_addr_conf), "the client's own portal address",
        'the client config carries no address file')
    add(LOG_TAIL, *_log_tail(cfg))
    add(ATRUST_VERSION, version, 'the version the client image was built with',
        'the image writes no version file')

    facts = [
        ('client image', (version or b'').decode('utf-8', 'replace').strip() or 'not recorded'),
        ('running client', client_version + " (its own /v1/service/init answer)"
         if client_version else 'not read'),
        ('base image', os.environ.get('ATRUST_BASE_REF', '').strip()
         or 'not recorded (the image carries no ATRUST_BASE_REF)'),
    ]
    manifest = _manifest(when, facts, notes)

    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / ('atrust-bundle-%s.tar.gz' % time.strftime('%Y%m%d-%H%M%S', when))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.chmod(path, 0o600)   # O_CREAT's mode only applies to a file it made itself
        with os.fdopen(fd, 'wb') as handle:
            with tarfile.open(fileobj=handle, mode='w:gz') as tar:
                _add_member(tar, MANIFEST, manifest, created)
                for name, data in members:
                    _add_member(tar, name, data, created)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    log.info('bundle written to %s (%d member(s), %d bytes)', path, len(members) + 1,
             path.stat().st_size)
    return path
