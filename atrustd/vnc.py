# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ask a human to finish something in the VNC session.

Requirements say: no cookie parameters, and whenever the portal wants the
graphical captcha (first login, or after the tokens went stale) the container
must *say so* and wait, instead of failing in a loop.
"""
from __future__ import annotations

import logging

from .state import StateFile

log = logging.getLogger('atrustd.vnc')

VNC_PORT = 5901


def hint(cfg, state_file: StateFile, reason: str, captcha: bytes | None = None) -> str:
    text = (
        'NEED_VNC: {reason}\n'
        'Open the container desktop and finish the login there:\n'
        '  vncviewer 127.0.0.1:{port}      (password: the container password / PASSWORD env)\n'
        '  ssh -L {port}:127.0.0.1:{port} <host>   # if the container runs elsewhere\n'
        'Inside the desktop you can also reach the client UI via http://127.0.0.1:54631 .\n'
        'atrustd keeps watching and continues automatically once the session is up.\n'
    ).format(reason=reason, port=VNC_PORT)
    path = state_file.set_vnc_hint(text, captcha)
    log.warning('human action required (%s); hint written to %s', reason, path)
    for line in text.strip().splitlines():
        log.warning('  %s', line)
    return path
