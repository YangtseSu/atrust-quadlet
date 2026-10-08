# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The apps the portal grants this account, with their launch information.

The client's own "App Details" panel shows exactly this (Basics + App Launch
Method): the launch URL, how the client would open it, and the server address
of the resource. Without a desktop the same facts are worth having anyway - a
"Default Browser" app is reachable from the host through the container's
proxies - so they are logged and written to ``apps.json`` in
``ATRUST_STATE_DIR`` whenever a login gave us a portal session, and
``atrustd --apps`` prints them on demand.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger('atrustd.apps')

FILE_NAME = 'apps.json'


@dataclass
class App:
    name: str
    id: str = ''
    group: str = ''
    launch_url: str = ''
    launch_method: str = ''
    addresses: list[str] = field(default_factory=list)
    web_domains: list[str] = field(default_factory=list)

    def line(self) -> str:
        parts = [self.name]
        if self.launch_url:
            parts.append('url=%s' % self.launch_url)
        if self.launch_method:
            parts.append('launch=%s' % self.launch_method)
        if self.addresses:
            parts.append('server=%s' % ' '.join(self.addresses))
        if self.group:
            parts.append('group=%s' % self.group)
        return ' | '.join(parts)


def _addresses(raw: dict) -> list[str]:
    out: list[str] = []
    for item in raw.get('addressList') or []:
        if not isinstance(item, dict) or not item.get('host'):
            continue
        port = item.get('port')
        out.append('%s %s%s' % (item.get('protocol') or 'tcp', item['host'],
                                ':%s' % port if port else ''))
    return out


def summarize(resources: dict) -> list[App]:
    """Flatten the portal's ``clientResource`` payload into one entry per app."""
    apps: list[App] = []
    for group in resources.get('appInfo') or []:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get('name') or '')
        for raw in group.get('apps') or []:
            if not isinstance(raw, dict):
                continue
            web = [str(url) for url in (raw.get('webRelativeDomainList') or []) if url]
            model = raw.get('openModel') or {}
            apps.append(App(
                name=str(raw.get('name') or ''),
                id=str(raw.get('id') or ''),
                group=group_name,
                launch_url=str(raw.get('accessAddress') or (web[0] if web else '')),
                launch_method=str(model.get('model') or ''),
                addresses=_addresses(raw),
                web_domains=web,
            ))
    return apps


def save(state_dir: Path, apps: list[App]) -> Path:
    path = Path(state_dir) / FILE_NAME
    payload = {'count': len(apps), 'apps': [asdict(app) for app in apps]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return path


def lines(apps: list[App]) -> list[str]:
    if not apps:
        return ['the portal granted no apps to this account']
    return ['%d app(s) from the portal:' % len(apps)] + ['  %s' % app.line() for app in apps]


def load(state_dir: Path) -> list[App]:
    """Read back what ``save`` wrote (empty when nothing was published yet)."""
    path = Path(state_dir) / FILE_NAME
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    apps: list[App] = []
    for raw in payload.get('apps') or []:
        if not isinstance(raw, dict):
            continue
        apps.append(App(**{key: value for key, value in raw.items()
                           if key in App.__dataclass_fields__}))
    return apps
