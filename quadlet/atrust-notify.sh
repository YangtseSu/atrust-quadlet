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
# and the captcha, DEGRADED/LOGGED_OUT and the recovery to ONLINE are normal,
# the recovery names how long the tunnel was down, and the client's own view
# (state/tunnel, user, login) rides in the ONLINE and LOGGED_OUT bodies.
# `STALE` is its own critical class: a state file that has stopped being
# written means the container or the supervisor is gone, and that is the one
# thing this script should be first at saying. A repeated notification of the
# same class replaces its own earlier one and a different class stacks beside
# it: the class's own notification id is remembered between runs and handed
# back as the daemon's `replaces_id`.
#
# It samples; it is not a log. The tick is the timer's 15 s, so a state shorter
# than that can be missed or caught mid-walk: a live
# ONLINE -> DEGRADED -> LOGGED_OUT -> ONLINE walk of 13.2 s (2026-10-15
# 23:36:02 -> 23:36:15) is 0 to 3 notifications depending on where the tick
# lands. What it reports is the state you would find if you looked now.
#
# Everything it writes is its own: the marker, the class ids and its
# temporaries, 0600 (`umask 077` - a bare /tmp is world readable and the
# captcha is part of a login). Nothing of the container is modified and nothing
# else depends on this script - removing it and its units removes the feature.
#
# Environment overrides:
#   ATRUST_CONTAINER      container name (default: atrust)
#   ATRUST_STATE_HOST_DIR host side of the container's state directory, e.g.
#                         ~/.atrust-data/run when atrust.container mounts it
#                         (without it the state is copied out with podman)
#   ATRUST_NOTIFY_MUTE    comma separated classes to keep quiet - NEED_VNC, DEGRADED, LOGGED_OUT,
#                         ONLINE, STALE, any case (default: none)
#   ATRUST_NOTIFY_STALE_AFTER
#                         seconds of an unmoving state file after which STALE rings (default: 300,
#                         the supervisor writes every cycle; 0 never rings it)
#   ATRUST_NOTIFY_CMD     executable to send through instead of `notify-send`, called with exactly
#                         four arguments `urgency title body icon` (the icon empty when there is
#                         none) - for a host without a session bus (an ntfy or mail wrapper)
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

umask 077

CONTAINER="${ATRUST_CONTAINER:-atrust}"
STATE_DIR=/run/atrustd
STATE_HOST_DIR="${ATRUST_STATE_HOST_DIR:-}"
ENV_FILE="${ATRUST_ENV_FILE:-$HOME/.config/atrust.env}"
STALE_AFTER="${ATRUST_NOTIFY_STALE_AFTER:-300}"
NOTIFY_CMD="${ATRUST_NOTIFY_CMD:-notify-send}"
# The ports the vendor's own page races on the host, in its order (the domain form first). The
# client binds none of them on the host itself - it binds 127.0.0.1:54630/54631 inside the
# container - so an answer here is a published relay.
WORKBENCH_PORTS='54631 54642 54653 54630 54641 54652'
RUNTIME="${XDG_RUNTIME_DIR:-/tmp}"
MARKER="$RUNTIME/atrust-notify.last"
# The daemon's own id for each class's last notification; `replaces_id` is the one mechanism the
# freedesktop spec gives for replacing a notification, and the one GNOME Shell implements.
IDS="$RUNTIME/atrust-notify.ids"

state_file="$RUNTIME/atrust-notify-state.$$"
hint_file="$RUNTIME/atrust-notify-hint.$$"
ids_tmp=''
captcha_copy=''
captcha_icon=''
trap 'rm -f "$state_file" "$hint_file" "$ids_tmp" "$captcha_copy"' EXIT

fail() { echo "atrust-notify: $*" >&2; }

case "$STALE_AFTER" in
    ''|*[!0-9]*)
        fail "ATRUST_NOTIFY_STALE_AFTER='$STALE_AFTER' is not a number of seconds, using 300"
        STALE_AFTER=300
        ;;
esac

# `ATRUST_NOTIFY_MUTE`: classes to keep quiet, comma separated and case-insensitive. A muted class
# still moves the marker, so it neither rings nor delays a later unmuted one.
mute_list=','
if [ -n "${ATRUST_NOTIFY_MUTE:-}" ]; then
    for mute in $(printf '%s' "$ATRUST_NOTIFY_MUTE" | tr 'a-z' 'A-Z' | tr ',' ' '); do
        case "$mute" in
            NEED_VNC|DEGRADED|LOGGED_OUT|ONLINE|STALE) mute_list="$mute_list$mute," ;;
            *) fail "unknown ATRUST_NOTIFY_MUTE class '$mute' (known: NEED_VNC, DEGRADED, LOGGED_OUT, ONLINE, STALE)" ;;
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

field() {  # $1: state JSON as written by Status.to_json(), $2: key, $3: leading spaces (default 2)
    # exactly two leading spaces by default: the writer uses indent=2, so this matches the
    # top level only - a nested object is read with its own indent (the `client` object's
    # fields sit at four, and it has a `state` of its own)
    indent="${3:-  }"
    value=$(printf '%s\n' "$1" | sed -n "s/^$indent\"$2\": \"\(.*\)\"[,]*$/\1/p" | head -n 1)
    if [ -z "$value" ]; then
        value=$(printf '%s\n' "$1" | sed -n "s/^$indent\"$2\": \([0-9.]*\),*$/\1/p" | head -n 1)
    fi
    printf '%s\n' "$value" | sed 's/\\"/"/g; s/\\n/ /g'
}

number() {  # $1: a value out of the state file; its integer part, or nothing when it is not numeric
    case "$1" in
        ''|*[!0-9.]*|*.*.*) printf '\n'; return 0 ;;
    esac
    printf '%s\n' "${1%.*}"
}

format_duration() {  # $1: seconds; a short phrase for a notification body
    if [ "$1" -lt 120 ]; then
        printf '%s s' "$1"
    elif [ "$1" -lt 7200 ]; then
        printf '%s min' "$(( $1 / 60 ))"
    else
        printf '%s h' "$(( $1 / 3600 ))"
    fi
}

add_line() {  # $1: a line, ignored when empty; appends it to $body
    if [ -z "$1" ]; then
        return 0
    fi
    if [ -z "$body" ]; then
        body=$1
    else
        body="$body
$1"
    fi
}

# The client's own view as one line, or nothing - the notifier's half of `Status.client_line()`,
# read out of the nested object above. An older container writes no `client` object at all and an
# unreachable client writes its `error`; both are handled by what the fields are.
client_line() {
    error=$(field "$json" error '    ')
    if [ -n "$error" ]; then
        printf 'client unreachable: %s\n' "$error"
        return 0
    fi
    cstate=$(field "$json" state '    ')
    ctunnel=$(field "$json" tunnel '    ')
    if [ -z "$cstate" ] && [ -z "$ctunnel" ]; then
        return 0
    fi
    line="client ${cstate:-?}/${ctunnel:-?}"
    user=$(field "$json" user '    ')
    if [ -n "$user" ]; then
        line="$line user=$user"
    fi
    login=$(field "$json" login '    ')
    if [ -n "$login" ]; then
        line="$line since=$login"
    fi
    printf '%s\n' "$line"
}

held_title() {  # $1: a body naming a credential the portal refused; the title for that class
    # The one NEED_VNC class whose fix is ~/.config/atrust.env and a restart: the account's own
    # counter, when the row carried one, is the whole headline (`_refused_reason` writes it as
    # `(wrong-password, 3 attempts left)`).
    left=$(printf '%s\n' "$1" | sed -n 's/.*, \([0-9][0-9]*\) attempts left.*/\1/p' | head -n 1)
    if [ -n "$left" ]; then
        printf 'aTrust: password refused, %s attempts left\n' "$left"
    else
        printf 'aTrust: password refused\n'
    fi
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

last_id() {  # $1: class; the id this class last used, or nothing
    [ -r "$IDS" ] || return 0
    sed -n "s/^$1 \([0-9][0-9]*\)$/\1/p" "$IDS" | head -n 1
}

remember_id() {  # $1: class, $2: id - one line per class, so the paths that stack stay apart
    ids_tmp="$IDS.$$"
    if [ -r "$IDS" ]; then
        sed "/^$1 /d" "$IDS" > "$ids_tmp" 2>/dev/null || : > "$ids_tmp"
    else
        : > "$ids_tmp"
    fi
    if ! printf '%s %s\n' "$1" "$2" >> "$ids_tmp" 2>/dev/null; then
        rm -f "$ids_tmp"
        ids_tmp=''
        return 0
    fi
    if ! mv "$ids_tmp" "$IDS" 2>/dev/null; then
        rm -f "$ids_tmp"
    fi
    ids_tmp=''
    return 0
}

send() {  # $1: urgency, $2: title, $3: body, $4: icon (may be empty), $5: class
    if [ "$NOTIFY_CMD" != notify-send ]; then
        # ATRUST_NOTIFY_CMD's contract: one executable, four arguments, the icon empty when there
        # is none. No notification daemon, no ids - the transport is somebody else's.
        "$NOTIFY_CMD" "$1" "$2" "$3" "$4"
        return $?
    fi
    # A repeated class takes its own previous notification back - the daemon's `replaces_id` is
    # the only mechanism the freedesktop spec gives for it (measured 2026-10-16: GNOME Shell 51's
    # own daemon reads no `x-canonical-private-synchronous` hint at all, it reuses the notification
    # when `replaces_id` is one it knows and mints a new one otherwise). `-p` prints the id it
    # settled on, which is the old one when it replaced. The remembered id belongs to this session
    # bus; a daemon that restarted and grew new ids loses at worst one banner to a collision.
    replaces=$(last_id "$5")
    [ -n "$replaces" ] || replaces=0
    if [ -n "$4" ]; then
        id=$(notify-send -p -a aTrust -u "$1" -i "$4" -r "$replaces" -- "$2" "$3")
    else
        id=$(notify-send -p -a aTrust -u "$1" -r "$replaces" -- "$2" "$3")
    fi
    status=$?
    if [ "$status" != 0 ]; then
        return "$status"
    fi
    case "$id" in
        ''|*[!0-9]*) return 0 ;;
    esac
    remember_id "$5" "$id"
    return 0
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

# Staleness: the supervisor writes `updated` every cycle, so an old one means nothing is writing
# the file any more - the container stopped, or `atrust.service` is in its restart loop and the
# last state is frozen at whatever it was. A missing file is not this case and stays silent.
now=$(date +%s)
age=0
stale_key='-'
stale_now=0
updated=$(number "$(field "$json" updated)")
if [ -n "$updated" ] && [ "$STALE_AFTER" -gt 0 ]; then
    age=$(( now - updated ))
    if [ "$age" -gt "$STALE_AFTER" ]; then
        stale_now=1
        stale_key="$updated"
    fi
fi

# The marker: the state and its `since` on the first two lines, the staleness decision on the
# third - `-` while the file moves, the frozen `updated` it already rang for, so one stop rings
# once and a file that freshens afterwards re-arms it.
prev_state=''
prev_since=''
prev_stale=''
if [ -f "$MARKER" ]; then
    prev_state=$(sed -n 1p "$MARKER")
    prev_since=$(sed -n 2p "$MARKER")
    prev_stale=$(sed -n 3p "$MARKER")
fi
if [ "$state" = "$prev_state" ] && [ "$since" = "$prev_since" ] && [ "$stale_key" = "$prev_stale" ]; then
    exit 0
fi

# First run after install (no marker yet): seed the marker silently, except when the tunnel is
# already waiting for a human or nothing is writing the file - the two states that cannot wait
# for a later transition.
notify_needed=1
if [ -z "$prev_state" ]; then
    notify_needed=0
    if [ "$state" = NEED_VNC ] || [ "$stale_now" = 1 ]; then
        notify_needed=1
    fi
fi

class=$state
title=''
body=''
urgency=normal
if [ "$stale_now" = 1 ]; then
    class=STALE
    urgency=critical
    title='aTrust: supervisor silent'
    add_line "no state update for $(format_duration "$age"): the last state it published is $state"
    add_line 'the container or its supervisor is stopped (systemctl --user status atrust.service)'
else
    case "$state" in
        NEED_VNC)
            urgency=critical
            title='aTrust: human action required'
            hint=''
            if path=$(on_host NEED_VNC); then
                hint=$(sed -n 1p "$path")
            elif copy_out NEED_VNC "$hint_file" && [ -s "$hint_file" ]; then
                hint=$(sed -n 1p "$hint_file")
            fi
            case "$hint" in
                'NEED_VNC: '*) hint=${hint#'NEED_VNC: '} ;;
            esac
            if [ -z "$hint" ]; then
                hint=$(field "$json" message)
            fi
            if [ -z "$hint" ]; then
                hint='open the VNC desktop and finish the login'
            fi
            add_line "$hint"
            # The browser line: with the client's own API published, the portal's page hands a
            # session to the client, so the human can type the login - and its captcha - there
            # instead of inside VNC (measured 2026-10-16: a human's portal login brought a
            # logged-out client up in 55 s). `workbench_url` decides whether that path is
            # available here and what to name. A refused credential or a lockout is not that kind
            # of NEED_VNC: its fix is the env file, a browser login would be refused the same way
            # (the wording is atrustd's held-class message), and its title says so.
            case "$hint" in
                *"refused the password login"*)
                    title=$(held_title "$hint")
                    ;;
                *)
                    if workbench=$(workbench_url) && [ -n "$workbench" ]; then
                        add_line "or finish the login in your browser: $workbench"
                    fi
                    ;;
            esac
            fetch_captcha
            ;;
        DEGRADED)
            title='aTrust: tunnel is not usable'
            detail=$(field "$json" detail)
            message=$(field "$json" message)
            if [ -n "$detail" ]; then
                add_line "$detail"
            else
                add_line "$message"
            fi
            ;;
        LOGGED_OUT)
            title='aTrust: session gone, logging in again'
            detail=$(field "$json" detail)
            message=$(field "$json" message)
            if [ -n "$detail" ]; then
                add_line "$detail"
            else
                add_line "$message"
            fi
            add_line "$(client_line)"
            ;;
        ONLINE)
            title='aTrust: tunnel is up'
            message=$(field "$json" message)
            detail=$(field "$json" detail)
            # `message` is the human sentence ("tunnel up after the ticket login") and leads;
            # `detail` is the probe's jargon and follows it.
            lead=$message
            if [ -z "$lead" ]; then
                lead=$detail
                detail=''
            fi
            down=''
            case "$prev_state" in
                DEGRADED|LOGGED_OUT|NEED_VNC)
                    back=$(number "$prev_since")
                    if [ -n "$back" ]; then
                        delta=$(( now - back ))
                        if [ "$delta" -ge 0 ]; then
                            down=$(format_duration "$delta")
                        fi
                    fi
                    ;;
            esac
            if [ -n "$lead" ] && [ -n "$down" ]; then
                lead="$lead (down $down)"
            fi
            if [ -z "$lead" ] && [ -n "$down" ]; then
                lead="down $down"
            fi
            add_line "$lead"
            add_line "$(client_line)"
            add_line "$detail"
            if [ "$prev_state" = ONLINE ]; then
                notify_needed=0
            fi
            ;;
        *)
            notify_needed=0
            ;;
    esac
fi

if [ "$notify_needed" = 1 ] && muted "$class"; then
    notify_needed=0
fi

if [ "$notify_needed" = 1 ]; then
    if ! send "$urgency" "$title" "$body" "$captcha_icon" "$class"; then
        fail "$NOTIFY_CMD failed, retrying on the next run"
        exit 1
    fi
fi

tmp="$MARKER.$$"
if ! printf '%s\n%s\n%s\n' "$state" "$since" "$stale_key" > "$tmp" 2>/dev/null || ! mv "$tmp" "$MARKER" 2>/dev/null; then
    rm -f "$tmp"
    fail "cannot write the marker $MARKER"
    exit 1
fi
