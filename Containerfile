# syntax=docker/dockerfile:1
#
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
FROM docker.io/hagb/docker-atrust:latest

# The base image ships the aTrust client, Xvfb, VNC, danted/tinyproxy and the
# container plumbing (iptables/route/tun). It has no Python, so add the only
# runtime this project needs. No pip/requests/cryptography: the engine is
# stdlib-only (urllib + sqlite3 + a small RSA PKCS#1 v1.5 implementation).
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY atrustd /opt/atrustd/atrustd
COPY entrypoint.sh /usr/local/bin/atrust-entrypoint.sh
RUN chmod +x /usr/local/bin/atrust-entrypoint.sh

ENV PYTHONPATH=/opt/atrustd \
    PYTHONUNBUFFERED=1 \
    ATRUST_STATE_DIR=/run/atrustd

# start.sh (inherited from the base image) brings up Xvfb + VNC + the aTrust
# client; the entrypoint additionally supervises login state.
ENTRYPOINT ["/usr/local/bin/atrust-entrypoint.sh"]
