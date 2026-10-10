/* SPDX-FileCopyrightText: 2020-2026 the docker-easyconnect contributors
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Vendored from docker-easyconnect/docker-easyconnect @ e8fc56a7c518d83b6817e16713f765e3c652e3bf (WTFPL v2, which permits
 * redistribution under these terms). The body is unchanged from upstream; see
 * base/README.md for provenance and the update procedure. */
#define _GNU_SOURCE
#include <string.h>
#include <stdlib.h>
#include <errno.h>

int getlogin_r(char *buf, size_t bufsize) {
  const char *login = getenv("FAKE_LOGIN");
  if (!login)
    return ENXIO;
  size_t len = strlen(login);
  if (len + 1 > bufsize)
    return ERANGE;
  strcpy(buf, login);
  return 0;
}

const char *getlogin() {
  const char *login = getenv("FAKE_LOGIN");
  if (!login)
    return 0;
  return login;
}
