#
# SPDX-FileCopyrightText: 2020-2026 the docker-easyconnect contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Vendored from docker-easyconnect/docker-easyconnect @ e8fc56a7c518d83b6817e16713f765e3c652e3bf (WTFPL v2, which permits
# redistribution under these terms). The body is unchanged from upstream; see
# base/README.md for provenance and the update procedure.
.PHONY: all clean

all: fake-getlogin.so

fake-getlogin.so: fake-getlogin.c
	${CC} --shared -o fake-getlogin.so fake-getlogin.c -ldl -fPIC

clean:
	-rm fake-getlogin.so
