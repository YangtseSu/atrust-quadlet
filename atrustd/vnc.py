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
import os

from .state import StateFile

log = logging.getLogger('atrustd.vnc')

VNC_PORT = 5901
# The container's own name, for the complete `podman exec` line the hint hands the operator (the
# notifier reads the same variable, and the Quadlet unit names the container `atrust`).
CONTAINER = os.environ.get('ATRUST_CONTAINER', 'atrust')


def hint(cfg, state_file: StateFile, reason: str, captcha: bytes | None = None) -> str:
    # The TOTP line names the command that actually works here: with the secret in the container's
    # own environment (`ATRUST_TOTP_KEY` in the unit's EnvironmentFile) the one-shot `-e` is noise.
    if os.environ.get('ATRUST_TOTP_KEY'):
        totp = (
            'If the window is asking for a TOTP (二次认证) code, the current one is:\n'
            '  podman exec {container} python3 -m atrustd --totp\n'
        ).format(container=CONTAINER)
    else:
        totp = (
            'If the window is asking for a TOTP (二次认证) code, the current one is:\n'
            '  podman exec -e ATRUST_TOTP_KEY=<base32 secret> {container} python3 -m atrustd --totp\n'
            '  (the secret is the one the portal showed at enrolment; put it in\n'
            '   ~/.config/atrust.env to leave the -e off)\n'
        ).format(container=CONTAINER)
    text = (
        'NEED_VNC: {reason}\n'
        'Open the container desktop and finish the login there:\n'
        '  vncviewer 127.0.0.1:{port}      (password: the container password / PASSWORD env)\n'
        '  ssh -L {port}:127.0.0.1:{port} <host>   # if the container runs elsewhere\n'
        'Inside the desktop you can also reach the client UI via http://127.0.0.1:54631 .\n'
        '{totp}'
        'atrustd keeps watching and continues automatically once the session is up.\n'
    ).format(reason=reason, port=VNC_PORT, container=CONTAINER, totp=totp)
    path = state_file.set_vnc_hint(text, captcha)
    log.warning('human action required (%s); hint written to %s', reason, path)
    for line in text.strip().splitlines():
        log.warning('  %s', line)
    return path
