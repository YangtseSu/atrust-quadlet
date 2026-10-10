#!/bin/bash
#
# SPDX-FileCopyrightText: 2020-2026 the docker-easyconnect contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Vendored from docker-easyconnect/docker-easyconnect @ e8fc56a7c518d83b6817e16713f765e3c652e3bf (WTFPL v2, which permits
# redistribution under these terms). The body is unchanged from upstream; see
# base/README.md for provenance and the update procedure.
# 不支持 nftables 时使用 iptables-legacy
## 感谢 @BoringCat https://github.com/Hagb/docker-easyconnect/issues/5
if {
	[ -z "$IPTABLES_LEGACY" -a -z "$(xtables-legacy-multi iptables-save)" ] &&
	xtables-nft-multi iptables-save &&
	xtables-nft-multi iptables -A INPUT -j ACCEPT &&
	xtables-nft-multi iptables -D INPUT -j ACCEPT; } 1>/dev/null 2>/dev/null
then
	iptables_type=nft
else
	iptables_type=legacy
fi
echo "$iptables_type" > /etc/iptables-type

for exec in /usr/sbin/iptables{-nft,-legacy,}{-save,-restore,}; do
	ln -fs /usr/sbin/xtables-echook-multi "$exec"
done

echo "export ECHACK_NOWARN=1"

