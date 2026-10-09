# syntax=docker/dockerfile:1
#
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The client image is built from base/ (Debian 13 + Sangfor's aTrust package +
# the container plumbing) by the same pipeline, into a throwaway local tag; see
# base/README.md. It is not published on its own: the artefact of this
# repository is the image this file builds.
ARG BASE_IMAGE=localhost/atrust-base:latest
FROM ${BASE_IMAGE}

# The base image ships the aTrust client, the VNC X server, tinyproxy/microsocks
# and the container plumbing (iptables/route/tun). It has no Python, so add the
# only runtime this project needs. No pip/requests/cryptography: the engine is
# stdlib-only (urllib + sqlite3 + a small RSA PKCS#1 v1.5 implementation).
#
# xdotool drives the client's own login window (X level input, atrustd.uiauto);
# xwd (x11-apps) dumps the root window, which uiauto probes to recognise which
# page the window is showing - neither has a Python binding.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 xdotool x11-apps \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY atrustd /opt/atrustd/atrustd
COPY entrypoint.sh /usr/local/bin/atrust-entrypoint.sh
RUN chmod +x /usr/local/bin/atrust-entrypoint.sh

ENV PYTHONPATH=/opt/atrustd \
    PYTHONUNBUFFERED=1 \
    ATRUST_STATE_DIR=/run/atrustd

# start.sh (from the base image) brings up the VNC X server, tinyproxy/microsocks
# and the aTrust client; the entrypoint additionally supervises login state.
ENTRYPOINT ["/usr/local/bin/atrust-entrypoint.sh"]
