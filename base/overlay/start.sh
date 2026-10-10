#!/bin/bash
#
# SPDX-FileCopyrightText: 2026 Yangtse Su <yangtsesu@gmail.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Container plumbing for the aTrust client: X server + VNC, the HTTP and SOCKS5
# proxies, the iptables/policy-routing the client expects, and the client
# restart loop the supervisor relies on.
#
# Derived from docker-easyconnect/docker-easyconnect @ e8fc56a7c518d83b6817e16713f765e3c652e3bf
# (WTFPL v2), aTrust path only. The detectors, the client prelude (vpn-config.sh),
# the restart loop (start-sangfor.sh) and the iptables hook stay upstream files in
# vendor/; this file drops the EasyConnect/noVNC/chromium paths and replaces
# danted with microsocks (dante-server is not in Debian 13).

eval "$(detect-iptables.sh)"
eval "$(detect-route.sh)"
eval "$(vpn-config.sh)"

forward_ports() {
	if [ -n "$FORWARD" ]; then
		if iptables -t mangle -A PREROUTING -m addrtype --dst-type LOCAL -j MARK --set-mark 2; then
			iptables -t mangle -D PREROUTING -m addrtype --dst-type LOCAL -j MARK --set-mark 2
			iptables -t nat -A POSTROUTING -p tcp -m mark --mark 2 -j MASQUERADE
			ip rule add fwmark 2 table 2
			format_error() { echo Format error in \""$rule"\": "$@" >&2 ; }
			for rule in $FORWARD; do
				array=(${rule//:/ })
				case ${#array[@]} in
					3) src_args="" ;;
					4) src_args="-s ${array[0]}" ;;
					*) format_error; continue ;;
				esac
				dst=${array[-2]}:${array[-1]}
				dport=${array[-3]}
				match_args="$src_args --dport $dport -m addrtype --dst-type LOCAL -i $VPN_TUN"
				iptables -t mangle -A PREROUTING -p tcp $match_args -j MARK --set-mark 2
				iptables -t mangle -A PREROUTING -p udp $match_args -j MARK --set-mark 2
				iptables -t nat -A PREROUTING -p tcp $match_args -j DNAT --to-destination $dst
				iptables -t nat -A PREROUTING -p udp $match_args -j DNAT --to-destination $dst

			done
		else
			echo "Can't append iptables used to forward ports to the host network!" >&2
		fi
	fi
}

start_socks() {
	# SOCKS5 (TCP CONNECT only) for the host. The egress interface is the
	# routing table's business, same as danted's external.rotation: route.
	open_port 1080
	microsocks -i 0.0.0.0 -p 1080 &
}

start_tinyproxy() {
	open_port 8888
	tinyproxy -c /etc/tinyproxy.conf
}

config_vpn_iptables() {
	iptables -t nat -A POSTROUTING -o $VPN_TUN -j MASQUERADE
	open_port 4440
	iptables -t nat -N SANGFOR_OUTPUT
	iptables -t nat -A PREROUTING -j SANGFOR_OUTPUT

	# Reject connections that the tunnel side initiates.
	iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
	iptables -A INPUT -i $VPN_TUN -p tcp -j DROP
}

force_open_ports() {
	# Expose 54631 and friends: the ports the client talks to a browser over.
	tmp_port=20000
	for port in $FORCE_OPEN_PORTS; do
		open_port $port
		open_port $tmp_port
		iptables -t nat -A PREROUTING -p tcp --dport $port -m addrtype --dst-type LOCAL -j REDIRECT --to-port $tmp_port
		socat tcp-listen:$tmp_port,reuseaddr,fork tcp4:127.0.0.1:$port &
		((tmp_port++))
	done
}

start_tigervncserver() {
	# Debian 13's tigervnc keeps its state in ~/.config/tigervnc and only
	# migrates a legacy ~/.vnc when ~/.config is already there (it exits 1
	# otherwise, which used to leave the container without an X server).
	VNC_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/tigervnc"
	mkdir -p "$VNC_DIR"
	if [ ! -e "$VNC_DIR/passwd" ]; then
		if [ -e "$HOME/.vnc/passwd" ]; then
			cp "$HOME/.vnc/passwd" "$VNC_DIR/passwd"
		else
			echo password | tigervncpasswd -f > "$VNC_DIR/passwd"
		fi
	fi
	# Update the VNC password when $PASSWORD is set.
	[ -n "$PASSWORD" ] && printf %s "$PASSWORD" | tigervncpasswd -f > "$VNC_DIR/passwd"

	VNC_SIZE="${VNC_SIZE:-1110x620}"

	open_port 5901
	tigervncserver "$DISPLAY" -geometry "$VNC_SIZE" -localhost no -passwd "$VNC_DIR/passwd" -xstartup flwm
	stalonetray -f 0 2> /dev/null &

	# Put the password on the clipboard for logins that cannot be saved (SMS verification).
	echo "$CLIP_TEXT" | DISPLAY="$DISPLAY" xclip -selection c
}

# Clear the locks in /tmp so the container can be run again.
for f in /tmp/* /tmp/.*; do
	[ "/tmp/.X11-unix" != "$f" ] && rm -rf -- "$f"
done

ulimit -n 1048576

forward_ports
start_socks
start_tinyproxy
config_vpn_iptables
force_open_ports
if [ -z "$DISPLAY" ]; then
	export DISPLAY=:1
	start_tigervncserver
fi

start-sangfor.sh &
wait $!
