#
# SPDX-FileCopyrightText: 2020-2026 the docker-easyconnect contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Vendored from Hagb/docker-easyconnect @ e8fc56a7c518d83b6817e16713f765e3c652e3bf (WTFPL v2, which permits
# redistribution under these terms). The body is unchanged from upstream; see
# base/README.md for provenance and the update procedure.
.PHONY: all clean

all: fake-hwaddr.so

fake-hwaddr.so: fake-hwaddr.c
	${CC} --shared -o fake-hwaddr.so fake-hwaddr.c -ldl -fPIC

clean:
	-rm fake-hwaddr.so
