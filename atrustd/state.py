# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Supervisor state: what atrustd believes about the tunnel, plus the state file
that humans (and ``atrustd --status``) read.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

log = logging.getLogger('atrustd.state')


def image_suffix(data: bytes) -> str:
    """The portal serves its captcha as PNG or JPEG without saying which."""
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8'):
        return 'jpg'
    return 'img'


class State(str, Enum):
    STARTING = 'STARTING'
    ONLINE = 'ONLINE'
    DEGRADED = 'DEGRADED'
    LOGGED_OUT = 'LOGGED_OUT'
    NEED_VNC = 'NEED_VNC'


HUMAN_HINTS = {
    State.STARTING: 'starting up',
    State.ONLINE: 'tunnel is up, nothing to do',
    State.DEGRADED: 'client is running but the tunnel is not usable yet',
    State.LOGGED_OUT: 'session is gone, trying to log in again',
    State.NEED_VNC: 'human action required: open VNC and finish the login/captcha',
}


@dataclass
class Status:
    state: str = State.STARTING.value
    since: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    attempts: int = 0
    message: str = ''
    detail: str = ''
    vnc_hint: str = ''

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


class Backoff:
    """Exponential backoff with a ceiling; reset() on success."""

    def __init__(self, base: float = 15.0, factor: float = 2.0, cap: float = 600.0):
        self.base, self.factor, self.cap = base, factor, cap
        self.round = 0

    def next(self) -> float:
        delay = min(self.cap, self.base * (self.factor ** self.round))
        self.round += 1
        return delay

    def reset(self) -> None:
        self.round = 0


class StateFile:
    def __init__(self, directory: Path):
        self.dir = directory
        self.path = directory / 'state.json'
        self.vnc_hint_path = directory / 'NEED_VNC'

    def write(self, status: Status) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(status.to_json(), encoding='utf-8')
            tmp.replace(self.path)
        except OSError as exc:
            log.warning('cannot write %s: %s', self.path, exc)

    def read(self) -> Status | None:
        try:
            return Status(**json.loads(self.path.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError):
            return None

    def set_vnc_hint(self, text: str, captcha: bytes | None = None) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.vnc_hint_path.write_text(text + '\n', encoding='utf-8')
        self.clear_captcha()
        if captcha:
            (self.dir / ('captcha.%s' % image_suffix(captcha))).write_bytes(captcha)
        return self.vnc_hint_path

    def clear_vnc_hint(self) -> None:
        try:
            self.vnc_hint_path.unlink()
        except FileNotFoundError:
            pass
        self.clear_captcha()

    def clear_captcha(self) -> None:
        for path in self.dir.glob('captcha.*'):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
