# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Configuration for atrustd, taken from the environment (set by the Quadlet unit)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _split_targets(raw: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for item in raw.replace(';', ',').split(','):
        item = item.strip()
        if not item:
            continue
        host, _, port = item.partition(':')
        if not host or not port.isdigit():
            raise ValueError('bad probe target %r, expected host:port' % item)
        out.append((host, int(port)))
    return out


@dataclass
class Config:
    portal_url: str
    username: str
    password: str
    probe_targets: list[tuple[str, int]] = field(default_factory=list)
    watch_interval: int = 90
    vnc_wait: int = 900
    lang: str = 'zh-CN'
    client_type: str = 'SDPBrowserClient'
    platform: str = 'Linux'
    state_dir: Path = Path('/run/atrustd')
    client_cookie_db: Path = Path('/root/.aTrust/AppCache/Cookies')
    proxy: str = '127.0.0.1:8888'
    tun: str = 'utun7'
    insecure: bool = True
    logins_before_vnc: int = 2
    device_id: str = ''

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> 'Config':
        env = dict(os.environ if env is None else env)

        def get(name: str, default: str = '') -> str:
            return env.get(name, default).strip()

        password = get('ATRUST_PASSWORD')
        password_file = get('ATRUST_PASSWORD_FILE')
        if not password and password_file:
            password = Path(password_file).read_text(encoding='utf-8').strip()

        portal = get('ATRUST_PORTAL_URL')
        user = get('ATRUST_USERNAME')
        missing = [k for k, v in (('ATRUST_PORTAL_URL', portal), ('ATRUST_USERNAME', user),
                                  ('ATRUST_PASSWORD', password)) if not v]
        if missing:
            raise SystemExit('missing required configuration: %s' % ', '.join(missing))

        return cls(
            portal_url=portal if portal.endswith('/') else portal + '/',
            username=user,
            password=password,
            probe_targets=_split_targets(get('ATRUST_PROBE_TARGET')),
            watch_interval=max(15, int(get('ATRUST_WATCH_INTERVAL', '90'))),
            vnc_wait=max(60, int(get('ATRUST_VNC_WAIT', '900'))),
            lang=get('ATRUST_LANG', 'zh-CN'),
            state_dir=Path(get('ATRUST_STATE_DIR', '/run/atrustd')),
            client_cookie_db=Path(get('ATRUST_CLIENT_COOKIE_DB', '/root/.aTrust/AppCache/Cookies')),
            proxy=get('ATRUST_PROXY', '127.0.0.1:8888'),
            tun=get('ATRUST_TUN', 'utun7'),
            device_id=get('ATRUST_DEVICE_ID'),
        )

    @property
    def host(self) -> str:
        from urllib.parse import urlparse
        return urlparse(self.portal_url).hostname or ''

    def api(self, path: str) -> str:
        return '%s%s' % (self.portal_url.rstrip('/'), path)
