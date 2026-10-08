#!/bin/bash
#
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Entrypoint of atrust-quadlet: vendor stack in the background, supervisor in front.
set -euo pipefail

# Base image plumbing: Xvfb, x11vnc, aTrust client (aTrustAgent + tray), danted,
# tinyproxy, port-forwarding hooks. It loops forever and restarts the client if
# the client dies, which is exactly the behaviour the supervisor wants.
/usr/local/bin/start.sh &

exec python3 -m atrustd --daemon
