#!/bin/sh
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# atrustd states -> desktop notifications (atrust-quadlet).
#
# Reads the supervisor's state file inside the container, compares (state, since)
# with a marker under $XDG_RUNTIME_DIR and sends exactly one notification per
# transition: NEED_VNC is critical and carries the hint line and the captcha,
# DEGRADED/LOGGED_OUT and the recovery to ONLINE are normal. It only reads the
# container and writes the marker, so the container, the client and the engine
# do not depend on it: removing this script and its units removes the feature.
#
# Environment overrides:
#   ATRUST_CONTAINER                container name (default: atrust)
#   ATRUST_NOTIFY_URGENCY_NEED_VNC  urgency of NEED_VNC (default: critical)
#   ATRUST_NOTIFY_URGENCY_STATE     urgency of DEGRADED/LOGGED_OUT/ONLINE (default: normal)
set -eu

CONTAINER="${ATRUST_CONTAINER:-atrust}"
STATE_DIR=/run/atrustd
RUNTIME="${XDG_RUNTIME_DIR:-/tmp}"
MARKER="$RUNTIME/atrust-notify.last"
URGENCY_NEED_VNC="${ATRUST_NOTIFY_URGENCY_NEED_VNC:-critical}"
URGENCY_STATE="${ATRUST_NOTIFY_URGENCY_STATE:-normal}"

captcha=''
trap 'if [ -n "$captcha" ]; then rm -f "$captcha"; fi' EXIT

fail() { echo "atrust-notify: $*" >&2; }

valid_urgency() {
    case "$1" in
        low|normal|critical) return 0 ;;
    esac
    return 1
}

if ! valid_urgency "$URGENCY_NEED_VNC"; then
    fail "invalid ATRUST_NOTIFY_URGENCY_NEED_VNC='$URGENCY_NEED_VNC', using critical"
    URGENCY_NEED_VNC=critical
fi
if ! valid_urgency "$URGENCY_STATE"; then
    fail "invalid ATRUST_NOTIFY_URGENCY_STATE='$URGENCY_STATE', using normal"
    URGENCY_STATE=normal
fi

in_container() {  # $1: file in $STATE_DIR; empty and failure when it cannot be read
    command -v podman >/dev/null 2>&1 || return 1
    podman exec "$CONTAINER" cat "$STATE_DIR/$1" 2>/dev/null
}

field() {  # $1: state JSON as written by Status.to_json(), $2: key
    value=$(printf '%s\n' "$1" | sed -n "s/^ *\"$2\": \"\(.*\)\"[,]*$/\1/p" | head -n 1)
    if [ -z "$value" ]; then
        value=$(printf '%s\n' "$1" | sed -n "s/^ *\"$2\": \([0-9.]*\),*$/\1/p" | head -n 1)
    fi
    printf '%s\n' "$value" | sed 's/\\"/"/g; s/\\n/ /g'
}

fetch_captcha() {  # a local copy of the captcha, or nothing at all
    for ext in png jpg; do
        candidate="$RUNTIME/atrust-notify-captcha.$$.$ext"
        if in_container "captcha.$ext" > "$candidate" && [ -s "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
        rm -f "$candidate"
    done
    return 0
}

send() {  # $1: urgency, $2: title, $3: body, $4: icon (may be empty)
    if [ -n "$4" ]; then
        notify-send -a aTrust -u "$1" -i "$4" -- "$2" "$3"
    else
        notify-send -a aTrust -u "$1" -- "$2" "$3"
    fi
}

json=$(in_container state.json) || exit 0
if [ -z "$json" ]; then
    exit 0
fi
state=$(field "$json" state)
since=$(field "$json" since)
if [ -z "$state" ] || [ -z "$since" ]; then
    exit 0
fi

prev_state=''
prev_since=''
if [ -f "$MARKER" ]; then
    prev_state=$(sed -n 1p "$MARKER")
    prev_since=$(sed -n 2p "$MARKER")
fi
if [ "$state" = "$prev_state" ] && [ "$since" = "$prev_since" ]; then
    exit 0
fi

# First run after install (no marker yet): seed the marker silently, except when
# the tunnel is already waiting for a human - that is the one state that cannot
# wait for a later transition.
notify_needed=1
if [ -z "$prev_state" ]; then
    notify_needed=0
    if [ "$state" = NEED_VNC ]; then
        notify_needed=1
    fi
fi

title=''
body=''
urgency=$URGENCY_STATE
case "$state" in
    NEED_VNC)
        urgency=$URGENCY_NEED_VNC
        title='aTrust: human action required'
        hint=$(in_container NEED_VNC) || hint=''
        body=$(printf '%s\n' "$hint" | sed -n 1p)
        case "$body" in
            'NEED_VNC: '*) body=${body#'NEED_VNC: '} ;;
        esac
        if [ -z "$body" ]; then
            body=$(field "$json" message)
        fi
        if [ -z "$body" ]; then
            body='open the VNC desktop and finish the login'
        fi
        captcha=$(fetch_captcha)
        ;;
    DEGRADED)
        title='aTrust: tunnel is not usable'
        body=$(field "$json" detail)
        if [ -z "$body" ]; then
            body=$(field "$json" message)
        fi
        ;;
    LOGGED_OUT)
        title='aTrust: session gone, logging in again'
        body=$(field "$json" detail)
        if [ -z "$body" ]; then
            body=$(field "$json" message)
        fi
        ;;
    ONLINE)
        title='aTrust: tunnel is up'
        body=$(field "$json" detail)
        if [ -z "$body" ]; then
            body=$(field "$json" message)
        fi
        if [ "$prev_state" = ONLINE ]; then
            notify_needed=0
        fi
        ;;
    *)
        notify_needed=0
        ;;
esac

if [ "$notify_needed" = 1 ]; then
    if ! send "$urgency" "$title" "$body" "$captcha"; then
        fail "notify-send failed, retrying on the next run"
        exit 1
    fi
fi

tmp="$MARKER.$$"
if ! printf '%s\n%s\n' "$state" "$since" > "$tmp" 2>/dev/null || ! mv "$tmp" "$MARKER" 2>/dev/null; then
    rm -f "$tmp"
    fail "cannot write the marker $MARKER"
    exit 1
fi
