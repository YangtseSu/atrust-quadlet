# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read and write the aTrust client's own cookie store.

The client's Chromium profile keeps its portal cookies in a plain SQLite
database (``/root/.aTrust/AppCache/Cookies``, ``value`` column in clear text).
Writing ``tid``/``tid.sig`` there is how this project makes the *client's* own
login skip the graphical captcha - the tokens live with the client, survive on
the mounted volume, and are never passed around as user-supplied parameters.

The client (Electron tray) is stopped around the write: it caches cookies in
memory and would otherwise overwrite them on exit.
"""
from __future__ import annotations

import logging
import sqlite3
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger('atrustd.tokens')

CLIENT_PATTERNS = ('aTrustTray2', 'aTrustTray')
# The whole client, for the way out of the container: the tray (with its
# aTrustTray2 helper and every Electron child), the agent (the plugin daemon and
# the core plugin it forks) and the tunnel with its watchdog child. The tunnel
# detaches and reparents to PID 1, so a parent-based cleanup never reaches it,
# and the pattern has to be the binary's path: `pkill -x` would compare the
# command name, which the kernel truncates to 15 characters (aTrustXtunnel-6).
CLIENT_FAMILY = (
    '/aTrust/aTrustTray',
    '/resources/bin/aTrustAgent',
    '/resources/bin/aTrustXtunnel-64',
)
TID = ('tid', 'tid.sig')

# Chromium stores timestamps as microseconds since 1601-01-01.
_EPOCH_OFFSET_US = 11644473600 * 1_000_000


def chrometime(offset_seconds: int = 0) -> int:
    return int(time.time() * 1_000_000) + _EPOCH_OFFSET_US + offset_seconds * 1_000_000


def read(db: Path, host: str) -> dict[str, str]:
    if not db.exists():
        return {}
    con = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    try:
        rows = con.execute(
            'SELECT name, value FROM cookies WHERE host_key=? AND name IN (?,?)', (host, *TID)
        ).fetchall()
    finally:
        con.close()
    return {name: value for name, value in rows if value}


def _upsert(con: sqlite3.Connection, host: str, name: str, value: str, ttl_days: int = 30) -> None:
    cur = con.execute(
        'SELECT * FROM cookies WHERE host_key=? AND name=? AND path=?', (host, name, '/')
    )
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    cur.close()
    base = dict(zip(cols, row)) if row else {}
    now = chrometime()
    record = {
        'creation_utc': base.get('creation_utc') or now,
        'host_key': host,
        'top_frame_site_key': base.get('top_frame_site_key', ''),
        'name': name,
        'value': value,
        'path': '/',
        'expires_utc': now + ttl_days * 86400 * 1_000_000,
        'is_secure': 1,
        'is_httponly': base.get('is_httponly', 1),
        'last_access_utc': now,
        'has_expires': 1,
        'is_persistent': 1,
        'priority': base.get('priority', 1),
        'encrypted_value': b'',
        'samesite': base.get('samesite', -1),
        'source_scheme': base.get('source_scheme', 1),
        'source_port': base.get('source_port', 443),
        'last_update_utc': now,
    }
    known = [c for c in cols if c in record]
    con.execute('DELETE FROM cookies WHERE host_key=? AND name=? AND path=?', (host, name, '/'))
    con.execute(
        'INSERT INTO cookies (%s) VALUES (%s)' % (','.join(known), ','.join('?' * len(known))),
        tuple(record[c] for c in known),
    )


def write(db: Path, host: str, cookies: dict[str, str]) -> None:
    """Write tid/tid.sig into the client profile (creates nothing else)."""
    wanted = {k: v for k, v in cookies.items() if k in TID and v}
    if not wanted:
        raise ValueError('no tid/tid.sig to write')
    if not db.exists():
        raise FileNotFoundError('client cookie database %s not found (client never ran?)' % db)
    con = sqlite3.connect(str(db), timeout=15)
    try:
        con.execute('BEGIN IMMEDIATE')
        for name, value in wanted.items():
            _upsert(con, host, name, value)
        con.commit()
    finally:
        con.close()
    log.info('wrote %s into %s', ','.join(sorted(wanted)), db)


def _live_pids(pattern: str) -> list[int]:
    """PIDs matching pattern whose process is not a zombie."""
    p = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True)
    live = []
    for raw in p.stdout.split():
        try:
            with open('/proc/%s/stat' % raw, encoding='utf-8', errors='replace') as fh:
                state = fh.read().rsplit(') ', 1)[1].split()[0]
        except (OSError, IndexError):
            continue
        if state != 'Z':
            live.append(int(raw))
    return live


def _client_pids() -> list[int]:
    seen: list[int] = []
    for pattern in CLIENT_PATTERNS:
        for pid in _live_pids(pattern):
            if pid not in seen:
                seen.append(pid)
    return seen


def _family_pids() -> list[int]:
    seen: list[int] = []
    for pattern in CLIENT_FAMILY:
        for pid in _live_pids(pattern):
            if pid not in seen:
                seen.append(pid)
    return seen


def _stop(patterns: tuple[str, ...], pids: Callable[[], list[int]], timeout: float,
          settle: float = 1.0, interval: float = 0.3) -> bool:
    """SIGTERM `patterns`, wait up to `timeout`, SIGKILL the rest, wait `settle`.

    Zombies do not count as alive (see `_live_pids`): the tunnel exits on SIGTERM
    but nothing reaps it, and waiting for the corpse would spend the whole
    timeout on a process that is already gone.
    """
    before = len(pids())
    for pattern in patterns:
        subprocess.run(['pkill', '-TERM', '-f', pattern], check=False)
    deadline = time.time() + timeout
    while time.time() < deadline and pids():
        time.sleep(interval)
    survivors = pids()
    if survivors:
        # The Electron children (zygote, gpu, renderer) take the signal and keep
        # running; the trays and the tunnel are gone by now.
        log.info('%d of %d client process(es) ignored SIGTERM, SIGKILLing %s',
                 len(survivors), before, survivors)
        for pattern in patterns:
            subprocess.run(['pkill', '-KILL', '-f', pattern], check=False)
        deadline = time.time() + settle
        while time.time() < deadline and pids():
            time.sleep(interval)
    return not pids()


def stop_client(timeout: float = 20.0) -> bool:
    """Stop the tray so the cookie database can be written safely.

    The base image's start.sh loop brings the client back a few seconds later,
    which is exactly what we want: the restarted client loads the new cookies.
    """
    return _stop(CLIENT_PATTERNS, _client_pids, timeout)


def stop_client_family(timeout: float = 1.0, settle: float = 0.5) -> bool:
    """Stop the whole client family, on the daemon's way out of the container.

    The stop path is the only caller: `stop_client()` above deliberately leaves
    the agent and the tunnel alone so a token refresh only reloads the tray.
    SIGTERM goes out first - the tunnel and the trays leave on it - and SIGKILL
    covers the Electron children, which do not. The wait is short and bounded:
    `start-sangfor.sh` brings the client back after about four seconds, the
    container's cgroup takes down whatever survives, and a stop has to cost
    seconds, not the ten podman waits by default.
    """
    return _stop(CLIENT_FAMILY, _family_pids, timeout, settle)


def wait_client(deadline_seconds: float = 120.0, interval: float = 2.0) -> bool:
    """Wait until the tray is running again (start.sh restarts it)."""
    end = time.time() + deadline_seconds
    while time.time() < end:
        if _client_pids():
            return True
        time.sleep(interval)
    return False
