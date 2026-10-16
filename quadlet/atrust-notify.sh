#!/bin/sh
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# atrustd states -> desktop notifications (atrust-quadlet).
#
# Reads the supervisor's state from the mounted state directory (falling back to
# copying it out of the container when the mount is absent), compares
# `(state, since)` with a marker under $XDG_RUNTIME_DIR and sends exactly one
# notification per transition: NEED_VNC is critical and carries the hint line
# and the captcha, DEGRADED/LOGGED_OUT and the recovery to ONLINE are normal.
# Everything it writes is its own: the marker and its temporaries. Nothing of
# the container is modified and nothing else depends on this script - removing
# it and its units removes the feature.
#
# Environment overrides:
#   ATRUST_CONTAINER      container name (default: atrust)
#   ATRUST_STATE_HOST_DIR host side of the container's state directory, e.g.
#                         ~/.atrust-data/run when atrust.container mounts it
#                         (without it the state is copied out with podman)
#   ATRUST_NOTIFY_MUTE    comma separated classes to keep quiet - NEED_VNC, DEGRADED, LOGGED_OUT,
#                         ONLINE, any case (default: none)
#   ATRUST_ENV_FILE      where the deployment's own portal address is read from when the browser
#                         line is derived (default: ~/.config/atrust.env, key ATRUST_PORTAL_URL)
#   ATRUST_NOTIFY_WORKBENCH what a NEED_VNC notification says about the browser:
#                           auto (default) - the portal address above, and only after the client's
#                             API has answered a probe on one of the host ports the vendor's own
#                             page uses (127.0.0.1, one /v1/detect per port, `curl`). A port that is
#                             bound with nothing behind it - the container gone, the relay stopped -
#                             does not count, so the line appears exactly when the browser path
#                             works. No curl, no readable portal address, no answering port: the
#                             notification says nothing about a browser.
#                           <url>  - name that URL, no probing (a deployment whose publish lives
#                             elsewhere)
#                           no     - never mention a browser
set -eu

CONTAINER="${ATRUST_CONTAINER:-atrust}"
STATE_DIR=/run/atrustd
STATE_HOST_DIR="${ATRUST_STATE_HOST_DIR:-}"
ENV_FILE="${ATRUST_ENV_FILE:-$HOME/.config/atrust.env}"
# The ports the vendor's own page races on the host, in its order (the domain form first). The
# client binds none of them on the host itself - it binds 127.0.0.1:54630/54631 inside the
# container - so an answer here is a published relay.
WORKBENCH_PORTS='54631 54642 54653 54630 54641 54652'
RUNTIME="${XDG_RUNTIME_DIR:-/tmp}"
MARKER="$RUNTIME/atrust-notify.last"

state_file="$RUNTIME/atrust-notify-state.$$"
hint_file="$RUNTIME/atrust-notify-hint.$$"
captcha_copy=''
captcha_icon=''
trap 'rm -f "$state_file" "$hint_file" "$captcha_copy"' EXIT

fail() { echo "atrust-notify: $*" >&2; }

# `ATRUST_NOTIFY_MUTE`: classes to keep quiet, comma separated and case-insensitive. A muted class
# still moves the marker, so it neither rings nor delays a later unmuted one.
mute_list=','
if [ -n "${ATRUST_NOTIFY_MUTE:-}" ]; then
    for mute in $(printf '%s' "$ATRUST_NOTIFY_MUTE" | tr 'a-z' 'A-Z' | tr ',' ' '); do
        case "$mute" in
            NEED_VNC|DEGRADED|LOGGED_OUT|ONLINE) mute_list="$mute_list$mute," ;;
            *) fail "unknown ATRUST_NOTIFY_MUTE class '$mute' (known: NEED_VNC, DEGRADED, LOGGED_OUT, ONLINE)" ;;
        esac
    done
fi

muted() {
    case "$mute_list" in
        *",$1,"*) return 0 ;;
    esac
    return 1
}

api_answers() {  # $1: host port on 127.0.0.1, $2: the portal address for the envelope
    # A plain connect is not enough: a published port stays bound while the container is gone or
    # its relay is stopped (measured 2026-10-16), and the page would then find nothing. The
    # envelope is the shape the vendor's own page sends first; curl without --fail treats any
    # answer as reachable, which is exactly the question here.
    command -v curl >/dev/null 2>&1 || return 1
    envelope=$(printf '{"addr":"%s","type":"web","guid":"","lang":"zh-CN","token":"","data":{}}' "${2%/}")
    curl -sk --max-time 2 -o /dev/null -X POST "https://127.0.0.1:$1/v1/detect" \
        -H 'Content-Type: application/json' -d "$envelope" 2>/dev/null
}

workbench_url() {  # prints what a NEED_VNC notification may name as the browser path, or nothing
    case "${ATRUST_NOTIFY_WORKBENCH:-auto}" in
        no) return 0 ;;
        auto) ;;
        *) printf '%s\n' "$ATRUST_NOTIFY_WORKBENCH"; return 0 ;;
    esac
    [ -r "$ENV_FILE" ] || return 0
    portal=$(sed -n 's/^ATRUST_PORTAL_URL=//p' "$ENV_FILE" | head -n 1)
    portal=${portal#\"}
    portal=${portal%\"}
    [ -n "$portal" ] || return 0
    for port in $WORKBENCH_PORTS; do
        if api_answers "$port" "$portal"; then
            printf '%s\n' "${portal%/}"
            return 0
        fi
    done
    return 0
}

on_host() {  # $1: a file in the state directory; its host path when the mount is there
    [ -n "$STATE_HOST_DIR" ] || return 1
    [ -s "$STATE_HOST_DIR/$1" ] || return 1
    printf '%s\n' "$STATE_HOST_DIR/$1"
}

copy_out() {  # $1: a file in $STATE_DIR, $2: where it goes on the host; failure when absent
    command -v podman >/dev/null 2>&1 || return 1
    # the fallback for a container unit without the state mount; `podman cp`, not `podman exec
    # cat`, because this container's log driver is journald and every exec session writes
    # `container exec` / `container exec_died` records into the journal by itself, outside the
    # process's stderr and outside --log-level - cp creates no exec session
    rm -f "$2"
    podman cp "$CONTAINER:$STATE_DIR/$1" "$2" >/dev/null 2>&1
}

field() {  # $1: state JSON as written by Status.to_json(), $2: key
    # exactly two leading spaces: the writer uses indent=2, so this matches the
    # top level only - the nested `client` object has its own `state` key
    value=$(printf '%s\n' "$1" | sed -n "s/^  \"$2\": \"\(.*\)\"[,]*$/\1/p" | head -n 1)
    if [ -z "$value" ]; then
        value=$(printf '%s\n' "$1" | sed -n "s/^  \"$2\": \([0-9.]*\),*$/\1/p" | head -n 1)
    fi
    printf '%s\n' "$value" | sed 's/\\"/"/g; s/\\n/ /g'
}

fetch_captcha() {  # sets captcha_icon (what notify-send gets); captcha_copy is ours to remove
    for ext in png jpg; do
        if path=$(on_host "captcha.$ext"); then
            captcha_icon="$path"
            return 0
        fi
    done
    for ext in png jpg; do
        candidate="$RUNTIME/atrust-notify-captcha.$$.$ext"
        if copy_out "captcha.$ext" "$candidate" && [ -s "$candidate" ]; then
            captcha_copy="$candidate"
            captcha_icon="$candidate"
            return 0
        fi
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

json=''
if path=$(on_host state.json); then
    json=$(cat "$path")
elif copy_out state.json "$state_file" && [ -s "$state_file" ]; then
    json=$(cat "$state_file")
fi
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
urgency=normal
case "$state" in
    NEED_VNC)
        urgency=critical
        title='aTrust: human action required'
        body=''
        if path=$(on_host NEED_VNC); then
            body=$(sed -n 1p "$path")
        elif copy_out NEED_VNC "$hint_file" && [ -s "$hint_file" ]; then
            body=$(sed -n 1p "$hint_file")
        fi
        case "$body" in
            'NEED_VNC: '*) body=${body#'NEED_VNC: '} ;;
        esac
        if [ -z "$body" ]; then
            body=$(field "$json" message)
        fi
        if [ -z "$body" ]; then
            body='open the VNC desktop and finish the login'
        fi
        # The browser line: with the client's own API published, the portal's page hands a session
        # to the client, so the human can type the login - and its captcha - there instead of inside
        # VNC (measured 2026-10-16: a human's portal login brought a logged-out client up in 55 s).
        # `workbench_url` decides whether that path is available here and what to name. A refused
        # credential or a lockout is not that kind of NEED_VNC: its fix is the env file, and a
        # browser login would be refused the same way (the wording is atrustd's held-class message).
        case "$body" in
            *"refused the password login"*) ;;
            *)
                if workbench=$(workbench_url) && [ -n "$workbench" ]; then
                    body="$body
or finish the login in your browser: $workbench"
                fi
                ;;
        esac
        fetch_captcha
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

if [ "$notify_needed" = 1 ] && muted "$state"; then
    notify_needed=0
fi

if [ "$notify_needed" = 1 ]; then
    if ! send "$urgency" "$title" "$body" "$captcha_icon"; then
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
